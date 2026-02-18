$ErrorActionPreference = "Stop"

Write-Host "Building .exe files for all wrapper scripts..."

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "Python launcher (py) not found. Install Python and try again."
}

py -m pip install --upgrade pyinstaller

$scripts = Get-ChildItem -Filter *.py | Where-Object { $_.Name -ne "automation_cli.py" }

if ($scripts.Count -eq 0) {
    Write-Error "No scripts found to build."
}

foreach ($script in $scripts) {
    Write-Host "Building $($script.Name)..."
    py -m PyInstaller --onefile $script.Name | Out-Host
}

Write-Host "Done. EXEs are in .\\dist\\"
