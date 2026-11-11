"""The OpenCore boot disk of a machine: an EFI folder made from the machine
record and the OpenCore release in the install folder, and the FAT image
of it that QEMU attaches as SATA port 0.

No Tk in here. ``build_esp`` writes a folder, ``write_esp`` also the image.
The config is the release's Sample.plist with the settings Mac OS X 10.5
(32-bit kernel) needs under q35 and OVMF.
"""

from __future__ import annotations

import plistlib
import shutil
from pathlib import Path

from . import fatimg
from . import paths
from . import x86_model as model
from .x86_model import Machine

APPLE_NVRAM_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
FIXED_BOOT_ARGS = "keepsyms=1 debug=0x100"
SERIAL_NUMBER = "W00000000001"
BOARD_SERIAL = "M0000000000000001"
PICKER_TIMEOUT = 5

# OpenCore's own disk is kept out of the picker
CONTENT_VISIBILITY = "Disabled"

# The second I/O port of the RTC is not decoded by q35
RTC_PATCH = dict(Base="\\_SB.PCI0.SF8.RTC", BaseSkip=0, Comment="RTC: 2 ports (one CMOS bank)",
                 Count=1, Enabled=True, Find=bytes.fromhex("4701700070000108"), Limit=0,
                 Mask=b"", OemTableId=bytes(8), Replace=bytes.fromhex("4701700070000102"),
                 ReplaceMask=b"", Skip=0, TableLength=0, TableSignature=b"DSDT")


class EspError(OSError):
    pass


def boot_args(m: Machine) -> str:
    tokens = (FIXED_BOOT_ARGS + " " + (m.boot_args or "")).split()
    if "-v" in tokens:
        raise EspError("Verbose boot (-v) cannot be used: the Mac OS X 10.5 boot loader "
                       "crashes with it.")
    return " ".join(tokens)


def rom_bytes(m: Machine) -> bytes:
    mac = m.network.mac if model.MAC_RE.match(m.network.mac) else model.DEFAULT_MAC
    return bytes.fromhex(mac.replace(":", ""))


def kext_dirs(kexts_dir: Path | str | None) -> list[Path]:
    """The kext folders to inject, by name."""
    if not kexts_dir or not Path(kexts_dir).is_dir():
        return []
    return sorted((p for p in Path(kexts_dir).iterdir()
                   if p.is_dir() and p.suffix.lower() == ".kext"), key=lambda p: p.name.lower())


def kext_executable(kext: Path) -> str:
    """The kext's binary below its bundle, or "" when it has none."""
    macos = kext / "Contents" / "MacOS"
    if not macos.is_dir():
        return ""
    files = sorted(p.name for p in macos.iterdir() if p.is_file())
    if not files:
        return ""
    try:
        wanted = plistlib.loads((kext / "Contents" / "Info.plist").read_bytes()).get(
            "CFBundleExecutable")
    except (OSError, ValueError, plistlib.InvalidFileException):
        wanted = None
    return f"Contents/MacOS/{wanted if wanted in files else files[0]}"


def _section(parent: dict, key: str) -> dict:
    return parent.setdefault(key, {})


