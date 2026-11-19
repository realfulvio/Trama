$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        python -m venv .venv
        if ($LASTEXITCODE) { throw 'Could not create virtual environment' }
    }
    & $python -m pip install -r requirements.txt pyinstaller==6.22.3
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE) { throw 'Tests failed' }
    & $python -m PyInstaller --noconfirm --clean --windowed --onedir --name Trama --icon assets\trama.ico --manifest assets\trama.manifest --add-data 'assets;assets' --add-data 'tests/data;tests/data' --collect-data pypdfium2 --collect-all pypdfium2_raw --hidden-import openpyxl --hidden-import matplotlib.backends.backend_pdf --hidden-import matplotlib.backends.backend_svg --hidden-import matplotlib.backends.backend_tkagg --hidden-import matplotlib.backends.backend_qtagg tramastat.py
    if ($LASTEXITCODE) { throw 'Build failed' }
    & $python package_windows.py
    if ($LASTEXITCODE) { throw 'Packaging failed' }
} finally {
    Pop-Location
}
