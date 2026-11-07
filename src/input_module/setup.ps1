$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Can cai Python 3.12+ truoc.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Cai thu vien that bai.' }
