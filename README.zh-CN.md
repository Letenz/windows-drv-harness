# windows-drv-harness

面向 AI agent 的 Windows 内核驱动自动化测试 skill 包，基于 VMware
Workstation、VirtualKD-Redux、WinDbg、`windbg-mcp` 和 `vmware-mcp`。

这个仓库没有额外的高层 harness MCP。AI 读取 skill 后，直接使用：

- `windbg-mcp`：读 WinDbg 状态、执行调试命令、分析崩溃。
- `vmware-mcp` 或 `vmrun.exe`：恢复快照、启动虚拟机、向 guest 拷贝文件、运行 `sc.exe`。
- 受限 PowerShell：处理 `vmmon64.exe`、VirtualKD 注册表和本机路径探测。

## 目录结构

真正给 AI 读取的是一个 skill 目录：

```text
skills/windows-drv-harness/
  SKILL.md
  windbg-mcp/mcpext.dll
  windbg-mcp/windbg-mcp.exe
  vmware-mcp/
  windows-drv-harness.config.example.json
  windows-drv-harness.config.schema.json
```

给人看的示例驱动放在：

```text
example/HelloWorld/
  README.md
  HelloWorld.sln
  HelloWorld/HelloWorld.c
  HelloWorld/HelloWorld.inf
  HelloWorld/HelloWorld.vcxproj
```

## 组件来源

