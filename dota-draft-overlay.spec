# PyInstaller build recipe for the Windows program.
#   pip install -r requirements.txt pyinstaller
#   python -m PyInstaller dota-draft-overlay.spec --noconfirm
# Result: dist/DotaDraftOverlay/ (a folder, zipped for releases). A folder build
# starts faster and triggers fewer antivirus false positives than one big .exe.

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    # default slot boxes, found at runtime through paths.resource_dir()
    datas=[("slots.json", "."), ("LICENSE", "."), ("README.md", ".")],
    # mss picks its platform backend at runtime; make sure the Windows one is bundled
    hiddenimports=["mss.windows"],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DotaDraftOverlay",
    console=False,          # no terminal window; crashes go to error.log
    upx=False,              # UPX-packed files are flagged more often by antivirus
)
coll = COLLECT(exe, a.binaries, a.datas, name="DotaDraftOverlay", upx=False)
