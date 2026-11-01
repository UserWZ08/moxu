$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# Restrict DLL discovery to the runtime and Windows, excluding unrelated tools.
$pythonExecutable = (Get-Command python).Source
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
& $pythonExecutable -m PyInstaller --clean --noconfirm --windowed --name MoXu --icon assets\moxu.ico --add-data 'assets;assets' --collect-data pypinyin --collect-submodules pypinyin --distpath 程序-0.6 app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
Copy-Item -LiteralPath 'licenses' -Destination '程序-0.6\MoXu' -Recurse -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination '程序-0.6\MoXu' -Force
Write-Host 'Run Inno Setup ISCC.exe installer.iss to create the installer.'
