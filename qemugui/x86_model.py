"""The Intel Mac machine record: dataclasses, JSON load/save, checks.

``machine.json`` schema 1 of the x86 family. The machine is QEMU's ``q35``
with OVMF and OpenCore, started as a Mac Pro, for Mac OS X 10.5 (32-bit
kernel).

Facts the record encodes:

* Drives. The boot disk (the generated OpenCore ``esp.img``) is on SATA
  port 0 and is not part of the record; the record's five drives are the
  ports 1 to 5 of the ICH9 AHCI controller (``ide.1`` to ``ide.5``).
* Firmware. OVMF code is read-only from ``pc-bios``; the variable store is
  the machine's own ``OVMF_VARS.fd``, which holds the NVRAM (startup disk,
  OpenCore variables) and is never overwritten once it exists.
* SMC key. The ``isa-applesmc`` device needs a 64-character key. It is read
  by the launcher from a file when the launcher runs and is kept in no
  record, setting or launcher.
* Acceleration. TCG everywhere; HVF on an Intel Mac, WHPX on Windows.
* Input. A USB keyboard and a tablet (or mouse) on the UHCI controller.
* Host USB devices. Passed through with QEMU's ``usb-host``: full- and
  low-speed devices on the UHCI, high-speed ones on an added EHCI. macOS
  needs QEMU to run as root (the launcher uses sudo, as for vmnet); on
  Windows QEMU runs unelevated and opens only a device that is on Windows'
  WinUSB driver (``winusb-switch.exe`` moves it there and back).
"""

from __future__ import annotations

import json
import platform as _platform
import re
import shutil
import uuid as _uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from . import paths
from .paths import (DISPLAYS, default_display, AUDIO_DEFAULT,
                    NETWORK_MODES, NETWORK_MODE_PLATFORM, NETWORK_MODES_WITH_IFNAME,
                    NETWORK_MODE_LABELS, network_mode_label, network_mode_by_label,
                    network_modes_for_host, network_labels_for_host, default_ifname,
                    ifname_label, FORMATS, DRIVE_FORMATS, detect_format,
                    is_host_drive)

DEFAULT_MAC = "52:54:00:12:34:56"

SCHEMA = 1
NAME_RE = re.compile(r"^[A-Za-z0-9._ -]+$")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
VNC_RE = re.compile(r"^([A-Za-z0-9.\-]*:)?\d+$")
RTC_BASE_RE = re.compile(r"^(utc|localtime|\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?)$")
RTC_BASE_CHOICES = ("", "localtime")

MAC_MODELS = ("MacPro1,1", "MacPro2,1", "MacPro3,1", "MacPro4,1", "MacPro5,1")
# the QEMU processor of each model; Penryn stands in for the Core 2 Xeons of 1,1 and 2,1
MAC_MODEL_CPU = {"MacPro1,1": "Penryn", "MacPro2,1": "Penryn", "MacPro3,1": "Penryn",
                 "MacPro4,1": "Nehalem", "MacPro5,1": "Westmere"}
# the name of a Xeon each model shipped with
MAC_MODEL_CPU_NAME = {"MacPro1,1": "Intel(R) Xeon(R) CPU 5150 @ 2.66GHz",
                      "MacPro2,1": "Intel(R) Xeon(R) CPU X5365 @ 3.00GHz",
                      "MacPro3,1": "Intel(R) Xeon(R) CPU E5462 @ 2.80GHz",
                      "MacPro4,1": "Intel(R) Xeon(R) CPU E5520 @ 2.27GHz",
                      "MacPro5,1": "Intel(R) Xeon(R) CPU X5670 @ 2.93GHz"}
# the first system each later model shipped with
MAC_MODEL_FIRST_OS = {"MacPro4,1": "10.5.6", "MacPro5,1": "10.6.4"}
MAC_MODEL_DEFAULT = "MacPro2,1"
OS_VERSIONS = ("10.5", "10.6", "10.7", "10.8", "10.9", "10.10")
OS_DEFAULT = "10.5"
OS_NAMES = {"10.5": "Leopard", "10.6": "Snow Leopard", "10.7": "Lion",
            "10.8": "Mountain Lion", "10.9": "Mavericks", "10.10": "Yosemite"}
# the OpenCore Kernel->Scheme->KernelArch of each system
OS_KERNEL_ARCH = {"10.5": "i386", "10.6": "i386", "10.7": "i386", "10.8": "x86_64",
                  "10.9": "x86_64", "10.10": "x86_64"}
