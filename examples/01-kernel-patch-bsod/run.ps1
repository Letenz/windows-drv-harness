<#
.SYNOPSIS
    Example 01 — Trigger a BSOD by patching nt!SwapContext+5.

.DESCRIPTION
    End-to-end smoke test for driver-harness-mcp. Drives everything from
    PowerShell via vmrun + named pipe JSON protocol, no AI/MCP client needed.

.PARAMETER Vmx
    Path to the guest VM's .vmx file. No default — you must pass it.

.PARAMETER Snapshot
    Snapshot to revert to. Default: test_mcp_ready.

.EXAMPLE
    .\run.ps1 -Vmx "D:\VMs\test_win10\test_win10.vmx" -Snapshot "test_mcp_ready"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Vmx,

    [string]$Snapshot = 'test_mcp_ready',

    [string]$Vmrun = $(if ($env:VMRUN_PATH) { $env:VMRUN_PATH } else { 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe' }),

    [string]$PipeName = 'windbgmcp',

    [int]$PipeTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

function Step([string]$msg) { Write-Host "[+] $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Bad([string]$msg)  { Write-Host "    FAIL: $msg" -ForegroundColor Red }

if (-not (Test-Path $Vmrun)) { throw "vmrun not found: $Vmrun" }
if (-not (Test-Path $Vmx))   { throw "vmx not found: $Vmx" }

# -------------------------------------------------------------------- Stage 1
Step "Reverting to snapshot '$Snapshot' ..."
$sw = [Diagnostics.Stopwatch]::StartNew()
& $Vmrun revertToSnapshot $Vmx $Snapshot
if ($LASTEXITCODE -ne 0) { throw "revertToSnapshot failed: rc=$LASTEXITCODE" }
$sw.Stop(); Ok ("revert took {0:N1}s" -f $sw.Elapsed.TotalSeconds)

# -------------------------------------------------------------------- Stage 2
Step "Starting VM (nogui) ..."
$sw.Restart()
& $Vmrun start $Vmx nogui
if ($LASTEXITCODE -ne 0) { throw "start failed: rc=$LASTEXITCODE" }
$sw.Stop(); Ok ("start took {0:N1}s" -f $sw.Elapsed.TotalSeconds)

# -------------------------------------------------------------------- Stage 3
Step "Waiting for pipe \\.\pipe\$PipeName ..."
$deadline = (Get-Date).AddSeconds($PipeTimeoutSeconds)
$sw.Restart()
do {
    Start-Sleep -Milliseconds 500
    $ready = Test-Path "\\.\pipe\$PipeName"
    if ($ready) { break }
} while ((Get-Date) -lt $deadline)
if (-not $ready) { throw "pipe \\.\pipe\$PipeName did not appear within ${PipeTimeoutSeconds}s" }
$sw.Stop(); Ok ("pipe ready after {0:N1}s" -f $sw.Elapsed.TotalSeconds)

# -------------------------------------------------------------------- Stage 4
Step "Connecting to MCP pipe and sending commands ..."
$pipe = New-Object System.IO.Pipes.NamedPipeClientStream('.', $PipeName, [System.IO.Pipes.PipeDirection]::InOut)
$pipe.Connect(5000)
$reader = New-Object System.IO.StreamReader($pipe, [Text.Encoding]::UTF8)
$writer = New-Object System.IO.StreamWriter($pipe, [Text.Encoding]::UTF8)
$writer.AutoFlush = $true

function Send-Cmd([string]$cmd, [int]$timeoutMs = 15000) {
    $id = [int][double]::Parse((Get-Date -UFormat %s))
    $req = @{
        type    = 'command'
        command = 'execute_command'
        id      = $id
        args    = @{ command = $cmd; timeout_ms = $timeoutMs }
    } | ConvertTo-Json -Compress
    Write-Host "    >>> $cmd" -ForegroundColor DarkGray
    $writer.WriteLine($req)
    $resp = $reader.ReadLine()
    return ($resp | ConvertFrom-Json)
}

# health check
$vt = Send-Cmd 'vertarget'
if ($vt.status -ne 'success') { throw "vertarget failed: $($vt.error)" }
Ok ("vertarget: " + ($vt.output.Split("`n")[0]))

# -------------------------------------------------------------------- Stage 5
Step "Breaking in (SetInterrupt) ..."
$br = Send-Cmd '.echo (break_in placeholder)'  # real call requires break_in tool on server-side
# If your windbg-ext-mcp has BreakInHandler wired as `break_in` protocol action,
# send it via type=command/command=break_in instead. For the smoke test we
# assume the target was left in broken state by VKD's -d flag.
Ok 'assuming target already broken (from -d)'

# -------------------------------------------------------------------- Stage 6
Step "Locating nt!SwapContext ..."
$resp = Send-Cmd 'x nt!SwapContext'
if ($resp.status -ne 'success') { throw "x failed: $($resp.error)" }
if ($resp.output -match 'fffff[0-9a-f`]+') { $addr = $matches[0] } else { throw "Cannot parse SwapContext address from: $($resp.output)" }
Ok "SwapContext at $addr"

Step "Backing up 8 bytes ..."
$backup = Send-Cmd "db nt!SwapContext L10"
Ok ($backup.output.Split("`n")[0].Trim())

Step "Patching nt!SwapContext+5 with 00 00 00 00 00 ..."
$patch = Send-Cmd 'eb nt!SwapContext+5 00 00 00 00 00'
if ($patch.status -ne 'success') { throw "eb failed: $($patch.error)" }
Ok 'patched'

# -------------------------------------------------------------------- Stage 7
Step "Resuming kernel with g ..."
$go = Send-Cmd 'g' 2000
# g returns once break happens (BSOD)
Ok ('g returned: ' + ($go.output -replace "\r?\n", ' | ').Substring(0, [Math]::Min(200, ($go.output -replace "\r?\n", ' | ').Length)))

Start-Sleep -Milliseconds 500

# -------------------------------------------------------------------- Stage 8
Step "Running !analyze -v ..."
$an = Send-Cmd '!analyze -v' 30000
if ($an.status -ne 'success') { Bad "!analyze failed: $($an.error)" }
else {
    $snippet = ($an.output -split "`n") | Where-Object { $_ -match '^(BugCheck|BUCKET_ID|MODULE_NAME|IMAGE_NAME|FAILURE_BUCKET|BUGCHECK_CODE)' } | Select-Object -First 8
    foreach ($line in $snippet) { Ok $line }
}

$pipe.Close()

# -------------------------------------------------------------------- Stage 9
Step "Reverting snapshot for cleanup ..."
& $Vmrun revertToSnapshot $Vmx $Snapshot
if ($LASTEXITCODE -eq 0) { Ok 'reverted' } else { Bad "revert rc=$LASTEXITCODE" }

Write-Host ""
Write-Host "=== Example complete ===" -ForegroundColor Cyan
