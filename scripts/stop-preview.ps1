$ErrorActionPreference = 'Stop'
$taskProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskPidFile = Join-Path $taskProjectRoot 'artifacts\server-pids.json'
if (Test-Path -LiteralPath $taskPidFile) {
    $taskPreviewPids = Get-Content -LiteralPath $taskPidFile | ConvertFrom-Json
    foreach ($taskName in @('backend', 'frontend')) {
        $taskProcessId = $taskPreviewPids.$taskName
        if (-not $taskProcessId) { continue }
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskProcessId"
        if ($taskProcess -and $taskProcess.CommandLine -and
            $taskProcess.CommandLine.Contains($taskProjectRoot) -and
            $taskProcess.CommandLine -match 'uvicorn|next') {
            & taskkill /PID $taskProcessId /T /F | Out-Null
        }
    }
}
$taskPgCtl = Join-Path $taskProjectRoot 'artifacts\tools\postgresql\pgsql\bin\pg_ctl.exe'
$taskPgData = Join-Path $taskProjectRoot 'artifacts\postgres-data'
if ((Test-Path -LiteralPath $taskPgCtl) -and (Test-Path -LiteralPath (Join-Path $taskPgData 'postmaster.pid'))) {
    & $taskPgCtl -D $taskPgData -m fast -w stop
}
Write-Host 'Preview stopped. Stored PostgreSQL data was preserved.'
