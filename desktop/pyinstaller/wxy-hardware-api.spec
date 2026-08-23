from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


repository = Path(SPECPATH).parent.parent
backend = repository / "backend"
datas = [(str(repository / "VERSION"), ".")]
binaries = []
hiddenimports = collect_submodules("app")
for package in ("fastapi", "uvicorn", "sqlalchemy", "multipart", "openpyxl", "qrcode", "PIL"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    [str(backend / "desktop_main.py")],
    pathex=[str(backend)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="wxy-hardware-api",
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="wxy-hardware-api",
)
