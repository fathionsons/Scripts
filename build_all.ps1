param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "Building .exe files for all wrapper scripts..."

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "Python launcher (py) not found. Install Python and try again."
}

# Install PyInstaller only if missing (avoid broken upgrade attempts)
$pyinstallerMissing = $true
try {
    & py -c "import PyInstaller" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $pyinstallerMissing = $false
    }
} catch {
    $pyinstallerMissing = $true
}
if ($pyinstallerMissing) {
    Write-Host "Installing PyInstaller (user scope)..."
    py -m pip install --user --no-cache-dir pyinstaller
}

$scripts = Get-ChildItem -Filter *.py | Where-Object { $_.Name -ne "automation_cli.py" }

if ($scripts.Count -eq 0) {
    Write-Error "No scripts found to build."
}

if (-not (Test-Path ".\\dist")) {
    New-Item -ItemType Directory -Path ".\\dist" | Out-Null
}

foreach ($script in $scripts) {
    $exePath = Join-Path ".\\dist" ($script.BaseName + ".exe")
    if ((Test-Path $exePath) -and -not $Force) {
        Write-Host "Skipping $($script.Name) (already built)"
        continue
    }
    if ($Force -and (Test-Path $exePath)) {
        Remove-Item $exePath -Force
    }
    Write-Host "Building $($script.Name)..."
    py -m PyInstaller --onefile $script.Name | Out-Host
}

Write-Host "Done. EXEs are in .\\dist\\"