def make_config(m: Machine, sample: dict, kexts: list[Path]) -> dict:
    """The OpenCore config for *m*, from a loaded Sample.plist."""
    p = {k: v for k, v in sample.items() if not k.startswith("#")}
    arch = m.kernel_arch

    acpi = _section(p, "ACPI")
    acpi.update(Add=[], Delete=[], Patch=[dict(RTC_PATCH)])

    kernel = _section(p, "Kernel")
    kernel["Add"] = [dict(Arch="Any", BundlePath=k.name, Comment=k.stem, Enabled=True,
                          ExecutablePath=kext_executable(k), MaxKernel="", MinKernel="",
                          PlistPath="Contents/Info.plist") for k in kexts]
    kernel.update(Block=[], Patch=[], Force=[])
    scheme = _section(kernel, "Scheme")
    scheme.update(KernelArch=arch, KernelCache="Mkext")
    _section(kernel, "Quirks").update(ProvideCurrentCpuInfo=True, DisableLinkeditJettison=True)
    _section(kernel, "Emulate").update(DummyPowerManagement=True)

    booter = _section(p, "Booter")
    booter.update(MmioWhitelist=[], Patch=[])
    _section(booter, "Quirks").update(
        AvoidRuntimeDefrag=True, EnableSafeModeSlide=True, EnableWriteUnprotector=True,
        ProvideCustomSlide=True, SetupVirtualMap=False, RebuildAppleMemoryMap=True,
        DevirtualiseMmio=False, ProtectUefiServices=False, AllowRelocationBlock=True,
        ClearTaskSwitchBit=True)

    props = _section(p, "DeviceProperties")
    props.update(Add={}, Delete={})

    picker = bool(m.show_picker)
    misc = _section(p, "Misc")
    _section(misc, "Boot").update(Timeout=PICKER_TIMEOUT if picker else 0, HideAuxiliary=not picker,
                                  PickerMode="Builtin", PollAppleHotKeys=True, ShowPicker=picker)
    _section(misc, "Debug").update(AppleDebug=True, ApplePanic=True, DisableWatchDog=True,
                                   Target=0x09, DisplayLevel=0x80000042)
    _section(misc, "Serial")["Init"] = True
    _section(misc, "Security").update(SecureBootModel="Disabled", Vault="Optional", ScanPolicy=0,
                                      DmgLoading="Any", AllowSetDefault=True,
                                      ExposeSensitiveData=6)
    misc["Entries"] = []
    misc["Tools"] = [dict(Arguments="", Auxiliary=True, Comment="UEFI shell", Enabled=True,
                          Flavour="OpenShell:UEFIShell:Shell", FullNvramAccess=False,
                          Name="UEFI Shell", Path="OpenShell.efi", RealPath=False,
                          TextMode=False)]

    nvram = _section(p, "NVRAM")
    nvram_add = _section(nvram, "Add")
    nvram_add[APPLE_NVRAM_GUID] = {"boot-args": boot_args(m),
                                   "csr-active-config": b"\x00\x00\x00\x00",
                                   "prev-lang:kbd": b"en:0", "run-efi-updater": "No"}
    _section(nvram, "Delete")[APPLE_NVRAM_GUID] = ["boot-args", "csr-active-config",
                                                  "prev-lang:kbd"]
    nvram["WriteFlash"] = True

    info = _section(p, "PlatformInfo")
    info["Automatic"] = True
    _section(info, "Generic").update(SystemProductName=m.mac_model,
                                     SystemSerialNumber=SERIAL_NUMBER, MLB=BOARD_SERIAL,
                                     SystemUUID=m.uuid, ROM=rom_bytes(m), SpoofVendor=True)

    uefi = _section(p, "UEFI")
    uefi["Drivers"] = [dict(Arguments="", Comment="", Enabled=True, HideVerbose=False,
                            LoadEarly=False, Path=d) for d in paths.OPENCORE_DRIVERS]
    _section(uefi, "Quirks")["RequestBootVarRouting"] = True
    _section(uefi, "Output").update(ProvideConsoleGop=True, Resolution=m.resolution,
                                    TextRenderer="BuiltinText", UgaPassThrough=True,
                                    InitialMode="Text")
    return p


def build_esp(m: Machine, install_dir: Path | str, out: Path | str) -> Path:
    """Writes the EFI folder tree of *m* into *out* (made empty first);
    returns the config.plist path."""
    install = Path(install_dir)
    oc = install / paths.OPENCORE_DIR_NAME
    out = Path(out)
    missing = [f for f in paths.OPENCORE_FILES if not (oc / f).is_file()]
    if missing:
        raise EspError("The OpenCore folder is missing: " + ", ".join(missing))
    try:
        sample = plistlib.loads((oc / paths.OPENCORE_SAMPLE_PLIST).read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as e:
        raise EspError(f"The OpenCore Sample.plist cannot be read: {e}")
    kexts = kext_dirs(install / paths.KEXTS_DIR_NAME)
    config = make_config(m, sample, kexts)

    shutil.rmtree(out, ignore_errors=True)
    for d in ("EFI/BOOT", "EFI/OC/Drivers", "EFI/OC/Kexts", "EFI/OC/ACPI", "EFI/OC/Tools",
              "EFI/OC/Resources"):
        (out / d).mkdir(parents=True)
    efi = oc / "X64" / "EFI"
    shutil.copyfile(oc / paths.OPENCORE_BOOT_EFI, out / "EFI/BOOT/BOOTx64.efi")
    (out / "EFI/BOOT/.contentVisibility").write_text(CONTENT_VISIBILITY, encoding="ascii")
    shutil.copyfile(oc / paths.OPENCORE_MAIN_EFI, out / "EFI/OC/OpenCore.efi")
    for d in paths.OPENCORE_DRIVERS:
        shutil.copyfile(efi / "OC/Drivers" / d, out / "EFI/OC/Drivers" / d)
    shutil.copyfile(oc / paths.OPENCORE_TOOL, out / "EFI/OC/Tools/OpenShell.efi")
    for k in kexts:
        shutil.copytree(k, out / "EFI/OC/Kexts" / k.name)
    plist = out / "EFI/OC/config.plist"
    plist.write_bytes(plistlib.dumps(config, sort_keys=False))
    return plist


def write_esp(m: Machine, install_dir: Path | str, machine_dir: Path | str) -> Path:
    """Regenerates ``esp/`` and ``esp.img`` in the machine folder."""
    machine_dir = Path(machine_dir)
    folder = machine_dir / model.ESP_DIR
    build_esp(m, install_dir, folder)
    try:
        return fatimg.write_image(folder, machine_dir / model.ESP_IMAGE)
    except fatimg.FatError as e:
        raise EspError(f"The OpenCore disk cannot be made: {e}") from e
