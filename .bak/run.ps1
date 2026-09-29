# Exit on first error
$ErrorActionPreference = "Stop"

# --- CONFIG ---
$VenvDir = ".venv"
$PythonBin = "python"          # CPython executable
$RustPythonBin = "G:\RustPython\target\release\rustpython.exe"  # RustPython executable
$Requirements = @("requests")  # Packages to install (fallback if no requirements.txt)
$UseRustPython = $true          # Set to $false to force using venv Python
$ScriptToRun = "app.py"   # Your Python script
# --------------

# 1. Create venv if it doesn't exist
if (-Not (Test-Path $VenvDir)) {
    Write-Host "[INFO] Creating virtual environment in $VenvDir..."
    & $PythonBin -m venv $VenvDir
} else {
    Write-Host "[INFO] Virtual environment already exists."
}

# 2. Activate venv and install packages
Write-Host "[INFO] Installing packages"
# Dot-source the activate script so it affects the current scope
. "$VenvDir\Scripts\Activate.ps1"
# Use the venv's python to upgrade pip
& "$VenvDir\Scripts\python.exe" -m pip install --upgrade pip
# If there's a requirements.txt file in the repo, install from it; otherwise install the fallback list
if (Test-Path "requirements.txt") {
    Write-Host "[INFO] Installing from requirements.txt"
    & "$VenvDir\Scripts\python.exe" -m pip install -r requirements.txt
} else {
    Write-Host "[INFO] Installing: $($Requirements -join ', ')"
    & "$VenvDir\Scripts\python.exe" -m pip install $Requirements
}
# Deactivate if the activation script provided the function
if (Get-Command -Name 'deactivate' -ErrorAction SilentlyContinue) {
    deactivate
}

# 3. Detect site-packages path using the venv's python (accurate for the created venv)
$SitePackagesPath = & "$VenvDir\Scripts\python.exe" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"

Write-Host "[INFO] site-packages path: $SitePackagesPath"

# 4. Decide runtime: prefer RustPython if available and compatible
Write-Host "[INFO] Deciding runtime for $ScriptToRun..."
# Detect compiled extension modules in site-packages (these won't work under RustPython)
$compiled = Get-ChildItem -Path $SitePackagesPath -Include *.pyd,*.so -Recurse -ErrorAction SilentlyContinue
if ($compiled.Count -gt 0) {
    Write-Host "[WARN] Compiled extension modules detected in site-packages; these may not work with RustPython. Falling back to venv Python."
    $UseRustPython = $false
}

if ($UseRustPython -and (Test-Path $RustPythonBin)) {
    Write-Host "[INFO] Running $ScriptToRun with RustPython..."
    $env:RUSTPYTHONPATH = $SitePackagesPath
    & $RustPythonBin $ScriptToRun
} else {
    Write-Host "[INFO] Running $ScriptToRun with venv Python..."
    & "$VenvDir\Scripts\python.exe" $ScriptToRun
}
