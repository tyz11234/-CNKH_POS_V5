# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).parent
hiddenimports = collect_submodules('PySide6')
datas = [(str(project_root / 'resources'), 'resources'),
         (str(project_root / 'VERSION'), '.')]
a = Analysis([str(project_root / 'staff_launcher.py')],
             pathex=[str(project_root)], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='CNKH_POS_Staff',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False, argv_emulation=False,
          target_arch=None, codesign_identity=None, entitlements_file=None)