# the OpenCore Kernel->Scheme->KernelCache of each system
OS_KERNEL_CACHE = {"10.5": "Mkext", "10.6": "Mkext", "10.7": "Mkext", "10.8": "Auto",
                   "10.9": "Auto", "10.10": "Auto"}


def os_label(version: str) -> str:
    name = OS_NAMES.get(version)
    return f"{version} {name}" if name else version


def os_by_label(label: str) -> str:
    return (label or "").split(" ", 1)[0]


OS_LABELS = tuple(os_label(v) for v in OS_VERSIONS)
# 10.8 to 10.10 have a 64-bit kernel only and run on no Mac Pro before 3,1;
# 10.5 runs on no Mac Pro after 4,1
OS_MAC_MODELS = {"10.5": ("MacPro1,1", "MacPro2,1", "MacPro3,1", "MacPro4,1"),
                 "10.8": ("MacPro3,1", "MacPro4,1", "MacPro5,1"),
                 "10.9": ("MacPro3,1", "MacPro4,1", "MacPro5,1"),
                 "10.10": ("MacPro3,1", "MacPro4,1", "MacPro5,1")}
# the most processors each model shipped with
MAC_MODEL_MAX_SMP = {"MacPro1,1": 4, "MacPro2,1": 8, "MacPro3,1": 8, "MacPro4,1": 8,
                     "MacPro5,1": 8}

# SATA ports 1 to 5; port 0 is the generated OpenCore boot disk
DRIVE_SLOTS = tuple(f"SATA port {n}" for n in range(1, 6))
SATA_FIRST_PORT = 1

DRIVE_KINDS = ("disk", "cdrom")


def slot_name(i: int) -> str:
    return DRIVE_SLOTS[i]


def slot_kinds(i: int) -> tuple[str, ...]:
    """Every SATA port takes a hard disk or a CD."""
    return DRIVE_KINDS


def sata_port(i: int) -> int:
    """The AHCI port (``ide.N``) of drive position *i*."""
    return SATA_FIRST_PORT + i


def host_drives(m: Machine) -> list[str]:
    """The host optical drives the machine's CD slots name, in slot order."""
    return [d.file.strip() for d in m.drives
            if d and d.kind == "cdrom" and is_host_drive(d.file)]


SMP_CHOICES = (1, 2, 4, 8)


def smp_option(n: int) -> str:
    """Two sockets above one CPU, as in a Mac Pro."""
    n = int(n)
    if n < 2 or n % 2:
        return str(n)
    return f"{n},sockets=2,cores={n // 2},threads=1"

SMP_DEFAULT = 1
RAM_SIZES = (1024, 2048, 3072, 4096, 6144, 8192, 12288, 16384, 24576, 32768)
# the most memory Apple lists for each model
MAC_MODEL_MAX_RAM = {"MacPro1,1": 16384, "MacPro2,1": 16384, "MacPro3,1": 32768,
                     "MacPro4,1": 32768, "MacPro5,1": 32768}
RAM_CHOICES = RAM_SIZES


def ram_max_mb(mac_model: str) -> int:
    return MAC_MODEL_MAX_RAM.get(mac_model, max(RAM_SIZES))


def ram_choices(mac_model: str) -> tuple[int, ...]:
    return tuple(x for x in RAM_SIZES if x <= ram_max_mb(mac_model))
RAM_DEFAULT = 2048

ACCEL_DEFAULT = "tcg"
RESOLUTIONS = ("1024x768", "1280x800", "1440x900", "1680x1050", "1920x1200")
RESOLUTION_DEFAULT = "1440x900"

GPU_STD = "std"
GPU_X1900 = "x1900"
GPU_HD5770 = "hd5770"
GPU_LABELS = {GPU_STD: "Standard VGA",
              GPU_X1900: "ATI Radeon X1900 XT",
              GPU_HD5770: "ATI Radeon HD 5770"}
GPUS = tuple(GPU_LABELS)
# the firmware driver's file of each card
GPU_ROMS = {GPU_X1900: paths.R580_ROM_NAME, GPU_HD5770: paths.HD5770_ROM_NAME}
# the systems with a driver for each card
GPU_OS = {GPU_X1900: ("10.5", "10.6", "10.7"), GPU_HD5770: ("10.6", "10.7", "10.8", "10.9", "10.10")}
GPU_DEFAULT = GPU_STD
# the only mode the cards' firmware drivers offer
GPU_X1900_RESOLUTION = "1024x768"


