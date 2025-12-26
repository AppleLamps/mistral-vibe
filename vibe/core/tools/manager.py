from __future__ import annotations

from collections.abc import Iterator
import hashlib
import importlib.util
import inspect
from logging import getLogger
from pathlib import Path
import re
import sys
import traceback
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from vibe.core.paths.config_paths import resolve_local_tools_dir
from vibe.core.paths.global_paths import DEFAULT_TOOL_DIR, GLOBAL_TOOLS_DIR
from vibe.core.tools.base import BaseTool, BaseToolConfig
from vibe.core.tools.mcp import (
    RemoteTool,
    create_mcp_http_proxy_tool_class,
    create_mcp_stdio_proxy_tool_class,
    list_tools_http,
    list_tools_stdio,
)
from vibe.core.utils import run_sync

logger = getLogger("vibe")


class MCPServerStatus(BaseModel):
    name: str
    transport: str
    registered_tools: int = 0
    errors: list[str] = Field(default_factory=list)


def _format_exception_line(exc: BaseException) -> str:
    lines = traceback.format_exception_only(exc.__class__, exc)
    return lines[-1].strip() if lines else str(exc)

if TYPE_CHECKING:
    from vibe.core.config import MCPHttp, MCPStdio, MCPStreamableHttp, VibeConfig


class NoSuchToolError(Exception):
    """Exception raised when a tool is not found."""


