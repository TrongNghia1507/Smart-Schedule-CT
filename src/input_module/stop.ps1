$pidFile = Join-Path $PSScriptRoot 'data\server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $serverId = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverId"
    $appFile = Join-Path $PSScriptRoot 'app.py'
    if ($process -and $process.CommandLine.Contains($appFile) -and $process.CommandLine.Contains('streamlit')) {
        Stop-Process -Id $serverId
        Remove-Item -LiteralPath $pidFile
        Write-Output 'Da dung ung dung.'
    } else { Write-Output 'Khong tim thay tien trinh ung dung phu hop; khong dung tien trinh khac.' }
}
