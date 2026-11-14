param([switch]$Background, [int]$Port = 8501)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$localPython = Join-Path $project '.venv\Scripts\python.exe'
$taskPython = Join-Path $project '..\..\work\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $interpreter = (Resolve-Path -LiteralPath $localPython).Path }
elseif (Test-Path -LiteralPath $taskPython) { $interpreter = (Resolve-Path -LiteralPath $taskPython).Path }
else { throw 'Chay setup.ps1 truoc de tao moi truong Python.' }
$appFile = Join-Path $project 'app.py'
$arguments = @('-m', 'streamlit', 'run', ('"' + $appFile + '"'), '--server.address', '127.0.0.1', '--server.port', "$Port", '--server.headless', 'true', '--browser.gatherUsageStats', 'false')
if ($Background) {
    $logDir = Join-Path $project 'data'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $supervisorFile = Join-Path $project 'serve_forever.py'
    $supervisorPid = Join-Path $logDir 'supervisor.pid'
    if (Test-Path -LiteralPath $supervisorPid) {
        $existingId = [int](Get-Content -LiteralPath $supervisorPid)
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $existingId"
        if ($existing -and $existing.CommandLine.Contains($supervisorFile)) {
            $activePort = Get-Content -LiteralPath (Join-Path $logDir 'server.port')
            Write-Output "Da chay: http://127.0.0.1:$activePort"
            return
        }
    }
    $process = Start-Process -FilePath $interpreter -ArgumentList @(('"' + $supervisorFile + '"'), '--port', "$Port") -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'supervisor.log') -RedirectStandardError (Join-Path $logDir 'supervisor-error.log') -PassThru
    Write-Output "http://127.0.0.1:$Port (supervisor PID $($process.Id))"
} else {
    & $interpreter -m streamlit run $appFile --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false --server.disconnectedSessionTTL 0
}
