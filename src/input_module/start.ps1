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
    $process = Start-Process -FilePath $interpreter -ArgumentList $arguments -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server.log') -RedirectStandardError (Join-Path $logDir 'server-error.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $logDir 'server.pid')
    Write-Output "http://127.0.0.1:$Port (PID $($process.Id))"
} else {
    & $interpreter -m streamlit run $appFile --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
}