- `windbg-mcp`：源码仓库是
  [Letenz/windbg-mcp](https://github.com/Letenz/windbg-mcp)。本 harness
  仓库会在 `skills/windows-drv-harness/windbg-mcp/` 内置一份已知可用的
  `windbg-mcp.exe` 和 `mcpext.dll`，这样 AI 测试驱动时不需要临时 clone 或
  编译 `windbg-mcp`。替换这些二进制时，也要同步更新旁边的 `.sha256`
  文件。
- `vmware-mcp`：源码仓库是
  [ZacharyZcR/vmware-mcp](https://github.com/ZacharyZcR/vmware-mcp)。本仓库把它作为
  submodule 放在 `skills/windows-drv-harness/vmware-mcp/`。

## 它解决什么

目标是让 AI 能跑完整的驱动测试闭环：

```text
编译驱动 -> 恢复 VirtualKD-ready 快照 -> 部署 .sys ->
加载驱动 -> 收集 WinDbg/guest 证据 -> 卸载驱动 -> 回滚快照 -> 修改代码
```

关键不在“写更多脚本”，而在把易错时序固定下来：

- baseline 快照必须在 guest 已经开机、VMware Tools 正常、VirtualKD/KDNET
  已配置、经典 WinDbg 已经成功挂上内核目标并确认双机调试可用之后保存；不要使用从未
  挂上 WinDbg 双机调试的冷快照或普通系统快照。
- `vmmon64.exe` 必须在恢复/启动 VM 之前运行。
- VirtualKD 自动启动 debugger 应关闭，让 agent 在看到新的 `kd_*` 管道后自己启动 GUI `windbg.exe -b`。
- WinDbg 必须加载 `mcpext.dll` 并执行 `!mcpext.start`，否则 `windbg-mcp` 无法连接。
- agent 必须通过 `windbg-mcp` 判断调试状态，不要靠截图、窗口标题或猜测。

## 前置条件

- Windows host
- VMware Workstation Pro
- host 和 guest 都配置好 VirtualKD-Redux
- Windows guest VM 安装 VMware Tools
- 一个在 guest 已经开机、VMware Tools 正常、VirtualKD/KDNET 已配置、经典 WinDbg
  已经成功挂上内核目标并确认双机调试可用之后保存的 baseline 快照
- Python 3.10+，用于 `vmware-mcp`
- 建议让当前 agent/终端具备管理员权限，方便写 HKLM 注册表和控制 `vmmon64.exe`

## 快速开始

```powershell
git clone --recursive https://github.com/Letenz/windows-drv-harness.git
cd windows-drv-harness

$skill = ".\skills\windows-drv-harness"
Copy-Item "$skill\windows-drv-harness.config.example.json" "$skill\windows-drv-harness.config.json"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\detect-mcp.ps1"
```

`windows-drv-harness.config.json` 已被 gitignore。环境检查前先把 VMX 路径、快照名、guest 用户名、guest 密码、工具路径等写进去。这个本地配置可以按你的要求保存明文 guest 密码；agent 在聊天输出里必须打码，并且不要提交这个文件。也可以继续用环境变量，例如：

```json
"admin_password": "${env:KERNEL_DRIVER_TEST_GUEST_PASSWORD}"
```

如果当前 agent 的可调用工具里已经有 `windbg-mcp` 和 `vmware-mcp`，直接用，不需要跑探测/注册脚本。如果 MCP 工具不可见，再运行 `scripts\install-mcp.ps1` 准备本地工具。它不会把 server 写入客户端 MCP list。用户明确确认后，Codex 可以执行：

```powershell
powershell -ExecutionPolicy Bypass -File "$skill\scripts\install-mcp.ps1"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\register-mcp.ps1" -Apply
```

如果自动注册失败，就使用 `detect-mcp.ps1` 或 `register-mcp.ps1` 打印出的手工命令。

如果是自写 agent，除非你的 agent 暴露自己的 MCP list/config API，否则脚本不能证明“agent 已经加载成功”。但仍然可以做客户端无关的 MCP stdio 服务端冒烟测试：

```powershell
py -3 "$skill\scripts\smoke-mcp-server.py" --server windbg
py -3 "$skill\scripts\smoke-mcp-server.py" --server vmware
```

通过后，把脚本打印/README 中的 server command 配进你的自写 agent；然后让自写 agent 自己执行 list-tools，确认能看到工具，再进入 VM 操作。

`windbg-mcp.exe` 是 native 程序，可直接从下面路径运行：

```text
skills\windows-drv-harness\windbg-mcp\windbg-mcp.exe
```

如果当前客户端没有注册好的 MCP 工具，用内置的一次性辅助脚本，不要在仓库根目录临时生成 MCP client：

```powershell
py -3 .\skills\windows-drv-harness\scripts\invoke-windbg-mcp.py wm_session
py -3 .\skills\windows-drv-harness\scripts\invoke-windbg-mcp.py wm_run_cmd "lm m nt"
```

## 换电脑运行

skill 目录本身可以迁移，但测试环境不能自动迁移。新电脑上需要安装 VMware Workstation、Windows Kits Debuggers、VirtualKD-Redux 和 Python，并复制或重新创建一个 baseline 快照已在 guest 开机后、WinDbg 双机调试成功挂上后保存的 VM。然后在新机器上重新创建本地 `windows-drv-harness.config.json`，由用户指定那台机器自己的 VMX、快照名、工具路径、符号路径和 guest 凭据。agent 不应该从 `vmrun list`、目录扫描或正在运行的 VM 里替用户选择 VMX/快照。只要这些路径和 baseline 快照有效，同一份 skill 就应该可以继续跑通。

## 给 AI 的提示词

把这个仓库交给 AI agent 时，可以直接给它下面这段：

```text
Use skills/windows-drv-harness/SKILL.md as the operating manual. Resolve
tool paths relative to that skill directory. Do not look for an extra harness
MCP server. Use windbg-mcp for debugger state and commands, vmware-mcp or
vmrun for VMware operations, and bounded PowerShell for vmmon/VirtualKD
registry work. Run the skill's preflight gate before any vmrun operation:
disable VirtualKD auto debugger launch, ensure exactly one vmmon64.exe is
running, close stale KD/WinDbg, restore/start the VM, wait for the new
VirtualKD main KD pipe, then launch GUI WinDbg against that pipe and wait for
the windbgmcp pipe. Use the GUI WinDbg window,
debugger log, and windbg-mcp tools for progress visibility. Do not scan whole
drives; ask me for the VMX path and any missing paths after bounded probing
fails. Do not choose a VM from vmrun list without my explicit confirmation.
Fill the local gitignored config first, including guest credentials for
vmrun/vmware-mcp, and redact secrets in chat output. Ask before registering MCP
servers in my current client.
```

驱动测试任务可以这样说：

```text
Build my driver, restore the VirtualKD-ready snapshot, copy the .sys to the
guest, load it with sc.exe, collect wm_session/wm_run_cmd evidence, unload it,
revert the snapshot, and patch the smallest code area if the test fails.
```

## HelloWorld 示例

`example/HelloWorld` 是一个故意会触发蓝屏的最小 WDM 驱动，用来验证 AI 是否真的能跑完整闭环，而不是只会编译。

可以直接把下面这段任务交给 AI：

```text
请按 skills/windows-drv-harness/SKILL.md 运行 example\HelloWorld。
先复现预期 BSOD 并用 WinDbg MCP 给出 bugcheck/根因；然后只修最小代码，
重新编译并恢复 baseline 快照复测，直到 sc start/stop/delete 都成功且最终回滚 VM。
```

首轮预期结果：

- `sc start HelloWorld` 触发 guest BSOD。
- WinDbg 报告 `0x7E SYSTEM_THREAD_EXCEPTION_NOT_HANDLED`。
- 异常是 `STATUS_ACCESS_VIOLATION`。
- 故障位置在 `HelloWorld!DriverEntry`。

最终修复后的预期结果：

- `sc create` 和 `sc start` 成功。
- WinDbg `lm m HelloWorld` 能看到模块已加载。
- 加载过程不再发生 BSOD。
- `sc stop` 和 `sc delete` 成功。
- 卸载后 WinDbg `lm m HelloWorld` 不再显示该模块。
- VM 被恢复到配置好的 VirtualKD-ready baseline 快照。

最初本地测试项目误拼成 `HelloWord`，本仓库已经统一改名为 `HelloWorld`。

## 注意事项

- 不要让 agent 全盘搜索工具路径。最多查配置、环境变量、注册表和默认安装路径；找不到就问用户。
- 不要让 agent 自己从 `vmrun list` 里擅自选择 VMX，必须由用户确认。
- `vmmon64.exe` 读取 VirtualKD 注册表是在启动时发生的；改注册表前先停 vmmon，改完再启动。
- 推荐关闭 VirtualKD 自动启动 debugger，让 agent 自己控制 WinDbg 时序。
- 除非用户明确指定其他 kernel debugger pipe，否则 WinDbg 的 `-k` 连接管道就用 VirtualKD 暴露的主 `\\.\pipe\kd_*` 管道。
- guest 停在 KD break 状态时，不要跑 `vmrun` guest 操作；先让调试器执行 `g`。
- 不要提交 `windows-drv-harness.config.json`。

## License

MIT。第三方 submodule 保留各自许可证。
