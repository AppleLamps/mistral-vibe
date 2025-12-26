# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Enhanced Code Intelligence Tools** - Comprehensive AST-based code analysis powered by tree-sitter:
  - **Language Support Expansion**: Now supports 12 languages total:
    - Python, JavaScript, TypeScript (original)
    - Go, Rust, Java, C, C++, Ruby, PHP, C#, Kotlin (new)
  - **Scope Tracking**: Distinguish local vs global symbols, parameters, class members, and instance variables
  - **Import Resolution**: Smart path resolution for JavaScript/TypeScript ecosystems:
    - `tsconfig.json` paths support
    - `package.json` exports
    - Monorepo workspace detection
    - `node_modules` resolution
  - **Docstring Extraction**: Extract documentation from:
    - Python docstrings (`"""docstring"""`)
    - JSDoc/JavaDoc (`/** ... */`)
    - Rust doc comments (`///`)
    - Go/C# XML comments (`///`)
    - Ruby/PHP doc comments
  - **Tools**:
    - `symbol_search`: Find symbol definitions and references with optional scope and documentation info
    - `dependency_analyzer`: Analyze import relationships with enhanced path resolution
    - `refactor`: Safely rename symbols across multiple files with preview support
- `/new` command alias for `/clear` to start a new conversation
- Todo completion check - agent is reminded to complete todos before finishing work
- Improved error message when attempting to read a directory (suggests using `list_dir`)

### Changed

- Enhanced file vs folder detection with better guidance for the agent
- Code intelligence tools now support 9 additional programming languages

## [1.3.2] - 2025-12-24

### Added

- User definable reasoning field

### Fixed

- Fix rendering issue with spinner

## [1.3.1] - 2025-12-24

### Fixed

- Fix crash when continuing conversation
- Fix Nix flake to not export python

## [1.3.0] - 2025-12-23

### Added

- agentskills.io support
- Reasoning support
- Native terminal theme support
- Issue templates for bug reports and feature requests
- Auto update zed extension on release creation

### Changed

- Improve ToolUI system with better rendering and organization
- Use pinned actions in CI workflows
- Remove 100k -> 200k tokens config migration

### Fixed

- Fix `-p` mode to auto-approve tool calls
- Fix crash when switching mode
- Fix some cases where clipboard copy didn't work

## [1.2.2] - 2025-12-22

### Fixed

- Remove dead code
- Fix artefacts automatically attached to the release
- Refactor agent post streaming

## [1.2.1] - 2025-12-18

### Fixed

- Improve error message when running in home dir
- Do not show trusted folder workflow in home dir

## [1.2.0] - 2025-12-18

### Added

- Modular mode system
- Trusted folder mechanism for local .vibe directories
- Document public setup for vibe-acp in zed, jetbrains and neovim
- `--version` flag

### Changed

- Improve UI based on feedback
- Remove unnecessary logging and flushing for better performance
- Update textual
- Update nix flake
- Automate binary attachment to GitHub releases

### Fixed

- Prevent segmentation fault on exit by shutting down thread pools
- Fix extra spacing with assistant message

## [1.1.3] - 2025-12-12

### Added

- Add more copy_to_clipboard methods to support all cases
- Add bindings to scroll chat history

### Changed

- Relax config to accept extra inputs
- Remove useless stats from assistant events
- Improve scroll actions while streaming
- Do not check for updates more than once a day
- Use PyPI in update notifier

### Fixed

- Fix tool permission handling for "allow always" option in ACP
- Fix security issue: prevent command injection in GitHub Action prompt handling
- Fix issues with vLLM

## [1.1.2] - 2025-12-11

### Changed

- add `terminal-auth` auth method to ACP agent only if the client supports it
- fix `user-agent` header when using Mistral backend, using SDK hook

## [1.1.1] - 2025-12-10

### Changed

- added `include_commit_signature` in `config.toml` to disable signing commits

## [1.1.0] - 2025-12-10

### Fixed

- fixed crash in some rare instances when copy-pasting

### Changed

- improved context length from 100k to 200k

## [1.0.6] - 2025-12-10

### Fixed

- add missing steps in bump_version script
- move `pytest-xdist` to dev dependencies
- take into account config for bash timeout

### Changed

- improve textual performance
- improve README:
  - improve windows installation instructions
  - update default system prompt reference
  - document MCP tool permission configuration

## [1.0.5] - 2025-12-10

### Fixed

- Fix streaming with OpenAI adapter

## [1.0.4] - 2025-12-09

### Changed

- Rename agent in distribution/zed/extension.toml to mistral-vibe

### Fixed

- Fix icon and description in distribution/zed/extension.toml

### Removed

- Remove .envrc file

## [1.0.3] - 2025-12-09

### Added

- Add LICENCE symlink in distribution/zed for compatibility with zed extension release process

## [1.0.2] - 2025-12-09

### Fixed

- Fix setup flow for vibe-acp builds

## [1.0.1] - 2025-12-09

### Fixed

- Fix update notification

## [1.0.0] - 2025-12-09

### Added

- Initial release