def gpu_label(gpu: str) -> str:
    return GPU_LABELS.get(gpu, GPU_LABELS[GPU_DEFAULT])


def gpu_by_label(label: str) -> str:
    for k, v in GPU_LABELS.items():
        if v == label:
            return k
    return GPU_DEFAULT

# the variable store, QEMU's to write: a sudo run gives it back to the user
VARS_FILE = paths.OVMF_VARS_NAME
ESP_DIR = "esp"
ESP_IMAGE = "esp.img"
SERIAL_LOG = "serial.log"
SAVED_SETTINGS_FILES = (VARS_FILE,)

OWNED_FILES = ("machine.json", "run.command", "run.bat", "last-run.log", ESP_IMAGE, SERIAL_LOG,
               VARS_FILE, ".DS_Store")
OWNED_DIRS = (ESP_DIR,)

SMC_KEY_LENGTH = 64


def accel_choices(platform: str = paths.HOST_PLATFORM, arch: str | None = None) -> tuple[str, ...]:
    """The accelerators the host offers: HVF only on an Intel Mac, WHPX only
    on Windows."""
    arch = (arch or _platform.machine()).lower()
    if platform == "darwin":
        return ("tcg", "hvf") if arch in ("x86_64", "amd64") else ("tcg",)
    if paths.is_windows(platform):
        return ("tcg", "whpx")
    return ("tcg",)


def accel_label(accel: str) -> str:
    return {"tcg": "tcg (software)", "hvf": "hvf (macOS hypervisor)",
            "whpx": "whpx (Windows hypervisor)"}.get(accel, accel)


def accel_by_label(label: str) -> str:
    for a in ("tcg", "hvf", "whpx"):
        if accel_label(a) == label:
            return a
    return label


def accel_labels_for_host(platform: str = paths.HOST_PLATFORM, current: str | None = None,
                          arch: str | None = None) -> list[str]:
    """The choices offered, plus whatever the record holds."""
    out = list(accel_choices(platform, arch))
    if current and current not in out:
        out.append(current)
    return [accel_label(a) for a in out]


def smc_key_problem(path: str | Path) -> str | None:
    """A plain reason the SMC key file cannot be used, or None. The key is
    read to count it and is not kept or returned."""
    if not str(path or "").strip():
        return "No SMC key file is chosen."
    p = Path(str(path)).expanduser()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"The SMC key file {p} is not there."
    except (OSError, UnicodeError):
        return f"The SMC key file {p} cannot be read."
    key = text[:-1] if text.endswith("\n") else text
    if key.endswith("\r"):
        key = key[:-1]
    if len(key) != SMC_KEY_LENGTH or not key.isprintable():
        return (f"The SMC key file {p.name} has to hold one line of exactly "
                f"{SMC_KEY_LENGTH} printable characters.")
    if '"' in key:
        return f"The SMC key file {p.name} holds a double quote, which a launcher cannot pass on."
    return None


IMAGE_SUFFIXES = {".img", ".dsk", ".qcow2", ".iso", ".toast", ".cdr", ".dmg",
                  ".hfv", ".hfs", ".vmdk", ".raw"}


def looks_like_disk_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_SUFFIXES


@dataclass
class Drive:
    kind: str = "disk"
    file: str = ""
    format: str = "raw"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "file": self.file, "format": self.format}

    @classmethod
    def from_dict(cls, d: Any) -> "Drive | None":
        if not isinstance(d, dict):
            return None
        return cls(str(d.get("kind", "disk")), str(d.get("file", "")), str(d.get("format", "raw")))


HOSTFWD_PROTOS = ("tcp", "udp")
HOSTFWD_ROWS = 4


@dataclass
class HostFwd:
    proto: str = "tcp"
    host_port: str = ""
    guest_port: str = ""

    def to_dict(self) -> dict:
        return {"proto": self.proto, "host_port": self.host_port, "guest_port": self.guest_port}

    @classmethod
    def from_dict(cls, d: Any) -> "HostFwd":
        if not isinstance(d, dict):
            return cls()
        return cls(str(d.get("proto") or "tcp"), str(d.get("host_port") or "").strip(),
                   str(d.get("guest_port") or "").strip())

    @property
    def empty(self) -> bool:
        return not (self.host_port or self.guest_port)


def _port_ok(text: str) -> bool:
    return text.isascii() and text.isdigit() and 1 <= int(text) <= 65535


