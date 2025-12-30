from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.path_security import PathSecurityError, validate_safe_path
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


# Supported image formats and their MIME types
IMAGE_FORMATS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class ImageViewArgs(BaseModel):
    path: str = Field(description="Path to the image file to view.")
    max_dimension: int | None = Field(
        default=1024,
        description="Maximum width or height. Image will be resized if larger. Set to None to disable.",
    )


class ImageViewResult(BaseModel):
    path: str
    format: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    base64_data: str = Field(
        description="Base64-encoded image data for multimodal display."
    )
    was_resized: bool = False


class ImageViewConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_file_size: int = Field(
        default=10_000_000,  # 10MB
        description="Maximum image file size in bytes.",
    )


class ImageViewState(BaseToolState):
    viewed_images: list[str] = Field(default_factory=list)


def _get_image_dimensions(data: bytes) -> tuple[int, int]:
    """Get image dimensions without requiring PIL."""
    # PNG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if data[12:16] == b"IHDR":
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return width, height

    # JPEG
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 8:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):  # SOF markers
                height = int.from_bytes(data[i + 5 : i + 7], "big")
                width = int.from_bytes(data[i + 7 : i + 9], "big")
                return width, height
            length = int.from_bytes(data[i + 2 : i + 4], "big")
            i += 2 + length

    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a"):
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
        return width, height

    # BMP
    if data[:2] == b"BM":
        width = int.from_bytes(data[18:22], "little")
        height = abs(int.from_bytes(data[22:26], "little", signed=True))
        return width, height

    # WebP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8 ":
            # Lossy WebP
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return width, height
        elif data[12:16] == b"VP8L":
            # Lossless WebP
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height

    return 0, 0


class ImageView(
    BaseTool[ImageViewArgs, ImageViewResult, ImageViewConfig, ImageViewState],
    ToolUIData[ImageViewArgs, ImageViewResult],
):
    description: ClassVar[str] = (
        "View an image file. Returns the image as base64-encoded data that can be "
        "displayed in multimodal conversations. Supports PNG, JPEG, GIF, WebP, BMP, "
        "and SVG formats. Useful for viewing screenshots, UI mockups, and diagrams."
    )

    @final
    async def run(self, args: ImageViewArgs) -> ImageViewResult:
        import aiofiles

        # Validate and resolve path
        if not args.path.strip():
            raise ToolError("Path cannot be empty")

        file_path = Path(args.path).expanduser()
        if not file_path.is_absolute():
            file_path = self.config.effective_workdir / file_path

        try:
            resolved_path = file_path.resolve()
        except ValueError:
            raise ToolError(f"Invalid file path: {file_path}")

        project_root = self.config.effective_workdir.resolve()
        try:
            validate_safe_path(resolved_path, project_root)
        except PathSecurityError as e:
            raise ToolError(str(e))

        if not resolved_path.exists():
            raise ToolError(f"Image not found: {resolved_path}")
        if resolved_path.is_dir():
            raise ToolError(f"Path is a directory: {resolved_path}")

        # Check file extension
        suffix = resolved_path.suffix.lower()
        if suffix not in IMAGE_FORMATS:
            raise ToolError(
                f"Unsupported image format: {suffix}. "
                f"Supported: {', '.join(IMAGE_FORMATS.keys())}"
            )

        mime_type = IMAGE_FORMATS[suffix]

        # Check file size
        file_size = resolved_path.stat().st_size
        if file_size > self.config.max_file_size:
            raise ToolError(
                f"Image too large: {file_size:,} bytes "
                f"(max: {self.config.max_file_size:,} bytes)"
            )

        # Read image
        async with aiofiles.open(resolved_path, "rb") as f:
            image_data = await f.read()

        # Get dimensions
        width, height = _get_image_dimensions(image_data)

        # Resize if needed (only with PIL available)
        was_resized = False
        if args.max_dimension and (width > args.max_dimension or height > args.max_dimension):
            try:
                from PIL import Image
                import io

                img = Image.open(io.BytesIO(image_data))
                img.thumbnail((args.max_dimension, args.max_dimension), Image.Resampling.LANCZOS)

                output = io.BytesIO()
                img_format = "PNG" if suffix == ".png" else "JPEG"
                img.save(output, format=img_format, quality=85)
                image_data = output.getvalue()

                width, height = img.size
                was_resized = True
            except ImportError:
                # PIL not available, return original
                pass

        # Encode to base64
        base64_data = base64.b64encode(image_data).decode("ascii")

        # Update state
        self.state.viewed_images.append(str(resolved_path))
        if len(self.state.viewed_images) > 10:
            self.state.viewed_images.pop(0)

        return ImageViewResult(
            path=str(resolved_path),
            format=suffix.lstrip(".").upper(),
            mime_type=mime_type,
            width=width,
            height=height,
            size_bytes=len(image_data),
            base64_data=base64_data,
            was_resized=was_resized,
        )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, ImageViewArgs):
            return ToolCallDisplay(summary="image_view")

        path = Path(event.args.path)
        return ToolCallDisplay(summary=f"image_view: {path.name}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ImageViewResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        size_str = (
            f"{result.size_bytes:,}"
            if result.size_bytes < 10000
            else f"{result.size_bytes // 1000}KB"
        )

        message = f"{result.format} {result.width}x{result.height} ({size_str})"
        if result.was_resized:
            message += " [resized]"

        return ToolResultDisplay(success=True, message=message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Viewing image"
