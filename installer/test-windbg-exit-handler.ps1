[CmdletBinding()]
param(
    [string]$PipeName = "\\.\pipe\windbgmcp",
    [int]$TimeoutSeconds = 5,
    [switch]$ActuallyExit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Convert-ToPipeClientName {
    param([string]$Name)
    if ($Name.StartsWith("\\.\pipe\")) {
        return $Name.Substring("\\.\pipe\".Length)
    }
    return $Name
}

$clientName = Convert-ToPipeClientName $PipeName
$client = [System.IO.Pipes.NamedPipeClientStream]::new(
    ".",
    $clientName,
    [System.IO.Pipes.PipeDirection]::InOut,
    [System.IO.Pipes.PipeOptions]::None
)
$reader = $null
$writer = $null

try {
    $client.Connect([Math]::Max(1, $TimeoutSeconds * 1000))
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.IO.StreamWriter]::new($client, $utf8)
    $reader = [System.IO.StreamReader]::new($client, $utf8)
    $writer.AutoFlush = $true

    $payload = @{
        type = "command"
        command = "exit_windbg"
        id = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        args = @{
            dry_run = -not $ActuallyExit
            delay_ms = 250
            exit_code = 0
        }
    } | ConvertTo-Json -Compress

    $writer.WriteLine($payload)
    $line = $reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($line)) {
        throw "Empty response from $PipeName"
    }

    $response = $line | ConvertFrom-Json
    $response | ConvertTo-Json -Depth 8

    if ($response.status -ne "success") {
        throw "exit_windbg failed; install the current windbgmcpExt.dll if the handler is missing."
    }

    if ($ActuallyExit) {
        Write-Host "WinDbg exit was requested. The MCP pipe should disappear shortly." -ForegroundColor Yellow
    }
    else {
        Write-Host "OK: exit_windbg handler is available (dry run; WinDbg was not closed)." -ForegroundColor Green
    }
}
finally {
    if ($reader) { $reader.Dispose() }
    if ($writer) { $writer.Dispose() }
    $client.Dispose()
}
