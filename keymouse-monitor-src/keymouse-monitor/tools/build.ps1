# 一键打包：生成图标 -> PyInstaller 单文件 exe
# 用法: pwsh -File tools/build.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "[1/3] 生成图标 app.ico"
python -X utf8 tools/make_icon.py

Write-Host "[2/3] PyInstaller 打包（单文件、无控制台窗口）"
$ico = Join-Path $root 'app.ico'
python -X utf8 -m PyInstaller `
    --noconfirm --clean --onefile --noconsole `
    --name KeyMouseMonitor `
    --icon $ico `
    --add-data "$ico;." `
    --distpath (Join-Path $root 'dist') `
    --workpath (Join-Path $root 'build') `
    --specpath (Join-Path $root 'build') `
    --exclude-module PIL --exclude-module numpy `
    (Join-Path $root 'main.py')

Write-Host "[3/3] 完成"
$exe = Join-Path $root 'dist\KeyMouseMonitor.exe'
Get-Item $exe | Select-Object FullName, @{n='SizeMB';e={[math]::Round($_.Length/1MB,2)}}, LastWriteTime | Format-List
