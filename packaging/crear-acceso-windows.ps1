# Crea accesos directos del Archivador en el Escritorio y el menú Inicio (Windows).
# Uso (clic derecho > Ejecutar con PowerShell), o:
#   powershell -ExecutionPolicy Bypass -File packaging\crear-acceso-windows.ps1

$ErrorActionPreference = "Stop"
$Root    = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Target  = Join-Path $Root "run.bat"
$Icon    = Join-Path $Root "assets\icon.ico"

function New-Shortcut($Path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($Path)
    $sc.TargetPath       = $Target
    $sc.WorkingDirectory = $Root
    $sc.IconLocation     = $Icon
    $sc.Description       = "Descarga y organiza los videos de tu canal de YouTube"
    $sc.WindowStyle       = 7   # minimizado
    $sc.Save()
}

$desktop = [Environment]::GetFolderPath("Desktop")
$startup = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"

New-Shortcut (Join-Path $desktop "Archivador de canal.lnk")
New-Shortcut (Join-Path $startup "Archivador de canal.lnk")

Write-Host "OK: accesos creados en el Escritorio y el menu Inicio." -ForegroundColor Green
