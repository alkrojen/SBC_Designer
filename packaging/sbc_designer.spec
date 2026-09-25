# PyInstaller spec for the stand-alone SBC Designer application.
# Build from the repository root:  pyinstaller --noconfirm packaging/sbc_designer.spec
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "demo", "ac_controller_pcba.step"), "demo")]
binaries = []
hiddenimports = ["vtkmodules.all", "vtkmodules.qt.QVTKRenderWindowInteractor",
                 "vtkmodules.util.numpy_support"]
for pkg in ("OCP", "cadquery", "vtkmodules", "casadi"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "packaging", "launch.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "trame", "trame_vtk"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SBC_Designer",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SBC_Designer")
