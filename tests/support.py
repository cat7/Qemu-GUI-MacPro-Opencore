"""Shared test helpers: a fake install folder, a dummy SMC key file and a
guard that keeps real dialogs off the screen.

Importing this module replaces the tkinter dialog functions with ones that
record the call and raise, so a test that reaches one fails instead of
blocking on a window. A test that expects a dialog patches its own.
"""

from __future__ import annotations

import plistlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qemugui import paths  # noqa: E402

DUMMY_KEY = "x" * 64

BASH = "/bin/bash"
needs_bash = unittest.skipUnless(sys.platform != "win32", "no bash")
needs_exec_bit = unittest.skipUnless(sys.platform != "win32", "no execute bit")

SAMPLE = {
    "#WARNING - 1": "text",
    "ACPI": {"Add": [{"Path": "x.aml"}], "Delete": [], "Patch": []},
    "Booter": {"MmioWhitelist": [], "Patch": [], "Quirks": {"AvoidRuntimeDefrag": False}},
    "DeviceProperties": {"Add": {"PciRoot(0x0)": {}}, "Delete": {}},
    "Kernel": {"Add": [], "Block": [], "Emulate": {}, "Force": [], "Patch": [],
               "Quirks": {}, "Scheme": {"KernelArch": "Auto", "KernelCache": "Auto"}},
    "Misc": {"Boot": {}, "Debug": {}, "Entries": [], "Security": {}, "Serial": {},
             "Tools": []},
    "NVRAM": {"Add": {}, "Delete": {}, "WriteFlash": False},
    "PlatformInfo": {"Automatic": False, "Generic": {}},
    "UEFI": {"Drivers": [], "Output": {}, "Quirks": {}},
}


def make_install(root: Path | str, qemu_img: bool = False) -> Path:
    """A folder with the files the program needs, all dummy bytes."""
    root = Path(root)
    (root / "pc-bios").mkdir(parents=True, exist_ok=True)
    (root / "pc-bios" / paths.OVMF_CODE_NAME).write_bytes(b"code")
    (root / "pc-bios" / paths.OVMF_VARS_TEMPLATE_NAME).write_bytes(b"vars" * 16)
    (root / paths.qemu_binary_name()).write_bytes(b"")
    if qemu_img:
        (root / paths.qemu_img_name()).write_bytes(b"")
    oc = root / paths.OPENCORE_DIR_NAME
    for rel in paths.OPENCORE_FILES:
        f = oc / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if rel == paths.OPENCORE_SAMPLE_PLIST:
            f.write_bytes(plistlib.dumps(SAMPLE))
        else:
            f.write_bytes(b"MZ" + Path(rel).name.encode())
    write_key(root / paths.SMC_KEY_FILE_NAME)
    return root


def write_key(path: Path | str, text: str = DUMMY_KEY + "\n") -> Path:
    Path(path).write_text(text, encoding="utf-8")
    return Path(path)


shown: list[tuple[str, tuple]] = []


def _blocked(name):
    def fn(*args, **kw):
        shown.append((name, args))
        raise AssertionError(f"a real dialog was opened: {name}{args[:2]}")
    return fn


def block_dialogs() -> None:
    try:
        from tkinter import messagebox, filedialog, simpledialog
    except ImportError:
        return
    for mod, names in ((messagebox, ("showinfo", "showwarning", "showerror", "askquestion",
                                     "askokcancel", "askyesno", "askyesnocancel",
                                     "askretrycancel")),
                       (filedialog, ("askopenfilename", "askopenfilenames", "asksaveasfilename",
                                     "askdirectory")),
                       (simpledialog, ("askstring", "askinteger", "askfloat"))):
        for n in names:
            setattr(mod, n, _blocked(n))


block_dialogs()