@dataclass
class Network:
    mode: str = "user"
    mac: str = DEFAULT_MAC
    ifname: str = ""
    hostfwd: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"mode": self.mode, "mac": self.mac}
        if self.mode in NETWORK_MODES_WITH_IFNAME or self.ifname:
            d["ifname"] = self.ifname
        rules = [r.to_dict() for r in self.hostfwd if not r.empty]
        if rules:
            d["hostfwd"] = rules
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "Network":
        if not isinstance(d, dict):
            return cls()
        rules = d.get("hostfwd")
        return cls(str(d.get("mode", "user")), str(d.get("mac", DEFAULT_MAC)),
                   str(d.get("ifname", "") or ""),
                   [HostFwd.from_dict(r) for r in rules] if isinstance(rules, list) else [])

    @property
    def needs_sudo(self) -> bool:
        return self.mode.startswith("vmnet-")

    @property
    def low_host_port(self) -> bool:
        """Slirp with a non-empty forward whose host port is below 1024."""
        return self.mode == "user" and any(
            not r.empty and str(r.host_port).strip().isdigit() and 0 < int(r.host_port) < 1024
            for r in self.hostfwd)

    @property
    def platform(self) -> str | None:
        return NETWORK_MODE_PLATFORM.get(self.mode)


USB_ID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")


@dataclass
class UsbHostDevice:
    """A host USB device this machine takes, by vendor:product id (lower-case
    hex); the speed picks the bus."""
    id: str = ""
    name: str = ""
    speed: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "speed": self.speed}

    @classmethod
    def from_dict(cls, d: Any) -> "UsbHostDevice | None":
        if not isinstance(d, dict):
            return None
        return cls(str(d.get("id", "") or "").strip().lower(), str(d.get("name", "") or ""),
                   str(d.get("speed", "") or ""))


def usb_host_devices_from(value: Any) -> list[UsbHostDevice]:
    out: list[UsbHostDevice] = []
    for x in value if isinstance(value, list) else []:
        dev = UsbHostDevice.from_dict(x)
        if dev and dev.id and all(dev.id != o.id for o in out):
            out.append(dev)
    return out


SHARE_SCOPES = ("guest-only", "all-interfaces")
SHARE_DEFAULT_USER = "guest"


@dataclass
class Share:
    """One host folder, offered to the guest over FTP while it runs (see
    x86_share.py)."""
    folder: str = ""             # "" = no shared folder
    user: str = SHARE_DEFAULT_USER
    password: str = ""
    scope: str = "guest-only"    # guest-only | all-interfaces
    ftp: bool = False            # serve the folder over FTP

    def to_dict(self) -> dict:
        return {"folder": self.folder, "user": self.user, "password": self.password,
                "scope": self.scope, "ftp": self.ftp}

    @classmethod
    def from_dict(cls, d: Any) -> "Share":
        if not isinstance(d, dict):
            return cls()
        folder = str(d.get("folder", "") or "")
        return cls(folder,
                   str(d.get("user", SHARE_DEFAULT_USER) or SHARE_DEFAULT_USER),
                   str(d.get("password", "") or ""),
                   str(d.get("scope", "guest-only") or "guest-only"),
                   bool(d.get("ftp", False)))

    @property
    def enabled(self) -> bool:
        return bool(self.folder.strip())

    @property
    def ftp_on(self) -> bool:
        return self.enabled and self.ftp


def new_uuid() -> str:
    return str(_uuid.uuid4()).upper()


