$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# Restrict DLL discovery to the runtime and Windows, excluding unrelated tools.
$pythonExecutable = (Get-Command python).Source
$releaseVersion = (& $pythonExecutable -c "from release_info import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot read release.ini' }
$distribution = "程序-$releaseVersion"
$versionResource = Join-Path $PSScriptRoot 'build\version_info.txt'
& $pythonExecutable package_release.py --version-info $versionResource
if ($LASTEXITCODE -ne 0) { throw 'Cannot create version resource' }
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
& $pythonExecutable -m PyInstaller --clean --noconfirm --windowed --name MoXu --icon assets\moxu.ico --version-file $versionResource --add-data 'assets;assets' --add-data 'release.ini;.' --collect-data pypinyin --collect-submodules pypinyin --distpath $distribution app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
Copy-Item -LiteralPath 'licenses' -Destination (Join-Path $distribution 'MoXu') -Recurse -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $distribution 'MoXu') -Force
Write-Host 'Run Inno Setup ISCC.exe installer.iss to create the installer.'
