"""Build the QEMU argv for an x86 Machine and render it as run.command /
run.bat.

Pure apart from ``write_launcher``. See ``qemugui/x86_model.py`` for the
machine facts each choice rests on.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from . import paths
from .paths import (qopt, split_extra_args, group_options, bat_quote, drive_format,
                    SUDO_KEEPALIVE)  # re-exported
from . import x86_model as model
from . import usbhost
from .x86_model import Machine

HEADER_NOTE = f"Written by {paths.APP_NAME}. Do not edit."

PC_BIOS_DIR = paths.PC_BIOS_DIR_NAME
MACHINE_TYPE = "q35,i8042=off"
CPU_TYPE = "Penryn,vendor=GenuineIntel"
# given only under TCG on a Mac host
TCG_TSC_FREQUENCY = 1200000000
TCG_ACCEL = "tcg,thread=multi,tb-size=512"
USB_AUDIODEV = "usb"
HDA_AUDIODEV = "hda0"
HDA_SLOT = "0x1b"
NETDEV_ID = "n0"
SMC_VAR = "OSK"
UHCI_BUS = "uhci.0"
# Mac OS X 10.5 cuts 7.5% off each edge of an absolute axis
TABLET_INSET = 75


def _path(p: str, base: str, platform: str) -> str:
    return paths.join_path(base, p, platform)


def netdev_option(net) -> str:
    """The -netdev backend; the card is an e1000."""
    if net.mode == "user":
        fwd = "".join(f",hostfwd={r.proto}::{r.host_port}-:{r.guest_port}"
                      for r in net.hostfwd if not r.empty)
        return f"user,id={NETDEV_ID}{fwd}"
    if net.mode in ("vmnet-bridged", "tap"):
        return f"{net.mode},id={NETDEV_ID},ifname={qopt(net.ifname)}"
    if net.mode in ("vmnet-shared", "vmnet-host"):
        return f"{net.mode},id={NETDEV_ID}"
    raise ValueError(f"unknown network mode {net.mode!r}")


def network_tokens(net) -> list[str]:
    if net.mode == "none":
        return ["-nic", "none"]
    return ["-netdev", netdev_option(net),
            "-device", f"e1000-82545em,netdev={NETDEV_ID},mac={net.mac}"]


def needs_sudo(m: Machine, platform: str = paths.HOST_PLATFORM) -> bool:
    """vmnet, host forward ports below 1024, and QEMU's usb-host, which takes a device from macOS only as
    root."""
    usb = platform == "darwin" and bool(m.usb_host_devices)
    return paths.sudo_applies(m.network.needs_sudo or m.network.low_host_port or usb, platform)


def _usb_audio_added(m: Machine, extra: list[str]) -> bool:
    return m.usb_audio and not any(t.split(",")[0] == "usb-audio" for t in extra)


def builtin_audio_added(m: Machine, extra: list[str]) -> bool:
    return m.builtin_audio and not any(t.split(",")[0] in ("esb2-intel-hda", "hda-alc885")
                                       for t in extra)


def accel_tokens(m: Machine) -> list[str]:
    return ["-accel", TCG_ACCEL if m.accel == "tcg" else m.accel]


def cpu_option(m: Machine, platform: str) -> str:
    tsc = f",tsc-frequency={TCG_TSC_FREQUENCY}" if platform == "darwin" and m.accel == "tcg" else ""
    return CPU_TYPE + tsc


def drive_tokens(m: Machine, machine_dir: str, platform: str) -> list[str]:
    out: list[str] = []
    for i, d in enumerate(m.drives):
        if d is None or not d.file:
            continue
        port = model.sata_port(i)
        ident = f"sata{port}"
        cd = d.kind == "cdrom"
        host = cd and paths.is_host_drive(d.file)
        fmt = "raw" if host else drive_format(d.format, d.file, machine_dir)
        if host:
            src = paths.host_drive_option(d.file, platform)
            out += ["-drive", f"id={ident},if=none,{src},media=cdrom"]
        elif cd:
            out += ["-drive", f"id={ident},if=none,format={fmt},readonly=on,media=cdrom,"
                              f"file={qopt(_path(d.file, machine_dir, platform))}"]
        else:
            snap = ",snapshot=on" if fmt == "dmg" else ""
            out += ["-drive", f"id={ident},if=none,format={fmt},"
                              f"file={qopt(_path(d.file, machine_dir, platform))}{snap}"]
        out += ["-device", f"{'ide-cd' if cd else 'ide-hd'},bus=ide.{port},drive={ident}"]
    return out


def gpu_tokens(m: Machine, qemu_dir: str, platform: str) -> list[str]:
    if m.gpu not in model.GPU_ROMS:
        return ["-vga", "std"]
    rom = _path(model.GPU_ROMS[m.gpu], qemu_dir, platform)
    if m.gpu == model.GPU_HD5770:
        # the monitor's preferred size; the firmware starts at 1024x768
        w, h = m.resolution.split("x")
        card = f"ati-radeon-hd5770,bus=br1,addr=0x0,romfile={qopt(rom)},xres={w},yres={h}"
        if m.gpu_accel:
            card += ",accel=on"
    else:
        card = f"ati-radeon-x1900,bus=br1,romfile={qopt(rom)}"
    return ["-vga", "none",
            "-device", "pci-bridge,id=br1,bus=pcie.0,addr=0x1,chassis_nr=1,shpc=off",
            "-device", card]


def build_argv(m: Machine, qemu_dir: str, machine_dir: str,
               platform: str = paths.HOST_PLATFORM, owned=None) -> list[str]:
    """The complete argv, first token = absolute path of the QEMU binary.
    The SMC key is a run-time reference (see ``paths.runtime_ref``), never
    the key. *owned*: on Windows, the ids of the devices QEMU owns now (on
    WinUSB); only those of the ticked devices are passed through, none
    without it."""
    qd = qemu_dir
    argv: list[str] = [paths.join_path(qd, paths.qemu_binary_name(platform), platform)]

    pc_bios = _path(PC_BIOS_DIR, qd, platform)
    argv += ["-L", pc_bios, "-name", m.name.replace(",", "")]
    argv += ["-M", MACHINE_TYPE]
    argv += accel_tokens(m)
    argv += ["-m", str(int(m.ram_mb)), "-smp", model.smp_option(m.smp)]
    argv += ["-global", "ICH9-LPC.disable_s3=1", "-global", "ICH9-LPC.disable_s4=1",
             "-global", "mc146818rtc.ext-ram=on"]
    argv += ["-cpu", cpu_option(m, platform)]
    argv += ["-drive", "if=pflash,format=raw,readonly=on,file="
                       + qopt(_path(paths.OVMF_CODE_NAME, pc_bios, platform))]
    argv += ["-drive", "if=pflash,format=raw,file="
                       + qopt(_path(model.VARS_FILE, machine_dir, platform))]
    argv += ["-smbios", "type=2"]
    argv += ["-device", "isa-applesmc,osk=" + paths.runtime_ref(SMC_VAR)]
    argv += gpu_tokens(m, qd, platform)
    if m.vnc.strip():
        argv += ["-display", "none", "-vnc", m.vnc.strip()]
    else:
        argv += ["-display", m.display]
    argv += ["-drive", "id=esp,if=none,format=raw,file="
                       + qopt(_path(model.ESP_IMAGE, machine_dir, platform)),
             "-device", "ide-hd,bus=ide.0,drive=esp"]
    argv += drive_tokens(m, machine_dir, platform)

    extra = split_extra_args(m.extra_args, platform)
    argv += ["-device", "piix3-usb-uhci,id=uhci", "-device", f"usb-kbd,bus={UHCI_BUS}",
             "-device", (f"usb-tablet,bus={UHCI_BUS},axis-inset={TABLET_INSET}" if m.usb_tablet
                         else f"usb-mouse,bus={UHCI_BUS}")]
    if builtin_audio_added(m, extra):
        audio = paths.resolve_audio("default", platform)
        argv += ["-audiodev", f"{audio},id={HDA_AUDIODEV}",
                 "-device", f"esb2-intel-hda,id=hda,bus=pcie.0,addr={HDA_SLOT}",
                 "-device", f"hda-alc885,id=codec,bus=hda.0,audiodev={HDA_AUDIODEV}"]
    if _usb_audio_added(m, extra):
        audio = paths.resolve_audio("default", platform)
        argv += ["-audiodev", f"{audio},id={USB_AUDIODEV}",
                 "-device", f"usb-audio,audiodev={USB_AUDIODEV},bus={UHCI_BUS}"]
    argv += network_tokens(m.network)
    if m.serial_log:
        argv += ["-serial", "file:" + _path(model.SERIAL_LOG, machine_dir, platform)]
    if platform == "darwin":
        argv += usbhost.qemu_tokens([(u.id, u.speed) for u in m.usb_host_devices])
    elif paths.is_windows(platform) and owned:
        argv += usbhost.qemu_tokens([(u.id, u.speed) for u in m.usb_host_devices
                                     if u.id in owned])
    if m.rtc_base.strip():
        argv += ["-rtc", f"base={m.rtc_base.strip()}"]
    argv += extra
    return argv


# QEMU writes the variable store and the serial log; a sudo run gets them back.
OWNED_SETTINGS_FILES = (model.VARS_FILE, model.SERIAL_LOG)


def extra_count(m: Machine, platform: str = paths.HOST_PLATFORM) -> int:
    return len(split_extra_args(m.extra_args, platform))


def runtime_vars(key_file: str | None = None) -> tuple:
    return ((SMC_VAR, str(key_file) if key_file else str(paths.default_smc_key_file())),)


def render_shell(argv: list[str], sudo: bool = False, extra: int = 0, key_file=None) -> str:
    return paths.render_shell(argv, HEADER_NOTE, OWNED_SETTINGS_FILES, sudo, extra,
                              runtime_vars(key_file))


def render_bat(argv: list[str], extra: int = 0, title: str = "", key_file=None) -> str:
    return paths.render_bat(argv, HEADER_NOTE, extra, title, runtime_vars(key_file))


def render_launcher(argv: list[str], platform: str = paths.HOST_PLATFORM, sudo: bool = False,
                    extra: int = 0, title: str = "", key_file=None) -> str:
    return paths.render_launcher(argv, HEADER_NOTE, platform, sudo, OWNED_SETTINGS_FILES, extra,
                                 title, runtime_vars(key_file))


def launcher_text(m: Machine, qemu_dir: str, machine_dir: str,
                  platform: str = paths.HOST_PLATFORM, owned=None, key_file=None) -> str:
    return render_launcher(build_argv(m, qemu_dir, machine_dir, platform, owned), platform,
                           needs_sudo(m, platform), extra_count(m, platform), m.name, key_file)


def ensure_vars(machine_dir: str | Path, pc_bios_dir: str | Path) -> Path:
    """The machine's variable store, copied from the firmware's empty one
    when there is none. An existing one is never touched."""
    target = Path(machine_dir) / model.VARS_FILE
    if not target.exists():
        shutil.copyfile(Path(pc_bios_dir) / paths.OVMF_VARS_TEMPLATE_NAME, target)
    return target


def write_launcher(m: Machine, qemu_dir: str, machine_dir: str,
                   platform: str = paths.HOST_PLATFORM, owned=None, key_file=None):
    """Writes the OpenCore disk (esp/, esp.img), the variable store when it
    is missing, and the launcher."""
    from . import x86_esp
    Path(machine_dir).mkdir(parents=True, exist_ok=True)
    ensure_vars(machine_dir, Path(qemu_dir) / PC_BIOS_DIR)
    x86_esp.write_esp(m, qemu_dir, machine_dir)
    argv = build_argv(m, qemu_dir, machine_dir, platform, owned)
    text = render_launcher(argv, platform, needs_sudo(m, platform), extra_count(m, platform),
                           m.name, key_file)
    path = Path(machine_dir) / paths.launcher_name(platform)
    path.write_text(text, encoding="utf-8", newline="")
    if not paths.is_windows(platform):
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path, argv
