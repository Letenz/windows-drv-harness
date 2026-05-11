# driver-harness-mcp

> **AI 驱动的 Windows 内核调试自动化框架，端到端无人工。**
> 恢复快照 → 部署驱动 → 触发崩溃 → 自动分析。

[English version](./README.md)

---

## 这是什么？

`driver-harness-mcp` 把 Windows 内核调试常用的四样工具整合起来，并通过
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 暴露给
AI 助手（Claude Code CLI、Cursor、Cline 等），让 AI 不只是"建议命令"，而是**直接驱动整个测试流程**。

整合的组件：

- **VMware Workstation** —— 虚拟化 guest 操作系统
- **VirtualKD-Redux** —— 高速虚拟内核调试通道
- **WinDbg Preview** —— 调试器前端，通过 dbgeng 控制
- **MCP 服务** —— AI 与上述组件之间的桥梁

```
   ┌──────────────┐    MCP / JSON-RPC     ┌──────────────────┐
   │   AI 客户端  │ ────────────────────► │  MCP 服务集合    │
   │ (Claude Code │                       │  (vmware-mcp +   │
   │  CLI 等)     │                       │   windbg-ext-mcp │
   └──────────────┘                       │   + harness)     │
                                          └────────┬─────────┘
                                                   │
                              vmrun                │  named pipe
                                                   ▼
                          ┌────────────────────────────────────────┐
                          │  Host：VMware Workstation              │
                          │  + VirtualKD-Redux (vmmon64.exe)       │
                          │  + WinDbg Preview (自动拉起)           │
                          └─────────────────┬──────────────────────┘
                                            │  KDNET / VKD 虚拟 KD
                                            ▼
                          ┌────────────────────────────────────────┐
                          │  Guest VM：Windows 10/11 内核          │
                          └────────────────────────────────────────┘
```

## 项目状态

🚧 **v0.1 — 早期开发**。第一个端到端示例（内核字节补丁触发 BSOD）已验证通过且可复现。
API 与目录结构可能调整。Star / Watch 关注进展。

## 为什么做这个？

现有工具单独看都不错，但**缺一个把它们粘合起来的东西**：

| 组件 | 作用 | 缺什么 |
|---|---|---|
| [`vmware-mcp`](https://github.com/ZacharyZcR/vmware-mcp) | 通过 vmrun/REST 控制 VM | 不感知驱动 / 调试器 |
| [`windbg-ext-mcp`](https://github.com/NadavLor/windbg-ext-mcp) | WinDbg ↔ AI 桥接 | 需要手动配 WinDbg |
| `VirtualKD-Redux` | 高速虚拟 KD | 配置易错，坑多 |
| `KDNET` 配置 | 内核调试传输 | 防火墙、IL、ACL 等坑 |

本项目提供：

1. **一键安装脚本**（除 VMware 本体和 VirtualKD-Redux 外都自动）
2. **预设注册表配置**，让 VirtualKD-Redux 自动启动并加载 MCP 扩展
3. **Skills 文档库**（给 AI 看的 markdown），描述标准流程和坑位
4. **高阶 MCP 工具**：`diagnose_environment`、`start_vkd_monitor`、
   `cleanup_windbg_instances`、`query_debugger_status`、
   `ensure_debugger_ready`、`recover_to_clean_state`、`wait_mcp_ready`、
   `run_driver_load_verify`
5. **可直接复现的示例** —— 从 `examples/01-kernel-patch-bsod/` 开始

## 快速上手

> ⚠️ 需要 Windows 主机 + VMware Workstation Pro 16+ + 一台有管理员权限的 Windows guest VM。
> AI agent 请先读 [`AI_ENTRYPOINT.md`](./AI_ENTRYPOINT.md)。

```powershell
# 1. 带 submodule clone
git clone --recursive https://github.com/Letenz/driver-harness-mcp.git
cd driver-harness-mcp

# 2. 运行安装脚本（必须管理员）
powershell -ExecutionPolicy Bypass -File installer\install.ps1

# 3. 创建你的本地配置（VM 路径、guest 凭据等）
Copy-Item driver-harness.config.example.json driver-harness.config.json
# ...然后编辑 driver-harness.config.json 填写你的真实值。
# 你的 AI 助手可以一步一步带你填，参见 skills/kernel-driver-testing/。

# 4. 检查环境
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1

# 5. 配置 AI 客户端（以 Claude Code CLI 为例）
# 把 presets\mcp-client-config\claude-code-cli.json 合并到你的配置

# 6. 跑第一个示例
cd examples\01-kernel-patch-bsod
.\run.ps1
```

完整流程见 [`docs/quickstart.md`](./docs/quickstart.md)。

## 目录结构

```
driver-harness-mcp/
├── docs/                       # 用户文档
├── third_party/                # Git submodule（vmware-mcp、windbg-ext-mcp fork）
├── driver-harness-mcp/         # 我们自己的 MCP 服务（Python）
├── installer/                  # install.ps1 / doctor.ps1 / steps/
├── skills/                     # 给 AI 看的 markdown 知识库
├── examples/                   # 端到端可运行示例
└── presets/                    # 注册表模板、MCP 客户端配置样例
```

## 组件

| 组件 | 仓库 | 说明 |
|---|---|---|
| `vmware-mcp` | [`ZacharyZcR/vmware-mcp`](https://github.com/ZacharyZcR/vmware-mcp) | 直接用，submodule |
| `windbg-ext-mcp` | [`Letenz/windbg-ext-mcp`](https://github.com/Letenz/windbg-ext-mcp)（fork）| 含 harness 补丁：SDDL pipe ACL、BreakInHandler、debugger_status。后续会给上游提 PR。 |
| `driver-harness-mcp` | 本仓库 | 新增的高阶 MCP 工具 |
| `VirtualKD-Redux` | [`4d61726b/VirtualKD-Redux`](https://github.com/4d61726b/VirtualKD-Redux) | 用户自行安装（属于工具类） |

## 文档

- [Quickstart](./docs/quickstart.md) —— 30 分钟端到端搭建
- [架构说明](./docs/architecture.md) —— 各组件如何协作
- [配置 VirtualKD-Redux](./docs/configure-vkd-redux.md) —— 注册表设置、常见坑
- [配置 Guest VM](./docs/configure-guest-vm.md) —— KDNET、测试签名、快照基线
- [故障排查](./docs/troubleshooting.md) —— 症状 → 原因 → 解决

## AI Skills

[`skills/kernel-driver-testing/`](./skills/kernel-driver-testing/) 采用
[`anthropics/skills`](https://github.com/anthropics/skills) 格式，兼容
Claude / Cursor 以及其他支持 MCP 的客户端。

## 许可证

[MIT](./LICENSE) —— 自由使用，欢迎贡献。

本项目包含 Git submodule，遵循它们各自的许可证：
- `vmware-mcp` —— 见 [其 LICENSE](https://github.com/ZacharyZcR/vmware-mcp/blob/main/LICENSE)
- `windbg-ext-mcp` —— MIT (NadavLor)
- `VirtualKD-Redux` —— BSD 类（被引用，未打包进来）

## 贡献

欢迎 Issue / PR / Discussion。详见 [`CONTRIBUTING.md`](./CONTRIBUTING.md)（TODO）。

## 致谢

- [@NadavLor](https://github.com/NadavLor) —— `windbg-ext-mcp`
- [@ZacharyZcR](https://github.com/ZacharyZcR) —— `vmware-mcp`
- [@4d61726b](https://github.com/4d61726b) —— `VirtualKD-Redux` 的维护
- MCP / Anthropic 生态
