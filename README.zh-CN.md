# windows-drv-harness

面向 AI 的 Windows 内核驱动测试 harness，组合 VMware Workstation、
VirtualKD-Redux 和 WinDbg。v2 不再让小模型自己编排 VMware 命令、调试器进程、
管道、凭据和快照清理，而是只暴露一个高层 MCP server。

## 架构

```text
AI agent
  -> windows-drv-harness MCP（7 个任务级工具）
       -> target profile + target 独立状态
       -> vmrun.exe
       -> WinDbg + mcpext.dll（独立 MCP 管道）
       -> windbg-mcp.exe 2.0（同一管道）
```

运行配置不再放在 skill 安装目录：

```text
%LOCALAPPDATA%\windows-drv-harness\
  config.json
  state\
  logs\
```

一个配置可以保存任意数量的 VM target。每个 target 都有自己的 VMX、快照、
guest 账号、稳定 VirtualKD KD 管道和唯一 windbg-mcp 管道。启动阶段会短暂串行化
以确认 KD 管道归属，挂接完成后的 WinDbg/MCP 会话可以并行运行。

## 前置条件

- Windows host 和 Python 3.10+
- VMware Workstation 与 `vmrun.exe`
- host/guest 安装 VirtualKD-Redux
- 经典 x64 `windbg.exe`
- 编译驱动所需的 WDK/Visual Studio
- guest 中运行 VMware Tools

baseline 快照必须在 guest 已经开机、VMware Tools 正常、经典 WinDbg 已通过
VirtualKD/KDNET 成功挂上内核目标之后保存。没有验证过双机调试的冷快照不是有效
baseline。

## 快速开始

```powershell
git clone --recursive https://github.com/Letenz/windows-drv-harness.git
cd windows-drv-harness

$skill = ".\skills\windows-drv-harness"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\install-mcp.ps1"

py -3.11 "$skill\scripts\configure_target.py" `
  --target win10-lab `
  --vmx "D:\VMs\win10-lab\win10-lab.vmx" `
  --snapshot baseline-debug-ready `
  --kd-pipe kd_win10_lab `
  --guest-user testadmin `
  --guest-deploy-dir "C:\Users\testadmin\Desktop" `
  --make-default

powershell -ExecutionPolicy Bypass -File "$skill\scripts\setup-host.ps1"
py -3.11 "$skill\scripts\harness_cli.py" doctor --target win10-lab
```

`configure_target.py` 会隐藏输入 guest 密码，不把密码放到命令行。本机配置可以保存
明文密码或 `${env:VAR_NAME}`，但 harness 输出始终对敏感字段打码。

`setup-host.ps1` 在需要时会自行提权，关闭 VirtualKD 自动拉起 debugger、回填受限
路径探测结果，并保证全局只有一个 `vmmon64.exe`。这是一次性 host setup，不要在
每个并行 target 启动前重复执行。

确认 server 正常后，可注册唯一的高层 MCP：

```powershell
powershell -ExecutionPolicy Bypass -File "$skill\scripts\detect-mcp.ps1"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\register-mcp.ps1" -Apply
```

自写 agent 可把下面命令配置成 stdio MCP server：

```text
py -3.11 <SKILL_DIR>\scripts\harness_mcp.py
```

无需修改客户端即可做协议冒烟：

```powershell
py -3.11 "$skill\scripts\smoke-mcp-server.py" --server harness
```

## MCP 工具

| 工具 | 作用 |
|---|---|
| `lab_list_targets` | 列出 profile，不暴露凭据 |
| `lab_doctor` | 只读检查 target 是否就绪 |
| `lab_start` | 启动 target 独立的交互调试会话 |
| `driver_build` | 自动选择匹配 WDK 的 MSBuild 并返回 `.sys` |
| `driver_test` | 部署、测试、收集证据并恢复 baseline |
| `debug_run` | 证据不足时执行一条额外 WinDbg 命令 |
| `lab_reset` | 只重置选中的 target |

每个结果都有稳定的 `status` 和 `next_action`。故障版使用
`driver_test(expect="crash")`，修复并重新编译后使用 `expect="success"`。
`driver_test` 在任何退出路径都会尝试恢复 baseline。

## 多 Target

再次运行 `configure_target.py` 并提供新的 `--target`、`--vmx`、`--kd-pipe`
和 guest 账号即可增加 VM。每个 target 必须使用不同的 MCP 管道；不指定时会按
`windbgmcp-<target>` 生成。

VirtualKD 的 `kd_pipe` 是显式绑定的稳定管道，不能假定恢复快照后它会改名。
独立的 `mcp_pipe` 把一组 WinDbg 2.0 bridge 路由到一个 target，因此既能并行，
也不会让小模型面对多个 MCP server 注册项。

## HelloWorld 示例

`example/HelloWorld` 在 `DriverEntry` 中故意执行空指针写。可直接给 AI 下面的任务：

```text
使用 windows-drv-harness 工具运行 example\HelloWorld。先编译并执行一次
expect=crash 的测试，根据返回的 WinDbg 证据做最小源码修复；重新编译后执行
expect=success。只有服务能干净加载/卸载且 cleanup 显示 VM 已回滚才算完成。
```

首轮应得到 `0x7E`、访问异常和 `HelloWorld.sys`；修复后应看到
create/start/stop/delete 成功、WinDbg 确认模块加载与卸载、VM 恢复到配置好的
baseline。

## 内置 WinDbg Bridge

skill 内置来自 [Letenz/windbg-mcp](https://github.com/Letenz/windbg-mcp) 的
`windbg-mcp.exe` 与 `mcpext.dll` 2.0。新版支持每个 WinDbg 使用独立 endpoint、
明确区分 detach/shutdown，并通过 bridge instance 绑定防止重连到错误调试器。
准确源码提交和二进制哈希见
`skills/windows-drv-harness/windbg-mcp/build-manifest.json`。

`vmware-mcp` submodule 仍保留给高级/底层排查；小模型应使用高层 harness server。

## 开发校验

```powershell
py -3.11 -m unittest discover -s tests -v
py -3.11 skills\windows-drv-harness\scripts\smoke-mcp-server.py --server harness
py -3.11 skills\windows-drv-harness\scripts\smoke-mcp-server.py --server windbg --pipe windbgmcp-smoke
```

大日志和所有机器状态都保存在 `%LOCALAPPDATA%`，不要提交到仓库。

## License

MIT。第三方 submodule 保留各自许可证。
