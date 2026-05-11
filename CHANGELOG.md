# Changelog

All notable changes to this project will be documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Initial project skeleton
- README (English + Chinese)
- MIT license
- Core documentation stubs: quickstart, architecture, configure-vkd-redux, configure-guest-vm, troubleshooting
- Skill skeleton: `kernel-driver-testing/SKILL.md` + workflows + knowledge
- First verified example: `examples/01-kernel-patch-bsod/`
- Installer skeleton with steps: check-prereqs, init-submodules, apply-patches (fallback), build-windbg-ext, setup-python-envs, write-registry
- Doctor script for environment diagnostics
- Claude Code CLI / Claude Desktop / Cursor MCP client config templates
- Registry preset for VirtualKD-Redux auto-launch + MCP extension autoload
- `bin/windbgmcpExt.dll` — precompiled WinDbg extension (Release|x64, /MT, no debug info, ~534 KB) so users can get going without installing Visual Studio. SHA-256 recorded in `bin/windbgmcpExt.dll.sha256`. Built from the pinned `Letenz/windbg-ext-mcp` submodule.
- `third_party/vmware-mcp` and `third_party/windbg-ext-mcp` git submodules pinned to specific commits.

### Changed
- Replaced `installer/steps/build-windbg-ext.ps1` with `install-windbg-ext.ps1`, which by default copies and SHA-256-verifies `bin/windbgmcpExt.dll`, and only invokes MSBuild when `install.ps1 -Build` is passed. Visual Studio is now an **optional** dependency.
- Installer copies the chosen DLL to `%ProgramData%\driver-harness-mcp\bin\windbgmcpExt.dll`; `write-registry.ps1` and `doctor.ps1` look there first.
- `install.ps1` parameters: `-SkipBuild` removed; new `-Build` (compile from source) and `-SkipExt` (skip extension install entirely) introduced.
