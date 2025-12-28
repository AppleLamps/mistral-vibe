---
name: pytest-async
description: |
  Pytest patterns for async testing in this project. Use when writing tests, debugging test failures,
  or when user mentions "pytest", "async test", "fixture", "mock", or "test coverage".
allowed-tools: Read, Grep, Glob, Bash
---

# Pytest Async Testing Patterns

Guide for writing robust async tests in the mistral-vibe project.

## Instructions

1. **Project test configuration** (from pyproject.toml):
   ```toml
   [tool.pytest.ini_options]
   addopts = "-vvvv -q -n auto --durations=5 --import-mode=importlib"
   timeout = 10
   ```

2. **Async test pattern**:
   ```python
   from __future__ import annotations

   import pytest

   @pytest.mark.asyncio
   async def test_async_operation():
       result = await async_function()
       assert result.success
   ```

3. **Use autouse fixtures from conftest.py**:
   ```python
   # tests/conftest.py provides:
   # - tmp_working_directory (auto)
   # - config_dir (auto)
   # - _mock_api_key (auto)
   # - _mock_platform (auto)

   # Your test automatically gets isolated temp directories
   def test_file_operations(tmp_working_directory):
       file_path = tmp_working_directory / "test.txt"
       file_path.write_text("content")
       assert file_path.exists()
   ```

4. **Mock external services with monkeypatch**:
   ```python
   @pytest.mark.asyncio
   async def test_api_call(monkeypatch):
       async def mock_fetch(*args):
           return {"status": "ok"}

       monkeypatch.setattr("vibe.core.llm.backend.fetch", mock_fetch)
       result = await make_api_call()
       assert result["status"] == "ok"
   ```

5. **Use respx for HTTP mocking**:
   ```python
   import respx
   import httpx

   @pytest.mark.asyncio
   @respx.mock
   async def test_http_client():
       respx.get("https://api.example.com/data").respond(
           json={"key": "value"}
       )
       async with httpx.AsyncClient() as client:
           response = await client.get("https://api.example.com/data")
           assert response.json() == {"key": "value"}
   ```

6. **Create reusable fixtures**:
   ```python
   @pytest.fixture
   def sample_config():
       return {
           "active_model": "test-model",
           "providers": [{"name": "test", "backend": "generic"}],
       }

   @pytest.fixture
   async def agent(sample_config, config_dir):
       from vibe.core.agent import Agent
       from vibe.core.config import VibeConfig
       config = VibeConfig.load(**sample_config)
       return Agent(config=config)
   ```

7. **Snapshot testing for UI**:
   ```python
   # tests/snapshots/ directory
   from tests.snapshots.base_snapshot_test_app import BaseSnapshotTestApp

   class TestMyComponent(BaseSnapshotTestApp):
       async def test_component_renders(self):
           await self.compare_snapshot()
   ```

## Commands

| Task | Command |
|------|---------|
| Run all (no snapshots) | `uv run pytest --ignore tests/snapshots` |
| Run specific file | `uv run pytest tests/path/test_file.py` |
| Run specific test | `uv run pytest tests/path/test_file.py::test_name` |
| Run with pattern | `uv run pytest -k "pattern"` |
| Run snapshots only | `uv run pytest tests/snapshots` |
| Update snapshots | `uv run pytest tests/snapshots --snapshot-update` |

## Test Directory Structure

```
tests/
├── conftest.py           # Global fixtures
├── acp/                   # Agent Client Protocol tests
├── autocompletion/        # Autocomplete tests
├── backend/               # LLM backend tests
├── core/                  # Core module tests
├── skills/                # Skills system tests
├── snapshots/             # UI snapshot tests
├── tools/                 # Tool tests
└── mock/                  # Mock utilities
```

## Examples

- "Write a test for X function" → Async test with fixtures
- "Test is timing out" → Check 10s limit, add mocks
- "Mock the API call" → Use monkeypatch or respx

## Guardrails

- Always use `uv run pytest` (never bare pytest)
- Tests have 10-second timeout by default
- Use fixtures from conftest.py for isolation
- Don't modify snapshot files manually
