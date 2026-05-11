# driver-harness-mcp

> **AI-driven Windows kernel debugging automation, end-to-end.**
> Snapshot revert → driver deploy → BSOD trigger → crash analysis. Fully automated, zero manual interaction.

[中文文档 / Chinese version](./README_zh.md)

---

## What is this?

`driver-harness-mcp` integrates four widely-used kernel debugging tools and exposes them to AI assistants
(Claude Code CLI, Cursor, Cline, etc.) through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

It glues together:

- **VMware Workstation** — virtualized guest OS
- **VirtualKD-Redux** — fast virtual kernel debugging transport
- **WinDbg Preview** — debugger frontend, controlled via dbgeng
- **MCP servers** — bridge between AI assistants and the above

…so an AI assistant can drive the entire kernel testing workflow itself, not just suggest commands.

```
   ┌──────────────┐    MCP / JSON-RPC     ┌──────────────────┐
   │  AI Client   │ ────────────────────► │  MCP Servers     │
   │ (Claude Code │                       │  (vmware-mcp +   │
   │  CLI / etc.) │                       │   windbg-ext-mcp │
   └──────────────┘                       │   + harness)     │
                                          └────────┬─────────┘
                                                   │
                              vmrun                │  named pipe
                                                   ▼
                          ┌────────────────────────────────────────┐
                          │  Host: VMware Workstation              │
                          │  + VirtualKD-Redux (vmmon64.exe)       │
                          │  + WinDbg Preview (auto-launched)      │
                          └─────────────────┬──────────────────────┘
                                            │  KDNET / VKD virtual KD
                                            ▼
                          ┌────────────────────────────────────────┐
                          │  Guest VM: Windows 10/11 kernel        │
                          └────────────────────────────────────────┘
```

## Status

🚧 **v0.1 — early development.** First end-to-end demo (kernel-patch BSOD) verified and reproducible.
APIs and layout may change. Star/watch the repo to follow progress.

## Why?

Existing components are great in isolation but **nothing glues them together**:

| Component | What it does | What's missing |
|---|---|---|
| [`vmware-mcp`](https://github.com/ZacharyZcR/vmware-mcp) | VM control via vmrun/REST | No driver / debugger awareness |
| [`windbg-ext-mcp`](https://github.com/NadavLor/windbg-ext-mcp) | WinDbg ↔ AI bridge | Requires manual WinDbg setup |
| `VirtualKD-Redux` | Fast virtual KD | Manual config, easy to misconfigure |
| `KDNET` setup | Kernel debug transport | Lots of pitfalls (firewall, IL, ACL…) |

`driver-harness-mcp` provides:

1. **One-command installer** for everything except VMware itself and VirtualKD-Redux
2. **Pre-configured registry presets** for VirtualKD-Redux auto-launch with the MCP extension
3. **Skills** (markdown knowledge base for AI) describing standard workflows and pitfalls
4. **High-level MCP tools**: `diagnose_environment`, `start_vkd_monitor`,
   `cleanup_windbg_instances`, `query_debugger_status`,
   `ensure_debugger_ready`, `recover_to_clean_state`, `wait_mcp_ready`,
   `run_driver_load_verify`
5. **Verified working examples** — start with `examples/01-kernel-patch-bsod/`

## Quickstart

> ⚠️ Requires Windows host, VMware Workstation Pro 16+ (Pro), and a Windows guest VM with admin access.
> AI agents should start with [`AI_ENTRYPOINT.md`](./AI_ENTRYPOINT.md).

```powershell
# 1. Clone with submodules
git clone --recursive https://github.com/Letenz/driver-harness-mcp.git
cd driver-harness-mcp

# 2. Run installer (must be Administrator)
powershell -ExecutionPolicy Bypass -File installer\install.ps1

# 3. Create your per-user config (VM path, guest credentials, etc.)
Copy-Item driver-harness.config.example.json driver-harness.config.json
# ...then edit driver-harness.config.json and fill in your real values.
# Your AI assistant can walk you through this; see skills/kernel-driver-testing/.

# 4. Verify environment
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1

# 5. Configure your AI client (example for Claude Code CLI)
# Copy presets\mcp-client-config\claude-code-cli.json into your config

# 6. Try the first example
cd examples\01-kernel-patch-bsod
.\run.ps1
```

See [`docs/quickstart.md`](./docs/quickstart.md) for the full 30-minute walkthrough.

## Project Layout

```
driver-harness-mcp/
├── docs/                       # User-facing docs
├── third_party/                # Git submodules (vmware-mcp, windbg-ext-mcp fork)
├── driver-harness-mcp/         # Our own MCP server (Python)
├── installer/                  # install.ps1 / doctor.ps1 / steps/
├── skills/                     # Markdown knowledge base for AI assistants
├── examples/                   # End-to-end working examples
└── presets/                    # Registry templates, MCP client config samples
```

## Components

| Component | Repo | Notes |
|---|---|---|
| `vmware-mcp` | [`ZacharyZcR/vmware-mcp`](https://github.com/ZacharyZcR/vmware-mcp) | Used as-is via submodule |
| `windbg-ext-mcp` | [`Letenz/windbg-ext-mcp`](https://github.com/Letenz/windbg-ext-mcp) (fork) | With harness patches: SDDL pipe ACL, BreakInHandler, and debugger_status. Patches will be submitted upstream. |
| `driver-harness-mcp` | This repo | New high-level MCP tools |
| `VirtualKD-Redux` | [`4d61726b/VirtualKD-Redux`](https://github.com/4d61726b/VirtualKD-Redux) | User installs separately (it's an end-user tool) |

## Documentation

- [Quickstart](./docs/quickstart.md) — 30-minute end-to-end setup
- [Architecture](./docs/architecture.md) — How the pieces fit together
- [Configure VirtualKD-Redux](./docs/configure-vkd-redux.md) — Registry settings, common pitfalls
- [Configure Guest VM](./docs/configure-guest-vm.md) — KDNET, test signing, snapshot baseline
- [Troubleshooting](./docs/troubleshooting.md) — Symptom → cause → fix

## AI Skills

[`skills/kernel-driver-testing/`](./skills/kernel-driver-testing/) follows the
[`anthropics/skills`](https://github.com/anthropics/skills) format. Compatible
with Claude, Cursor, and other MCP-aware clients.

## License

[MIT](./LICENSE) — Use freely, contributions welcome.

This project includes Git submodules under their own licenses:
- `vmware-mcp` — see [its LICENSE](https://github.com/ZacharyZcR/vmware-mcp/blob/main/LICENSE)
- `windbg-ext-mcp` — MIT (NadavLor)
- `VirtualKD-Redux` — BSD-style (referenced, not bundled)

## Contributing

Issues, PRs, and discussions welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) (TODO).

## Acknowledgements

- [@NadavLor](https://github.com/NadavLor) for `windbg-ext-mcp`
- [@ZacharyZcR](https://github.com/ZacharyZcR) for `vmware-mcp`
- [@4d61726b](https://github.com/4d61726b) for keeping `VirtualKD-Redux` alive
- The MCP / Anthropic ecosystem