class ToolManager:
    """Manages tool discovery and instantiation for an Agent.

    Discovers available tools from the provided search paths. Each Agent
    should have its own ToolManager instance.
    """

    def __init__(self, config: VibeConfig) -> None:
        self._config = config
        self._instances: dict[str, BaseTool] = {}
        self._search_paths: list[Path] = self._compute_search_paths(config)
        self._mcp_status: list[MCPServerStatus] = []

        self._available: dict[str, type[BaseTool]] = {
            cls.get_name(): cls for cls in self._iter_tool_classes(self._search_paths)
        }
        self._integrate_mcp()

    @staticmethod
    def _compute_search_paths(config: VibeConfig) -> list[Path]:
        paths: list[Path] = [DEFAULT_TOOL_DIR.path]

        for path in config.tool_paths:
            if path.is_dir():
                paths.append(path)

        if (tools_dir := resolve_local_tools_dir(config.effective_workdir)) is not None:
            paths.append(tools_dir)

        if GLOBAL_TOOLS_DIR.path.is_dir():
            paths.append(GLOBAL_TOOLS_DIR.path)

        unique: list[Path] = []
        seen: set[Path] = set()
        for p in paths:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                unique.append(rp)
        return unique

    @staticmethod
    def _iter_tool_classes(search_paths: list[Path]) -> Iterator[type[BaseTool]]:
        for base in search_paths:
            if not base.is_dir():
                continue

            for path in base.rglob("*.py"):
                if not path.is_file():
                    continue
                name = path.name
                if name.startswith("_"):
                    continue

                stem = re.sub(r"[^0-9A-Za-z_]", "_", path.stem) or "mod"
                digest = hashlib.blake2s(
                    str(path.resolve()).encode("utf-8"), digest_size=6
                ).hexdigest()
                module_name = f"vibe_tools_discovered_{stem}_{digest}"

                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception as exc:
                    logger.warning(
                        "Failed to import tool module %s: %s", path, _format_exception_line(exc)
                    )
                    continue

                for obj in vars(module).values():
                    if not inspect.isclass(obj):
                        continue
                    if not issubclass(obj, BaseTool) or obj is BaseTool:
                        continue
                    if inspect.isabstract(obj):
                        continue
                    yield obj

    @staticmethod
    def discover_tool_defaults(
        search_paths: list[Path] | None = None,
    ) -> dict[str, dict[str, Any]]:
        if search_paths is None:
            search_paths = [DEFAULT_TOOL_DIR.path]

        defaults: dict[str, dict[str, Any]] = {}
        for cls in ToolManager._iter_tool_classes(search_paths):
            try:
                tool_name = cls.get_name()
                config_class = cls._get_tool_config_class()
                defaults[tool_name] = config_class().model_dump(exclude_none=True)
            except Exception as e:
                logger.warning(
                    "Failed to get defaults for tool %s: %s", cls.__name__, e
                )
                continue
        return defaults

    def available_tools(self) -> dict[str, type[BaseTool]]:
        return dict(self._available)

    def mcp_status(self) -> list[MCPServerStatus]:
        return list(self._mcp_status)

    def _integrate_mcp(self) -> None:
        if not self._config.mcp_servers:
            return
        run_sync(self._integrate_mcp_async())

    async def _integrate_mcp_async(self) -> None:
        try:
            http_count = 0
            stdio_count = 0
            self._mcp_status.clear()

            for srv in self._config.mcp_servers:
                match srv.transport:
                    case "http" | "streamable-http":
                        registered, errors = await self._register_http_server(srv)
                        http_count += registered
                        self._mcp_status.append(
                            MCPServerStatus(
                                name=srv.name,
                                transport=srv.transport,
                                registered_tools=registered,
                                errors=errors,
                            )
                        )
                    case "stdio":
                        registered, errors = await self._register_stdio_server(srv)
                        stdio_count += registered
                        self._mcp_status.append(
                            MCPServerStatus(
                                name=srv.name,
                                transport=srv.transport,
                                registered_tools=registered,
                                errors=errors,
                            )
                        )
                    case _:
                        logger.warning("Unsupported MCP transport: %r", srv.transport)

            logger.info(
                "MCP integration registered %d tools (http=%d, stdio=%d)",
                http_count + stdio_count,
                http_count,
                stdio_count,
            )
        except Exception as exc:
            logger.warning("Failed to integrate MCP tools: %s", exc)

    async def _register_http_server(self, srv: MCPHttp | MCPStreamableHttp) -> tuple[int, list[str]]:
        url = (srv.url or "").strip()
        if not url:
            msg = f"MCP server '{srv.name}' missing url for http transport"
            logger.warning(msg)
            return 0, [msg]

        headers = srv.http_headers()
        errors: list[str] = []
        try:
            tools: list[RemoteTool] = await list_tools_http(url, headers=headers)
        except Exception as exc:
            msg = f"MCP HTTP discovery failed for {url}: {exc}"
            logger.warning(msg)
            return 0, [msg]

        added = 0
        for remote in tools:
            try:
                proxy_cls = create_mcp_http_proxy_tool_class(
                    url=url,
                    remote=remote,
                    alias=srv.name,
                    server_hint=srv.prompt,
                    headers=headers,
                )
                self._available[proxy_cls.get_name()] = proxy_cls
                added += 1
            except Exception as exc:
                msg = (
                    f"Failed to register MCP HTTP tool '{getattr(remote, 'name', '<unknown>')}'"
                    f" from {url}: {exc}"
                )
                logger.warning(msg)
                errors.append(msg)
        return added, errors

    async def _register_stdio_server(self, srv: MCPStdio) -> tuple[int, list[str]]:
        cmd = srv.argv()
        if not cmd:
            msg = f"MCP stdio server '{srv.name}' has invalid/empty command"
            logger.warning(msg)
            return 0, [msg]

        errors: list[str] = []

        try:
            tools: list[RemoteTool] = await list_tools_stdio(cmd)
        except Exception as exc:
            msg = f"MCP stdio discovery failed for {cmd!r}: {exc}"
            logger.warning(msg)
            return 0, [msg]

        added = 0
        for remote in tools:
            try:
                proxy_cls = create_mcp_stdio_proxy_tool_class(
                    command=cmd, remote=remote, alias=srv.name, server_hint=srv.prompt
                )
                self._available[proxy_cls.get_name()] = proxy_cls
                added += 1
            except Exception as exc:
                msg = (
                    f"Failed to register MCP stdio tool '{getattr(remote, 'name', '<unknown>')}'"
                    f" from {cmd!r}: {exc}"
                )
                logger.warning(msg)
                errors.append(msg)
        return added, errors

    def get_tool_config(self, tool_name: str) -> BaseToolConfig:
        tool_class = self._available.get(tool_name)

        if tool_class:
            config_class = tool_class._get_tool_config_class()
            default_config = config_class()
        else:
            config_class = BaseToolConfig
            default_config = BaseToolConfig()

        user_overrides = self._config.tools.get(tool_name)
        if user_overrides is None:
            merged_dict = default_config.model_dump()
        else:
            merged_dict = {**default_config.model_dump(), **user_overrides.model_dump()}

        if self._config.workdir is not None:
            merged_dict["workdir"] = self._config.workdir

        return config_class.model_validate(merged_dict)

    def get(self, tool_name: str) -> BaseTool:
        """Get a tool instance, creating it lazily on first call.

        Raises:
            NoSuchToolError: If the requested tool is not available.
        """
        if tool_name in self._instances:
            return self._instances[tool_name]

        if tool_name not in self._available:
            raise NoSuchToolError(
                f"Unknown tool: {tool_name}. Available: {list(self._available.keys())}"
            )

        tool_class = self._available[tool_name]
        tool_config = self.get_tool_config(tool_name)
        self._instances[tool_name] = tool_class.from_config(tool_config)
        return self._instances[tool_name]

    def reset_all(self) -> None:
        self._instances.clear()
