# Contributing to driver-harness-mcp

Issues, PRs, and questions all welcome. A few ground rules to keep things clean.

## Things we do not accept (PRs will be closed)

- Anything containing **company-internal information** (employer names, internal IPs/hostnames, internal repo paths, customer data, etc.). The maintainer's day job is unrelated to this project.
- Examples / docs that target specific vendor products (anti-cheat solutions, AV/EDR products, DRM systems) by name. Generic kernel/driver scenarios only.
- Tools that automate **harmful** actions (rootkit installation, privilege escalation against systems the user does not own, etc.).

## Things we do accept

- New high-level MCP tools in `driver-harness-mcp/src/driver_harness_mcp/tools/`
- New examples in `examples/NN-name/` (each with a `README.md` + `run.ps1`)
- Skill / workflow / knowledge improvements in `skills/`
- Doc improvements
- Bug fixes (please include reproduction steps)
- Patches to upstream `windbg-ext-mcp` — submit them to `Letenz/windbg-ext-mcp` first

## Style

- **Code:** Python 3.11+, type-hinted. `ruff` for linting (config in `driver-harness-mcp/pyproject.toml`).
- **Commits:** Conventional-ish — `feat:`, `fix:`, `docs:`, `chore:`, etc.
- **Docs:** Markdown. Use mermaid for diagrams when possible. ASCII-only file paths in examples.
- **PowerShell:** Pin parameters with types, use `[CmdletBinding()]`, prefer `Set-StrictMode`.

## Adding a new MCP tool

1. Add a function in `driver-harness-mcp/src/driver_harness_mcp/tools/<your_tool>.py`.
2. Function should be type-hinted, have a docstring, and return a JSON-serializable dict.
3. Register it in `server.py` with `mcp.tool()(your_tool)`.
4. Add a unit test in `driver-harness-mcp/tests/`.
5. Update `skills/kernel-driver-testing/SKILL.md` if the tool changes user-facing workflow.

## Adding a new example

1. `examples/NN-short-name/`
2. Required files: `README.md` (what it does, why), `run.ps1` (executable demo), `expected-output.txt`.
3. **Test on a fresh `test_mcp_ready` snapshot** before opening a PR.

## Reporting issues

Include:
- OS version of host and guest
- VMware Workstation version
- VirtualKD-Redux version
- Output of `installer\doctor.ps1`
- Exact reproduction steps
- Full error message / log

**Redact any company info or sensitive paths before posting.**

## License

By contributing, you agree your contributions are licensed under MIT.