def name_uuid(name: str) -> str:
    """A uuid derived from the name, for a record that has none."""
    return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{name}.x86-opencore")).upper()


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Machine:
    name: str = "New machine"
    mac_model: str = MAC_MODEL_DEFAULT
    os: str = OS_DEFAULT
    smp: int = SMP_DEFAULT
    ram_mb: int = RAM_DEFAULT
    accel: str = ACCEL_DEFAULT
    display: str = "cocoa"
    vnc: str = ""                  # "" = off; else a -vnc display spec, e.g. ":1"
    gpu: str = GPU_DEFAULT
    resolution: str = RESOLUTION_DEFAULT
    show_picker: bool = False
    boot_args: str = ""            # kernel arguments after the fixed ones
    serial_log: bool = False
    verbose: bool = False
    drives: list = field(default_factory=lambda: [None] * len(DRIVE_SLOTS))
    network: Network = field(default_factory=Network)
    usb_tablet: bool = True        # False: usb-mouse
    builtin_audio: bool = True     # esb2-intel-hda with an ALC885 codec
    startup_chime: bool = True     # played by OpenCore on the built-in audio
    usb_audio: bool = False
    usb_host_devices: list = field(default_factory=list)   # [UsbHostDevice]
    share: Share = field(default_factory=Share)
    rtc_base: str = ""
    extra_args: str = ""
    uuid: str = field(default_factory=new_uuid)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "name": self.name,
            "uuid": self.uuid,
            "mac_model": self.mac_model,
            "os": self.os,
            "smp": self.smp,
            "ram_mb": self.ram_mb,
            "accel": self.accel,
            "display": self.display,
            "vnc": self.vnc,
            "gpu": self.gpu,
            "resolution": self.resolution,
            "show_picker": self.show_picker,
            "boot_args": self.boot_args,
            "serial_log": self.serial_log,
            "verbose": self.verbose,
            "drives": [d.to_dict() if d else None for d in self.drives],
            "network": self.network.to_dict(),
            "usb_tablet": self.usb_tablet,
            "builtin_audio": self.builtin_audio,
            "startup_chime": self.startup_chime,
            "usb_audio": self.usb_audio,
            "usb_host_devices": [u.to_dict() for u in self.usb_host_devices],
            "share": self.share.to_dict(),
            "rtc_base": self.rtc_base,
            "extra_args": self.extra_args,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Machine":
        drives = [Drive.from_dict(x) for x in list(d.get("drives") or [])][:len(DRIVE_SLOTS)]
        while len(drives) < len(DRIVE_SLOTS):
            drives.append(None)
        name = str(d.get("name", "New machine"))
        return cls(
            name=name,
            mac_model=str(d.get("mac_model") or MAC_MODEL_DEFAULT),
            os=str(d.get("os") or OS_DEFAULT),
            smp=_int(d.get("smp", SMP_DEFAULT) or SMP_DEFAULT, SMP_DEFAULT),
            ram_mb=_int(d.get("ram_mb", RAM_DEFAULT), RAM_DEFAULT),
            accel=str(d.get("accel") or ACCEL_DEFAULT),
            display=str(d.get("display") or default_display(paths.HOST_PLATFORM)),
            vnc=str(d.get("vnc", "") or ""),
            gpu=str(d.get("gpu") or GPU_DEFAULT),
            resolution=str(d.get("resolution") or RESOLUTION_DEFAULT),
            show_picker=bool(d.get("show_picker", False)),
            boot_args=str(d.get("boot_args", "") or ""),
            serial_log=bool(d.get("serial_log", False)),
            verbose=bool(d.get("verbose", False)),
            drives=drives,
            network=Network.from_dict(d.get("network")),
            usb_tablet=bool(d.get("usb_tablet", True)),
            builtin_audio=bool(d.get("builtin_audio", True)),
            startup_chime=bool(d.get("startup_chime", True)),
            usb_audio=bool(d.get("usb_audio", False)),
            usb_host_devices=usb_host_devices_from(d.get("usb_host_devices")),
            share=Share.from_dict(d.get("share")),
            rtc_base=str(d.get("rtc_base", "") or ""),
            extra_args=str(d.get("extra_args", "") or ""),
            uuid=str(d.get("uuid") or "").strip().upper() or name_uuid(name),
            notes=str(d.get("notes", "")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Machine":
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, path: Path) -> "Machine":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    def copy(self) -> "Machine":
        return Machine.from_dict(self.to_dict())

    def first_unfilled_disk_slot(self) -> int | None:
        """The first position a new hard disk can go in."""
        for i, d in enumerate(self.drives):
            if d is None or not d.file:
                return i
        return None

    def slot_status(self, i: int) -> str:
        d = self.drives[i]
        if d is None or not d.file:
            return "empty"
        return f"replace {Path(d.file).name}"

    def image_paths(self) -> list[str]:
        return [f for _label, f in _image_files(self) if f]

    @property
    def kernel_arch(self) -> str:
        return OS_KERNEL_ARCH.get(self.os, "i386")

    @property
    def kernel_cache(self) -> str:
        return OS_KERNEL_CACHE.get(self.os, "Mkext")


def new_machine(name: str) -> Machine:
    """A fresh record with the defaults and its own uuid. No file field is
    ever filled in."""
    return Machine(name=name, display=default_display(paths.HOST_PLATFORM), uuid=new_uuid())


def file_fields(m: Machine) -> dict[str, str]:
    return {f"drives[{i}]": (d.file if d else "") for i, d in enumerate(m.drives)}


def start_blockers(m: Machine, key_file: str | Path | None = None,
                   qemu_dir: str | Path | None = None) -> list[str]:
    """What stops a start: the SMC key file, the X1900 ROM file."""
    why = smc_key_problem(key_file if key_file is not None else paths.default_smc_key_file())
    out = [why] if why else []
    if m.gpu in GPU_ROMS:
        rom = Path(qemu_dir) if qemu_dir else paths.install_dir()
        if not (rom / GPU_ROMS[m.gpu]).is_file():
            out.append(f"The graphics card needs the file {GPU_ROMS[m.gpu]} in the "
                       "folder with the program, and it is not there.")
    return out


# ---------------------------------------------------------------- checking

def boot_arg_tokens(text: str) -> list[str]:
    return (text or "").split()


def validate(m: Machine, qemu_dir: str | None = None, platform: str = paths.HOST_PLATFORM,
             check_files: bool = True, machine_dir: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not m.name or not m.name.strip():
        errors.append("This machine has no name.")
    elif not NAME_RE.match(m.name) or m.name.strip() != m.name:
        errors.append("That name will not work.")
    if m.mac_model not in MAC_MODELS:
        errors.append(f"'{m.mac_model}' is not a Mac model this machine can be.")
    if m.os not in OS_VERSIONS:
        errors.append(f"'{m.os}' is not a Mac OS X version this machine can run.")
    elif m.mac_model in MAC_MODELS and m.mac_model not in OS_MAC_MODELS.get(m.os, MAC_MODELS):
        errors.append(f"Mac OS X {m.os} needs the Mac model "
                      + " or ".join(OS_MAC_MODELS[m.os]) + ".")
    if m.ram_mb not in RAM_SIZES:
        errors.append("Memory has to be " + ", ".join(str(x) for x in RAM_SIZES) + " MB.")
    elif m.ram_mb > ram_max_mb(m.mac_model):
        errors.append(f"A {m.mac_model} takes at most {ram_max_mb(m.mac_model)} MB.")
    if m.smp not in SMP_CHOICES:
        errors.append("Processors has to be " + ", ".join(str(x) for x in SMP_CHOICES) + ".")
    elif m.smp > MAC_MODEL_MAX_SMP.get(m.mac_model, max(SMP_CHOICES)):
        errors.append(f"A {m.mac_model} has at most "
                      f"{MAC_MODEL_MAX_SMP[m.mac_model]} processors.")
    if m.os == "10.5" and m.mac_model == "MacPro3,1":
        warnings.append("A MacPro3,1 needs a Mac OS X 10.5.1 or later install disc; "
                        "the original 10.5.0 disc is not meant for it.")
    first = MAC_MODEL_FIRST_OS.get(m.mac_model)
    if first and m.os in OS_VERSIONS and first.startswith(m.os + "."):
        warnings.append(f"A {m.mac_model} needs a Mac OS X {first} or later install disc.")
    if m.accel not in ("tcg", "hvf", "whpx"):
        errors.append(f"'{m.accel}' is not an acceleration setting.")
    elif m.accel not in accel_choices(platform):
        warnings.append(f"{m.accel} does not work on this computer.")
    if m.gpu not in GPUS:
        errors.append(f"'{m.gpu}' is not a graphics card this machine can have.")
    elif m.os in OS_VERSIONS and m.os not in GPU_OS.get(m.gpu, OS_VERSIONS):
        warnings.append(f"Mac OS X {os_label(m.os)} has no driver for the {gpu_label(m.gpu)}: "
                        "the screen stays at 1024x768 without acceleration.")
    if m.resolution not in RESOLUTIONS:
        errors.append("Screen size at boot has to be " + ", ".join(RESOLUTIONS) + ".")
    if m.display == "cocoa" and platform != "darwin":
        warnings.append("'cocoa' only works on a Mac.")
    if m.vnc.strip() and not VNC_RE.match(m.vnc.strip()):
        errors.append("VNC display has to look like :1 or 127.0.0.1:1.")
    if m.rtc_base.strip() and not RTC_BASE_RE.match(m.rtc_base.strip()):
        errors.append("Date and time has to be localtime, utc, or look like "
                      "2005-04-29T10:30:00.")

    net = m.network
    if net.mode not in NETWORK_MODES:
        errors.append(f"'{net.mode}' is not a network setting.")
    else:
        if net.mode != "none" and not MAC_RE.match(net.mac):
            errors.append("The card address has to look like 52:54:00:12:34:56.")
        if net.mode in NETWORK_MODES_WITH_IFNAME and not net.ifname.strip():
            errors.append("No interface named.")
        for r in net.hostfwd:
            if r.empty:
                continue
            if r.proto not in HOSTFWD_PROTOS:
                errors.append(f"'{r.proto}' is not a forwarding protocol.")
            if not (_port_ok(r.host_port) and _port_ok(r.guest_port)):
                errors.append("Port forwarding needs host and guest ports from 1 to 65535.")
        host = "win32" if paths.is_windows(platform) else platform
        if net.platform is not None and net.platform != host:
            warnings.append("This network setting only works on "
                            f"{'a Mac' if net.platform == 'darwin' else 'Windows'}.")
    if len(m.drives) != len(DRIVE_SLOTS):
        errors.append(f"There are not {len(DRIVE_SLOTS)} drive positions.")
    for i, d in enumerate(m.drives[:len(DRIVE_SLOTS)]):
        if d is not None and d.file and d.kind not in DRIVE_KINDS:
            errors.append(f"{slot_name(i)} has no drive type.")

    share = m.share
    if share.scope not in SHARE_SCOPES:
        errors.append(f"'{share.scope}' is not a sharing setting.")
    if share.enabled:
        if not Path(share.folder.strip()).expanduser().is_dir():
            errors.append("The shared folder is not a folder that exists.")
        if not share.ftp:
            warnings.append("The shared folder is not served over FTP.")
    if share.ftp_on:
        if not share.user.strip():
            errors.append("The shared folder has no user name.")
        if share.scope == "all-interfaces" and not share.password:
            errors.append("Sharing on all interfaces needs a password.")
        if share.scope == "guest-only" and net.mode != "user":
            warnings.append("Guest only sharing is only reachable with default (slirp).")

    for u in m.usb_host_devices:
        if not USB_ID_RE.match(u.id):
            errors.append(f"'{u.id}' is not a USB device id like 046d:0990.")
    if m.usb_host_devices and platform != "darwin" and not paths.is_windows(platform):
        warnings.append("Host USB devices only work on a Mac or on Windows.")

    if check_files:
        for label, f in _image_files(m):
            if not f:
                continue
            p = Path(f).expanduser()
            if not p.is_absolute():
                if machine_dir is None:
                    continue
                p = Path(machine_dir) / p
            if not p.is_file():
                warnings.append(f"{label}: {f} is not there.")
    return errors, warnings


def _image_files(m: Machine):
    for i, d in enumerate(m.drives):
        if d and not is_host_drive(d.file):
            yield slot_name(i), d.file


def check_new_image_path(folder: Path | str, name: str, fmt: str) -> tuple[Path | None, str | None]:
    name = (name or "").strip()
    if not name:
        return None, "Give the disk a name."
    if "/" in name or "\\" in name or name in (".", ".."):
        return None, "The name cannot contain slashes."
    suffixes = (".img", ".qcow2", ".dsk")
    if not name.lower().endswith(suffixes):
        name += ".qcow2" if fmt == "qcow2" else ".img"
    target = Path(folder) / name
    if target.exists() or target.is_symlink():
        return None, f"There is already a file called {name}."
    return target, None


# ---------------------------------------------------------------- machines

@dataclass
class DeleteResult:
    folder: Path
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    folder_removed: bool = False

    @property
    def kept_images(self) -> list[str]:
        return [f for f in self.kept if looks_like_disk_image(f)]


def _owned(rel: str) -> bool:
    """A file of the machine folder this program made (a path relative to it)."""
    return rel in OWNED_FILES or any(rel.startswith(d + "/") for d in OWNED_DIRS)


class Library:
    """The Machines folder: one subfolder per machine, named after it.
    Nothing here ever deletes a disk image, and nothing ever picks a file."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root).expanduser() if root else paths.machines_dir()

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, name: str) -> Path:
        return self.root / name

    def json_path(self, name: str) -> Path:
        return self.folder(name) / "machine.json"

    def names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        out = []
        for p in sorted(self.root.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir() and (p / "machine.json").is_file():
                out.append(p.name)
        return out

    def load(self, name: str) -> Machine:
        m = Machine.load(self.json_path(name))
        m.name = name
        return m

    def load_all(self) -> list[Machine]:
        out = []
        for n in self.names():
            try:
                out.append(self.load(n))
            except (OSError, ValueError, KeyError, TypeError):
                out.append(Machine(name=n, notes="(unreadable)"))
        return out

    def save(self, m: Machine, old_name: str | None = None) -> Path:
        if not NAME_RE.match(m.name):
            raise ValueError("illegal machine name")
        self.ensure()
        if old_name and old_name != m.name and self.folder(old_name).is_dir():
            if self.folder(m.name).exists():
                raise FileExistsError(f"A machine called '{m.name}' already exists.")
            old_folder, new_folder = self.folder(old_name), self.folder(m.name)
            moved = [(old_folder, new_folder),
                     (old_folder.resolve(), new_folder.parent.resolve() / new_folder.name)]
            old_folder.rename(new_folder)
            _repoint_images(m, moved)
        self.folder(m.name).mkdir(parents=True, exist_ok=True)
        m.save(self.json_path(m.name))
        return self.folder(m.name)

    def exists(self, name: str) -> bool:
        return self.folder(name).exists()

    def has_record(self, name: str) -> bool:
        return self.json_path(name).is_file()

    def usb_conflicts(self, m: Machine) -> list[str]:
        """The host devices of *m* another machine also passes through."""
        out = []
        mine = {u.id: u for u in m.usb_host_devices}
        for other in self.load_all():
            if other.name == m.name:
                continue
            for u in other.usb_host_devices:
                if u.id in mine:
                    out.append(f"{mine[u.id].name or u.id} ({u.id}) is also passed through "
                               f"by “{other.name}”: untick it in one of the two machines.")
        return out

    def duplicate(self, name: str, new_name: str) -> Machine:
        if self.exists(new_name):
            raise FileExistsError(f"A machine called '{new_name}' already exists.")
        m = self.load(name)
        m.name = new_name
        m.uuid = new_uuid()
        m.usb_host_devices = []      # a host device goes to one machine only
        self.save(m)
        for f in SAVED_SETTINGS_FILES:
            src = self.folder(name) / f
            dst = self.folder(new_name) / f
            if src.is_file() and not dst.exists():
                shutil.copy2(src, dst)
        return m

    def folder_contents(self, name: str) -> list[str]:
        d = self.folder(name)
        if not d.is_dir():
            return []
        return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() or p.is_symlink())

    def delete_preview(self, name: str) -> tuple[list[str], list[str]]:
        contents = self.folder_contents(name)
        removed = [f for f in contents if _owned(f)]
        kept = [f for f in contents if not _owned(f)]
        return removed, kept

    def delete(self, name: str) -> DeleteResult:
        d = self.folder(name)
        result = DeleteResult(folder=d)
        if not d.is_dir() or d.resolve().parent != self.root.resolve():
            return result
        for f in self.folder_contents(name):
            if not _owned(f):
                continue
            p = d / f
            try:
                p.unlink()
            except OSError:
                continue
            result.removed.append(f)
        for top in OWNED_DIRS:
            base = d / top
            if base.is_dir():
                for sub in sorted((q for q in base.rglob("*") if q.is_dir()),
                                  key=lambda q: len(q.parts), reverse=True) + [base]:
                    try:
                        sub.rmdir()
                    except OSError:
                        pass
        result.kept = self.folder_contents(name)
        if not result.kept:
            for sub in sorted((p for p in d.rglob("*") if p.is_dir()),
                              key=lambda p: len(p.parts), reverse=True):
                try:
                    sub.rmdir()
                except OSError:
                    pass
            try:
                d.rmdir()
                result.folder_removed = True
            except OSError:
                pass
        return result

    def saved_settings_status(self, name: str) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        for f in SAVED_SETTINGS_FILES:
            p = self.folder(name) / f
            out[f] = p.stat().st_size if p.is_file() else None
        return out

    def clear_saved_settings(self, name: str) -> list[str]:
        removed = []
        for f in SAVED_SETTINGS_FILES:
            p = self.folder(name) / f
            if p.is_file():
                p.unlink()
                removed.append(f)
        return removed


def _repoint_images(m: Machine, moved: list[tuple[Path, Path]]) -> None:
    def fixed(p: str) -> str:
        if not p:
            return p
        for old_folder, new_folder in moved:
            try:
                rel = Path(p).relative_to(old_folder)
            except ValueError:
                continue
            return str(new_folder / rel)
        return p

    for d in m.drives:
        if d and not is_host_drive(d.file):
            d.file = fixed(d.file)
