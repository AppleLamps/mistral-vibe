Use the `bash` tool to run one-off shell commands.

**Key characteristics:**
- **Stateless**: Each command runs independently in a fresh environment

**IMPORTANT: Use dedicated tools if available instead of these bash commands:**

**Use dedicated tools instead of bash for these operations:**

- **Reading files** → Use `read_file(path="filename")` or `read_file(path="filename", limit=20)`
- **Writing files** → Use `write_file(path="file", content="content")`
- **Searching** → Use `grep(pattern="pattern", path=".")`
- **Editing files** → Use `search_replace` tool

**APPROPRIATE bash uses (Windows):**
- System information: `echo %CD%`, `whoami`, `date /t`, `systeminfo`
- Directory listings: `dir`, `dir /s` (recursive), `tree`
- Git operations: `git status`, `git log --oneline -10`, `git diff`
- Package management: `pip list`, `npm list`
- Environment checks: `set VAR`, `where python`, `echo %PATH%`
- Process info: `tasklist`, `tasklist /fi "imagename eq python.exe"`

**NEVER use these Unix commands (they don't work on Windows):**
- `ls`, `cat`, `grep`, `find`, `head`, `tail`, `ps`, `top`, `which`, `uname`

**Examples:**

```python
# Reading files - use read_file tool
read_file(path="large_file.txt", limit=1000)

# Searching - use grep tool
grep(pattern="TODO", path="src/")

# Directory listing - use bash with Windows commands
bash("dir")
bash("tree /f")

# Git operations - use bash
bash("git status")
bash("git log --oneline -10")
```

**Remember:** Bash is for system checks and git operations. For file operations, searching, and editing, always use the dedicated tools.
