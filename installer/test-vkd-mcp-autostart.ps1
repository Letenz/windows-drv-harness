[CmdletBinding()]
param(
    [string]$RegistryKey = 'HKLM:\Software\VirtualKD-Redux\Monitor',
    [string]$PipeName = '\\.\pipe\windbgmcp',
    [switch]$RequireVmmon,
    [switch]$RequirePipe
)

$ErrorActionPreference = 'Stop'
$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail = '',
        [string]$Hint = ''
    )
    $script:checks.Add([pscustomobject]@{
        Name = $Name
        Ok = $Ok
        Detail = $Detail
        Hint = $Hint
    }) | Out-Null
}

function Test-NamedPipe {
    param([string]$Name)
    if ($Name -notmatch '^\\\\\.\\pipe\\(.+)$') {
        return Test-Path -LiteralPath $Name
    }
    $shortName = $Matches[1]
    try {
        $client = [System.IO.Pipes.NamedPipeClientStream]::new(
            '.',
            $shortName,
            [System.IO.Pipes.PipeDirection]::InOut
        )
        $client.Connect(100)
        $client.Dispose()
        return $true
    } catch {
        return $false
    }
}

$props = $null
try {
    $props = Get-ItemProperty -LiteralPath $RegistryKey
    Add-Check 'VirtualKD registry key' $true $RegistryKey
} catch {
    Add-Check 'VirtualKD registry key' $false $RegistryKey 'Run installer\steps\write-registry.ps1 as Administrator.'
}

$template = ''
if ($props) {
    $template = [string]$props.CustomDebuggerTemplate
    Add-Check 'DebuggerType=2 Custom' ($props.DebuggerType -eq 2) "DebuggerType=$($props.DebuggerType)" 'Set DebuggerType to 2. DebuggerType=3 can ignore CustomDebuggerTemplate.'
    Add-Check 'AutoInvokeDebugger=1' ($props.AutoInvokeDebugger -eq 1) "AutoInvokeDebugger=$($props.AutoInvokeDebugger)"
    Add-Check 'CustomDebuggerTemplate present' (-not [string]::IsNullOrWhiteSpace($template)) $template
    Add-Check 'Template loads windbgmcpExt.dll' ($template -like '*windbgmcpExt.dll*') $template
    Add-Check 'Template runs !mcpstart' ($template -like '*!mcpstart*') $template
    Add-Check 'Template has -c startup command' ($template -match '(?i)(^|\s)-c\s+') $template
    Add-Check 'Template resumes guest with g' ($template -match '(?i)(^|[;\s])g"?\s*$|;\s*g"?') $template

    $dllPath = ''
    if ($template -match '(?i)\.load\s+([^;]+?windbgmcpExt\.dll)') {
        $dllPath = $Matches[1].Trim().Trim('"')
    }
    Add-Check 'Template DLL path parsed' (-not [string]::IsNullOrWhiteSpace($dllPath)) $dllPath
    if ($dllPath) {
        Add-Check 'Template DLL exists' (Test-Path -LiteralPath $dllPath) $dllPath
    }
}

$vmmon = Get-Process -Name vmmon64 -ErrorAction SilentlyContinue | Select-Object -First 1
Add-Check 'vmmon64.exe running' ([bool]$vmmon -or -not $RequireVmmon) ($(if ($vmmon) { "$($vmmon.Id) $($vmmon.Path)" } else { 'not running' })) 'Start or restart vmmon64.exe after registry changes.'

$pipeOk = Test-NamedPipe $PipeName
Add-Check 'windbgmcp pipe available' ($pipeOk -or -not $RequirePipe) $PipeName 'Pipe appears only after vmmon64 starts WinDbg and !mcpstart runs.'

$checks | Format-Table -AutoSize

$failed = @($checks | Where-Object { -not $_.Ok })
if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host "FAILED: $($failed.Count) check(s) need attention." -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host 'OK: VirtualKD autostart is configured for WinDbg MCP.' -ForegroundColor Green
