#!/usr/bin/env python3
"""Verify that the Task tool is properly registered and configured."""

import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging to see debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s - %(name)s - %(message)s",
)


def main() -> int:
    """Verify Task tool registration."""
    print("=" * 60)
    print("Task Tool Registration Verification")
    print("=" * 60)

    # Check if task.py exists
    print("\n1. Checking task.py file...")
    task_file = project_root / "vibe" / "core" / "tools" / "builtins" / "task.py"
    if task_file.exists():
        print(f"   [OK] task.py exists at: {task_file}")
    else:
        print(f"   [ERROR] task.py NOT found at: {task_file}")
        return 1

    # Try to import the Task class directly
    print("\n2. Importing Task class...")
    try:
        from vibe.core.tools.builtins.task import Task

        print("   [OK] Task class imported successfully")
        print(f"   Class name: {Task.__name__}")
        print(f"   Description: {Task.description[:80]}...")
    except ImportError as e:
        print(f"   [ERROR] Failed to import Task: {e}")
        return 1

    # Check the tool name
    print("\n3. Checking tool name...")
    tool_name = Task.get_name()
    print(f"   Tool name: '{tool_name}'")
    if tool_name == "task":
        print("   [OK] Tool name is 'task'")
    else:
        print(f"   [WARNING] Tool name is '{tool_name}', expected 'task'")

    # Check tool discovery
    print("\n4. Checking tool discovery...")
    from vibe.core.tools.manager import ToolManager

    builtins_dir = project_root / "vibe" / "core" / "tools" / "builtins"
    print(f"   Scanning: {builtins_dir}")

    discovered = {}
    for cls in ToolManager._iter_tool_classes([builtins_dir]):
        name = cls.get_name()
        discovered[name] = cls

    print(f"   Discovered {len(discovered)} tools")

    if "task" in discovered:
        print("   [OK] 'task' tool discovered!")
    else:
        print("   [ERROR] 'task' tool NOT discovered!")
        print("   Discovered tools:", ", ".join(sorted(discovered.keys())[:20]))
        return 1

    # Check for required attributes
    print("\n5. Checking Task class attributes...")
    has_parent_config = hasattr(Task, "_parent_config")
    has_parent_backend = hasattr(Task, "_parent_backend")
    print(f"   Has _parent_config attr: {has_parent_config}")
    print(f"   Has _parent_backend attr: {has_parent_backend}")

    # List discovered tools
    print("\n6. All discovered tools:")
    for name in sorted(discovered.keys()):
        marker = " <-- SUB-AGENT TOOL" if name == "task" else ""
        print(f"   - {name}{marker}")

    print("\n" + "=" * 60)
    print("RESULT: Task tool is properly registered!")
    print("Sub-agent spawning should work.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
