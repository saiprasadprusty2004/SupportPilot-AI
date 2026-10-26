$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { python -m venv .venv }
& ./.venv/Scripts/python.exe -m pip install -e './backend[test]'
Push-Location -LiteralPath 'frontend'
try { npm.cmd ci } finally { Pop-Location }
Write-Output 'Start the backend: .\.venv\Scripts\python.exe -m app.cli demo'
Write-Output 'In another terminal: cd frontend; npm.cmd run dev'
Write-Output 'Then open http://localhost:5173 and choose Open demo workspace.'
