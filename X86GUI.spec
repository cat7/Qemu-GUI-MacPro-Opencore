# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Qemu-system-x86_64 OpenCore GUI.
#
# macOS, with the python.org framework Python (it has a working tkinter):
#
#   /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
#       -m PyInstaller --noconfirm X86GUI.spec
#
# The macOS bundle is universal2 unless QEMUGUI_TARGET_ARCH says otherwise
# (x86_64 or universal2).
#
# Put the result ("dist/Qemu-system-x86_64 OpenCore GUI.app" on macOS, the single
# "dist/Qemu-system-x86_64 OpenCore GUI.exe" on Windows) into the folder that holds
# qemu-system-x86_64, pc-bios/ and OpenCore/. Machines/ is made
# beside the application, never inside the bundle.

import os
import sys

NAME = 'Qemu-system-x86_64 OpenCore GUI'
TARGET_ARCH = (os.environ.get('QEMUGUI_TARGET_ARCH') or 'universal2') if sys.platform == 'darwin' else None

a = Analysis(
    ['x86_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('qemugui/usb_ids.gz', 'qemugui')],
    hiddenimports=['tkinter', 'tkinter.ttk', 'tkinter.filedialog',
                   'tkinter.messagebox', 'tkinter.simpledialog',
                   'pyftpdlib', 'pyftpdlib.authorizers', 'pyftpdlib.handlers',
                   'pyftpdlib.servers'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == 'win32':
    # One self-contained .exe; it unpacks itself to a temp folder at start.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        target_arch=TARGET_ARCH,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=NAME,
    )
    app = BUNDLE(
        coll,
        name=NAME + '.app',
        icon=None,
        bundle_identifier='org.cat7.qemu-gui-x86-opencore',
        info_plist={
            'CFBundleName': NAME,
            'CFBundleDisplayName': NAME,
            'CFBundleShortVersionString': '1.0',
            'CFBundleVersion': '1.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
            'LSApplicationCategoryType': 'public.app-category.utilities',
            'NSMicrophoneUsageDescription': 'The emulated machine uses the microphone as its audio input.',
        },
    )
