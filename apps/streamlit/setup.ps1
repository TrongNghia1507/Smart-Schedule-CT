param([string]$Python)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$venv = Join-Path $repo '.venv'
if ($Python) {
    & $Python -m venv $venv
} else {
    py -3 -m venv $venv
}
if ($LASTEXITCODE -ne 0) { throw 'Can cai Python 3.12+ truoc.' }
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
& (Join-Path $venv 'Scripts\python.exe') -m pip install -e $repo -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Cai thu vien that bai.' }
