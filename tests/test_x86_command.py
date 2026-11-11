"""Golden-output tests for qemugui.x86_command / x86_model / paths
(headless, no Tk).

Run:  python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import support  # noqa: E402
from qemugui import x86_command as command  # noqa: E402
from qemugui import x86_model as model  # noqa: E402
from qemugui import paths  # noqa: E402
from qemugui.x86_model import Machine, Drive, HostFwd, Network  # noqa: E402

FIXTURES = HERE / "fixtures"
QD = "/Applications/qemu-x86"
MD = "/Machines/Leopard"
KEY = "/Applications/qemu-x86/OSK-Key.txt"
WQD, WMD, WKEY = r"C:\qemu-x86", r"C:\Machines\Leopard", r"C:\qemu-x86\OSK-Key.txt"


def plain(**kw) -> Machine:
    kw.setdefault("name", "Leopard")
    kw.setdefault("display", "cocoa")
    kw.setdefault("uuid", "11111111-2222-3333-4444-555555555555")
    return Machine(**kw)


def default_with_two_drives() -> Machine:
    return plain(drives=[Drive("disk", "/images/leopard.qcow2", "qcow2"),
                         Drive("cdrom", "/images/10.5.iso", "raw"), None, None, None])


def argv_of(m: Machine, platform: str = "darwin", qd: str = QD, md: str = MD) -> list[str]:
    return command.build_argv(m, qd, md, platform)


def pairs(argv):
    return command.group_options(argv)


def option(argv, flag):
    return [g[1] for g in pairs(argv) if g[0] == flag]


MAC_ARGV = [
    f"{QD}/qemu-system-x86_64", "-L", f"{QD}/pc-bios", "-name", "Leopard",
    "-M", "q35,i8042=off",
    "-accel", "tcg,thread=multi,tb-size=512",
    "-m", "2048", "-smp", "1",
    "-global", "ICH9-LPC.disable_s3=1", "-global", "ICH9-LPC.disable_s4=1",
    "-cpu", "Penryn,vendor=GenuineIntel,tsc-frequency=1200000000",
    "-drive", f"if=pflash,format=raw,readonly=on,file={QD}/pc-bios/edk2-x86_64-code.fd",
    "-drive", f"if=pflash,format=raw,file={MD}/OVMF_VARS.fd",
    "-smbios", "type=2",
    "-device", "isa-applesmc,osk={{OSK}}",
    "-vga", "std",
    "-display", "cocoa",
    "-drive", f"id=esp,if=none,format=raw,file={MD}/esp.img",
    "-device", "ide-hd,bus=ide.0,drive=esp",
    "-drive", "id=sata1,if=none,format=qcow2,file=/images/leopard.qcow2",
    "-device", "ide-hd,bus=ide.1,drive=sata1",
    "-drive", "id=sata2,if=none,format=raw,readonly=on,media=cdrom,file=/images/10.5.iso",
    "-device", "ide-cd,bus=ide.2,drive=sata2",
    "-device", "piix3-usb-uhci,id=uhci", "-device", "usb-kbd,bus=uhci.0",
    "-device", "usb-tablet,bus=uhci.0,axis-inset=75",
    "-netdev", "user,id=n0",
    "-device", "e1000-82545em,netdev=n0,mac=52:54:00:12:34:56",
]

RUN_COMMAND = f"""#!/bin/bash
# Written by Qemu-system-x86_64 OpenCore GUI. Do not edit.
cd "$(dirname "$0")"

OSK="$(cat '{KEY}')"

{QD}/qemu-system-x86_64 \\
-L {QD}/pc-bios \\
-name Leopard \\
-M q35,i8042=off \\
-accel tcg,thread=multi,tb-size=512 \\
-m 2048 \\
-smp 1 \\
-global ICH9-LPC.disable_s3=1 \\
-global ICH9-LPC.disable_s4=1 \\
-cpu Penryn,vendor=GenuineIntel,tsc-frequency=1200000000 \\
-drive if=pflash,format=raw,readonly=on,file={QD}/pc-bios/edk2-x86_64-code.fd \\
-drive if=pflash,format=raw,file={MD}/OVMF_VARS.fd \\
-smbios type=2 \\
-device "isa-applesmc,osk=$OSK" \\
-vga std \\
-display cocoa \\
-drive id=esp,if=none,format=raw,file={MD}/esp.img \\
-device ide-hd,bus=ide.0,drive=esp \\
-drive id=sata1,if=none,format=qcow2,file=/images/leopard.qcow2 \\
-device ide-hd,bus=ide.1,drive=sata1 \\
-drive id=sata2,if=none,format=raw,readonly=on,media=cdrom,file=/images/10.5.iso \\
-device ide-cd,bus=ide.2,drive=sata2 \\
-device piix3-usb-uhci,id=uhci \\
-device usb-kbd,bus=uhci.0 \\
-device usb-tablet,bus=uhci.0,axis-inset=75 \\
-netdev user,id=n0 \\
-device e1000-82545em,netdev=n0,mac=52:54:00:12:34:56
"""

RUN_BAT = "\r\n".join([
    "@echo off",
    "rem Written by Qemu-system-x86_64 OpenCore GUI. Do not edit.",
    "title Leopard",
    "mode con: cols=100 lines=30",
    'cd /d "%~dp0"',
    "",
    f'set /p OSK=<"{WKEY}"',
    "",
    rf"{WQD}\qemu-system-x86_64.exe ^",
    rf'-L {WQD}\pc-bios ^',
    "-name Leopard ^",
    '-M "q35,i8042=off" ^',
    '-accel "tcg,thread=multi,tb-size=512" ^',
    "-m 2048 ^",
    "-smp 1 ^",
    '-global ICH9-LPC.disable_s3=1 ^',
    '-global ICH9-LPC.disable_s4=1 ^',
    '-cpu "Penryn,vendor=GenuineIntel" ^',
    rf'-drive "if=pflash,format=raw,readonly=on,file={WQD}\pc-bios\edk2-x86_64-code.fd" ^',
    rf'-drive "if=pflash,format=raw,file={WMD}\OVMF_VARS.fd" ^',
    "-smbios type=2 ^",
    '-device "isa-applesmc,osk=%OSK%" ^',
    "-vga std ^",
    "-display sdl ^",
    rf'-drive "id=esp,if=none,format=raw,file={WMD}\esp.img" ^',
    '-device "ide-hd,bus=ide.0,drive=esp" ^',
    r'-drive "id=sata1,if=none,format=qcow2,file=C:\images\leopard.qcow2" ^',
    '-device "ide-hd,bus=ide.1,drive=sata1" ^',
    r'-drive "id=sata2,if=none,format=raw,readonly=on,media=cdrom,file=C:\images\10.5.iso" ^',
    '-device "ide-cd,bus=ide.2,drive=sata2" ^',
    '-device "piix3-usb-uhci,id=uhci" ^',
    '-device "usb-kbd,bus=uhci.0" ^',
    '-device "usb-tablet,bus=uhci.0,axis-inset=75" ^',
    '-netdev "user,id=n0" ^',
    '-device "e1000-82545em,netdev=n0,mac=52:54:00:12:34:56"',
    "",
    "if errorlevel 1 pause",
    "",
])


X1900_LINES = (
    "-vga none \\\n"
    "-device pci-bridge,id=br1,bus=pcie.0,addr=0x1,chassis_nr=1,shpc=off \\\n"
    f"-device ati-radeon-x1900,bus=br1,romfile={QD}/ati-r580-gop.rom \\\n")
RUN_COMMAND_X1900 = RUN_COMMAND.replace("-vga std \\\n", X1900_LINES)

X1900_BAT_LINES = [
    "-vga none ^",
    '-device "pci-bridge,id=br1,bus=pcie.0,addr=0x1,chassis_nr=1,shpc=off" ^',
    rf'-device "ati-radeon-x1900,bus=br1,romfile={WQD}\ati-r580-gop.rom" ^']


class GoldenCommandLines(unittest.TestCase):
    """Whole argv lists and launchers, compared exactly."""

    def test_default_machine_with_a_disk_and_a_cd_on_a_mac(self):
        self.assertEqual(argv_of(default_with_two_drives()), MAC_ARGV)

    def test_run_command(self):
        text = command.launcher_text(default_with_two_drives(), QD, MD, "darwin", key_file=KEY)
        self.assertEqual(text, RUN_COMMAND)

    def test_run_bat(self):
        m = plain(display="sdl", drives=[Drive("disk", r"C:\images\leopard.qcow2", "qcow2"),
                                         Drive("cdrom", r"C:\images\10.5.iso", "raw"),
                                         None, None, None])
        text = command.launcher_text(m, WQD, WMD, "win32", key_file=WKEY)
        self.assertEqual(text, RUN_BAT)

    @support.needs_bash
    def test_the_run_command_is_valid_shell(self):
        r = subprocess.run([support.BASH, "-n"], input=RUN_COMMAND, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_run_command_with_the_x1900(self):
        m = default_with_two_drives()
        m.gpu = "x1900"
        text = command.launcher_text(m, QD, MD, "darwin", key_file=KEY)
        self.assertEqual(text, RUN_COMMAND_X1900)
        self.assertNotIn("-vga std", text)

    @support.needs_bash
    def test_the_x1900_run_command_is_valid_shell(self):
        r = subprocess.run([support.BASH, "-n"], input=RUN_COMMAND_X1900, text=True,
                           capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_run_bat_with_the_x1900(self):
        m = plain(display="sdl", gpu="x1900",
                  drives=[Drive("disk", r"C:\images\leopard.qcow2", "qcow2"),
                          Drive("cdrom", r"C:\images\10.5.iso", "raw"), None, None, None])
        want = RUN_BAT.replace("-vga std ^", "\r\n".join(X1900_BAT_LINES))
        self.assertEqual(command.launcher_text(m, WQD, WMD, "win32", key_file=WKEY), want)

    def test_the_x1900_argv_on_both_hosts(self):
        a = argv_of(plain(gpu="x1900"))
        i = a.index("-vga")
        self.assertEqual(a[i:i + 6], [
            "-vga", "none",
            "-device", "pci-bridge,id=br1,bus=pcie.0,addr=0x1,chassis_nr=1,shpc=off",
            "-device", f"ati-radeon-x1900,bus=br1,romfile={QD}/ati-r580-gop.rom"])
        w = argv_of(plain(gpu="x1900"), "win32", WQD, WMD)
        self.assertIn(rf"ati-radeon-x1900,bus=br1,romfile={WQD}\ati-r580-gop.rom", w)
        self.assertEqual(option(argv_of(plain(gpu="std")), "-vga"), ["std"])

    def test_a_fixture_record_end_to_end(self):
        m = Machine.load(FIXTURES / "x86-leopard.json")
        argv = argv_of(m)
        self.assertEqual(argv[argv.index("-smp") + 1], "2,sockets=2,cores=1,threads=1")
        self.assertEqual(argv[argv.index("-m") + 1], "3072")
        self.assertEqual(option(argv, "-serial"), [f"file:{MD}/serial.log"])
        self.assertEqual(option(argv, "-audiodev"), ["coreaudio,id=usb"])
        self.assertIn("usb-audio,audiodev=usb,bus=uhci.0", option(argv, "-device"))

    def test_the_argv_holds_a_reference_never_the_key(self):
        text = " ".join(argv_of(default_with_two_drives()))
        self.assertIn("osk={{OSK}}", text)
        self.assertNotIn(support.DUMMY_KEY, text)


class Pieces(unittest.TestCase):

    def test_name_loses_commas(self):
        argv = argv_of(plain(name="a,b"))
        self.assertEqual(option(argv, "-name"), ["ab"])

    def test_accel(self):
        self.assertEqual(option(argv_of(plain(accel="tcg")), "-accel"),
                         ["tcg,thread=multi,tb-size=512"])
        self.assertEqual(option(argv_of(plain(accel="hvf")), "-accel"), ["hvf"])
        self.assertEqual(option(argv_of(plain(accel="whpx"), "win32", WQD, WMD), "-accel"),
                         ["whpx"])

    def test_tsc_frequency_only_for_tcg_on_a_mac(self):
        tsc = "tsc-frequency=1200000000"
        self.assertIn(tsc, option(argv_of(plain()), "-cpu")[0])
        self.assertNotIn(tsc, option(argv_of(plain(accel="hvf")), "-cpu")[0])
        self.assertNotIn(tsc, option(argv_of(plain(), "win32", WQD, WMD), "-cpu")[0])
        self.assertNotIn(tsc, option(argv_of(plain(), "linux"), "-cpu")[0])
        self.assertEqual(option(argv_of(plain(), "win32", WQD, WMD), "-cpu"),
                         ["Penryn,vendor=GenuineIntel"])

    def test_smp_sockets(self):
        self.assertEqual([model.smp_option(n) for n in model.SMP_CHOICES],
                         ["1", "2,sockets=2,cores=1,threads=1", "4,sockets=2,cores=2,threads=1",
                          "8,sockets=2,cores=4,threads=1"])

    def test_smp_and_ram(self):
        argv = argv_of(plain(smp=4, ram_mb=4096))
        self.assertEqual((option(argv, "-smp"), option(argv, "-m")), (["4,sockets=2,cores=2,threads=1"], ["4096"]))

    def test_tablet_off_is_a_mouse(self):
        devices = option(argv_of(plain(usb_tablet=False)), "-device")
        self.assertIn("usb-mouse,bus=uhci.0", devices)
        self.assertNotIn("usb-tablet,bus=uhci.0,axis-inset=75", devices)

    def test_vnc(self):
        argv = argv_of(plain(vnc=":5"))
        self.assertEqual(option(argv, "-display"), ["none"])
        self.assertEqual(option(argv, "-vnc"), [":5"])

    def test_no_network(self):
        argv = argv_of(plain(network=Network("none")))
        self.assertEqual(option(argv, "-nic"), ["none"])
        self.assertEqual(option(argv, "-netdev"), [])

    def test_network_backends(self):
        def nd(mode, **kw):
            return option(argv_of(plain(network=Network(mode, "52:54:00:aa:bb:cc", **kw))),
                          "-netdev")
        self.assertEqual(nd("vmnet-shared"), ["vmnet-shared,id=n0"])
        self.assertEqual(nd("vmnet-host"), ["vmnet-host,id=n0"])
        self.assertEqual(nd("vmnet-bridged", ifname="en0"), ["vmnet-bridged,id=n0,ifname=en0"])
        self.assertEqual(nd("tap", ifname="tap0"), ["tap,id=n0,ifname=tap0"])
        fwd = [HostFwd("tcp", "8022", "22"), HostFwd("udp", "5353", "53"), HostFwd()]
        self.assertEqual(nd("user", hostfwd=fwd),
                         ["user,id=n0,hostfwd=tcp::8022-:22,hostfwd=udp::5353-:53"])
        argv = argv_of(plain(network=Network("user", "52:54:00:aa:bb:cc")))
        self.assertIn("e1000-82545em,netdev=n0,mac=52:54:00:aa:bb:cc", option(argv, "-device"))

    def test_serial_log_off_by_default(self):
        self.assertEqual(option(argv_of(plain()), "-serial"), [])
        self.assertEqual(option(argv_of(plain(serial_log=True)), "-serial"),
                         [f"file:{MD}/serial.log"])

    def test_rtc_and_extra_args_come_last(self):
        argv = argv_of(plain(rtc_base="localtime", extra_args="-d guest_errors"))
        self.assertEqual(argv[-4:], ["-rtc", "base=localtime", "-d", "guest_errors"])

    def test_empty_slots_leave_no_trace(self):
        argv = argv_of(plain(drives=[None, None, Drive("disk", "/d.img"), None, None]))
        self.assertEqual(option(argv, "-drive")[-1], "id=sata3,if=none,format=raw,file=/d.img")
        self.assertIn("ide-hd,bus=ide.3,drive=sata3", option(argv, "-device"))
        self.assertFalse(any("sata1" in t or "sata2" in t for t in argv))

    def test_file_names_with_commas_are_escaped(self):
        argv = argv_of(plain(drives=[Drive("disk", "/a,b.img"), None, None, None, None]))
        self.assertIn("file=/a,,b.img", option(argv, "-drive")[-1])

    def test_all_five_ports(self):
        m = plain(drives=[Drive("disk", f"/d{i}.img") for i in range(5)])
        devices = [d for d in option(argv_of(m), "-device") if d.startswith("ide-hd")]
        self.assertEqual(devices, [f"ide-hd,bus=ide.{n},drive={'esp' if n == 0 else f'sata{n}'}"
                                   for n in range(6)])

    def test_the_order_of_the_options(self):
        flags = [g[0] for g in pairs(argv_of(default_with_two_drives()))]
        want = ["-L", "-name", "-M", "-accel", "-m", "-smp", "-global", "-global", "-cpu",
                "-drive", "-drive", "-smbios", "-device", "-vga", "-display", "-drive", "-device"]
        self.assertEqual(flags[:len(want)], want)


class Sudo(unittest.TestCase):

    def test_vmnet_needs_sudo_and_gives_the_nvram_back(self):
        m = plain(network=Network("vmnet-shared"))
        text = command.launcher_text(m, QD, MD, "darwin", key_file=KEY)
        self.assertIn(f"sudo {QD}/qemu-system-x86_64 \\", text)
        self.assertIn("OVMF_VARS.fd serial.log", text)
        self.assertLess(text.index("OSK="), text.index("sudo -v"))

    def test_plain_machine_has_no_sudo(self):
        self.assertNotIn("sudo", command.launcher_text(plain(), QD, MD, "darwin"))


class WritingTheLauncher(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.install = support.make_install(Path(self.td.name) / "install")
        self.md = Path(self.td.name) / "Machines" / "Leopard"

    def tearDown(self):
        self.td.cleanup()

    def write(self, m=None, platform="darwin"):
        return command.write_launcher(m or plain(), str(self.install), str(self.md), platform,
                                      key_file=str(self.install / "OSK-Key.txt"))

    def test_files_written(self):
        path, argv = self.write()
        self.assertEqual(path, self.md / "run.command")
        for f in ("run.command", "OVMF_VARS.fd", "esp.img", "esp/EFI/OC/config.plist",
                  "esp/EFI/BOOT/BOOTx64.efi", "esp/EFI/BOOT/.contentVisibility"):
            self.assertTrue((self.md / f).is_file(), f)
        if sys.platform != "win32":
            self.assertTrue((self.md / "run.command").stat().st_mode & 0o100)
        self.assertEqual((self.md / "OVMF_VARS.fd").read_bytes(),
                         (self.install / "pc-bios" / "edk2-i386-vars.fd").read_bytes())

    def test_no_file_holds_the_key(self):
        self.write()
        self.write(platform="win32")
        for f in self.md.rglob("*"):
            if f.is_file():
                self.assertNotIn(support.DUMMY_KEY.encode(), f.read_bytes(), f)

    def test_the_variable_store_is_never_overwritten(self):
        self.write()
        (self.md / "OVMF_VARS.fd").write_bytes(b"the machine's nvram")
        self.write()
        self.assertEqual((self.md / "OVMF_VARS.fd").read_bytes(), b"the machine's nvram")

    def test_a_missing_variable_store_is_copied_again(self):
        self.write()
        (self.md / "OVMF_VARS.fd").unlink()
        self.write()
        self.assertTrue((self.md / "OVMF_VARS.fd").is_file())

    def test_the_esp_is_regenerated_from_the_record(self):
        import plistlib
        self.write(plain(show_picker=False))
        before = (self.md / "esp.img").read_bytes()
        self.write(plain(show_picker=True))
        cfg = plistlib.loads((self.md / "esp/EFI/OC/config.plist").read_bytes())
        self.assertTrue(cfg["Misc"]["Boot"]["ShowPicker"])
        self.assertNotEqual(before, (self.md / "esp.img").read_bytes())

    def test_windows_writes_a_bat(self):
        path, _ = self.write(platform="win32")
        self.assertEqual(path.name, "run.bat")
        self.assertIn(b"\r\n", path.read_bytes())

    def test_a_missing_template_is_an_oserror(self):
        (self.install / "pc-bios" / "edk2-i386-vars.fd").unlink()
        with self.assertRaises(OSError):
            self.write()


class RuntimeVariable(unittest.TestCase):
    """The run-time reference in the renderers, on both platforms."""

    ARGV = ["/q/qemu", "-device", "isa-applesmc,osk=" + paths.runtime_ref("OSK"), "-vga", "std"]

    def test_shell(self):
        text = paths.render_shell(self.ARGV, "h", (), False, 0, (("OSK", "/k/my key.txt"),))
        self.assertIn("OSK=\"$(cat '/k/my key.txt')\"", text)
        self.assertIn('-device "isa-applesmc,osk=$OSK" \\', text)
        self.assertLess(text.index("OSK="), text.index("/q/qemu"))

    @support.needs_bash
    def test_shell_path_with_a_single_quote(self):
        text = paths.render_shell(self.ARGV, "h", (), False, 0, (("OSK", "/k/it's.txt"),))
        r = subprocess.run([support.BASH, "-n"], input=text, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @support.needs_bash
    def test_the_shell_passes_the_value_on_as_one_word(self):
        keyfile = Path(tempfile.mkdtemp()) / "k.txt"
        key = 'a b$c`d\\e"f&g;h*i(j)k'
        keyfile.write_text(key + "\n")
        argv = ["/usr/bin/printf", "%s\\n", "x=" + paths.runtime_ref("OSK")]
        text = paths.render_shell(argv, "h", (), False, 0, (("OSK", str(keyfile)),))
        out = subprocess.run([support.BASH, "-c", text], capture_output=True, text=True)
        self.assertEqual(out.stdout, "x=" + key + "\n", out.stderr)

    def test_no_runtime_variable_no_line(self):
        text = paths.render_shell(["/q/qemu", "-vga", "std"], "h")
        self.assertNotIn("OSK", text)

    def test_bat(self):
        text = paths.render_bat(self.ARGV, "h", 0, "t", (("OSK", r"C:\k k\OSK.txt"),))
        self.assertIn(r'set /p OSK=<"C:\k k\OSK.txt"', text)
        self.assertIn('-device "isa-applesmc,osk=%OSK%" ^', text)
        self.assertLess(text.index("set /p"), text.index("/q/qemu"))

    def test_bat_doubles_percent_signs_around_it(self):
        argv = ["q", "-x", "a%b," + paths.runtime_ref("OSK") + "%c"]
        text = paths.render_bat(argv, "h", 0, "t", (("OSK", "k.txt"),))
        self.assertIn('-x "a%%b,%OSK%%%c"', text)

    def test_extra_arguments_are_not_reference_expanded(self):
        argv = ["/q/qemu", "-device", "isa-applesmc,osk={{OSK}}", "-name", "{{OSK}}"]
        text = paths.render_shell(argv, "h", (), False, 1, (("OSK", "/k"),))
        self.assertNotIn("$OSK\n", text.split("-name")[1])


class SmcKeyFile(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = Path(self.td.name) / "OSK-Key.txt"

    def tearDown(self):
        self.td.cleanup()

    def problem(self, text: str | bytes | None):
        if text is not None:
            if isinstance(text, bytes):
                self.p.write_bytes(text)
            else:
                self.p.write_text(text, encoding="utf-8")
        return model.smc_key_problem(self.p)

    def test_good_files(self):
        for text in ("x" * 64, "x" * 64 + "\n", "(c)" + "y" * 61 + "\n", " " + "z" * 63):
            self.assertIsNone(self.problem(text), repr(text))

    def test_bad_files(self):
        for text in ("", "\n", "x" * 63, "x" * 65, "x" * 64 + "\n\n", "x" * 32 + "\n" + "x" * 31,
                     "x" * 63 + "\t", "x" * 63 + '"'):
            self.assertIsNotNone(self.problem(text), repr(text))
        self.assertIsNotNone(self.problem(b"\xff" * 64))

    def test_missing_and_unset(self):
        self.assertIn("not there", model.smc_key_problem(self.p))
        self.assertIn("No SMC key file", model.smc_key_problem(""))

    def test_the_message_does_not_repeat_the_key(self):
        self.assertNotIn("q" * 10, self.problem("q" * 63 + "\n"))

    def test_start_blockers(self):
        self.assertEqual(model.start_blockers(plain(), self.p)[0][:12], "The SMC key ")
        self.p.write_text("x" * 64)
        self.assertEqual(model.start_blockers(plain(), self.p), [])

    def test_the_x1900_needs_its_rom_file(self):
        self.p.write_text("x" * 64)
        m = plain(gpu="x1900")
        got = model.start_blockers(m, self.p, self.td.name)
        self.assertEqual(len(got), 1)
        self.assertIn("ati-r580-gop.rom", got[0])
        self.assertEqual(model.start_blockers(plain(), self.p, self.td.name), [])
        (Path(self.td.name) / "ati-r580-gop.rom").write_bytes(b"rom")
        self.assertEqual(model.start_blockers(m, self.p, self.td.name), [])

    def test_settings_hold_the_path_only(self):
        s = paths.Settings(last_machine="L", smc_key_file=str(self.p))
        f = Path(self.td.name) / "settings.json"
        s.save(f)
        self.assertEqual(json.loads(f.read_text()),
                         {"last_machine": "L", "smc_key_file": str(self.p)})
        self.assertEqual(paths.Settings.load(f), s)
        self.assertEqual(paths.Settings().key_file, str(paths.default_smc_key_file()))
        self.assertEqual(paths.Settings.load(Path(self.td.name) / "none.json").smc_key_file, "")


class Record(unittest.TestCase):

    def test_gpu_and_verbose_round_trip(self):
        m = Machine.from_json(plain(gpu="x1900", verbose=True).to_json())
        self.assertEqual((m.gpu, m.verbose), ("x1900", True))

    def test_old_records_get_the_standard_card_and_quiet_boot(self):
        for rec in ({"name": "old"}, {"name": "old", "gpu": "", "verbose": None}):
            m = Machine.from_dict(rec)
            self.assertEqual((m.gpu, m.verbose), ("std", False))
        m = Machine.load(FIXTURES / "x86-minimal.json")
        self.assertEqual((m.gpu, m.verbose), ("std", False))

    def test_labels(self):
        self.assertEqual(model.gpu_label("std"), "Standard VGA")
        self.assertEqual(model.gpu_label("x1900"), "ATI Radeon X1900 XT")
        for g in model.GPUS:
            self.assertEqual(model.gpu_by_label(model.gpu_label(g)), g)

    def test_defaults(self):
        m = model.new_machine("t")
        self.assertEqual((m.mac_model, m.os, m.smp, m.ram_mb, m.accel, m.resolution),
                         ("MacPro2,1", "10.5", 1, 2048, "tcg", "1440x900"))
        self.assertEqual((m.show_picker, m.boot_args, m.serial_log, m.usb_tablet, m.usb_audio),
                         (False, "", False, True, False))
        self.assertEqual((m.gpu, m.verbose), ("std", False))
        self.assertEqual(m.network.mac, "52:54:00:12:34:56")
        self.assertEqual(len(m.drives), 5)
        self.assertEqual(m.drives, [None] * 5)

    def test_a_new_machine_has_its_own_stable_uuid(self):
        a, b = model.new_machine("a"), model.new_machine("b")
        self.assertNotEqual(a.uuid, b.uuid)
        self.assertEqual(Machine.from_json(a.to_json()).uuid, a.uuid)
        self.assertEqual(a.copy().uuid, a.uuid)

    def test_a_record_without_uuid_gets_a_stable_one(self):
        a = Machine.from_dict({"name": "old"})
        self.assertEqual(a.uuid, Machine.from_dict({"name": "old"}).uuid)

    def test_round_trip(self):
        m = Machine.load(FIXTURES / "x86-leopard.json")
        self.assertEqual(Machine.from_json(m.to_json()), m)
        self.assertEqual(m.to_dict()["schema"], 1)

    def test_no_ppc_fields(self):
        keys = set(model.new_machine("t").to_dict())
        for gone in ("prom_env", "bios", "decr_cap_ms", "cd_audio", "audio", "boot_slot"):
            self.assertNotIn(gone, keys)
        self.assertNotIn("volume", model.new_machine("t").to_dict()["share"])

    def test_the_key_is_not_a_field(self):
        d = json.dumps(model.new_machine("t").to_dict()).lower()
        self.assertNotIn("osk", d)

    def test_the_os_selects_the_kernel_arch(self):
        self.assertEqual(model.new_machine("t").kernel_arch, "i386")


class Validation(unittest.TestCase):

    def check(self, m, platform="darwin"):
        return model.validate(m, None, platform, check_files=False)

    def test_a_default_machine_is_clean(self):
        self.assertEqual(self.check(model.new_machine("t")), ([], []))

    def test_choices_are_enforced(self):
        for kw in ({"mac_model": "iMac"}, {"os": "10.4"}, {"smp": 3}, {"ram_mb": 5000},
                   {"resolution": "800x600"}, {"accel": "kvm"}):
            errors, _ = self.check(plain(**kw))
            self.assertTrue(errors, kw)

    def test_verbose_boot_is_accepted_in_the_extra_arguments(self):
        for text in ("", "-x", "-v", "cpus=1 -v", "-verbose", "debug=-v"):
            errors, _ = self.check(plain(boot_args=text))
            self.assertEqual(errors, [], text)

    def test_the_graphics_card_is_enforced(self):
        errors, _ = self.check(plain(gpu="voodoo"))
        self.assertTrue(errors)
        for gpu in model.GPUS:
            self.assertEqual(self.check(plain(gpu=gpu))[0], [])

    def test_hvf_off_a_mac_warns(self):
        _, w = self.check(plain(accel="whpx"), "darwin")
        self.assertTrue(any("whpx" in x for x in w))
        _, w = self.check(plain(accel="whpx", display="sdl"), "win32")
        self.assertEqual(w, [])

    def test_five_drives(self):
        errors, _ = self.check(plain(drives=[None] * 4))
        self.assertTrue(errors)


class Library(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.lib = model.Library(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_duplicate_gets_a_new_uuid_and_keeps_the_nvram(self):
        m = model.new_machine("a")
        self.lib.save(m)
        (self.lib.folder("a") / "OVMF_VARS.fd").write_bytes(b"nv")
        b = self.lib.duplicate("a", "b")
        self.assertNotEqual(b.uuid, m.uuid)
        self.assertEqual((self.lib.folder("b") / "OVMF_VARS.fd").read_bytes(), b"nv")

    def test_delete_removes_what_the_program_made_and_keeps_images(self):
        self.lib.save(model.new_machine("a"))
        f = self.lib.folder("a")
        (f / "esp" / "EFI" / "OC").mkdir(parents=True)
        (f / "esp" / "EFI" / "OC" / "config.plist").write_bytes(b"x")
        for n in ("esp.img", "OVMF_VARS.fd", "run.command", "serial.log", "disk.img"):
            (f / n).write_bytes(b"x")
        gone, kept = self.lib.delete_preview("a")
        self.assertEqual(kept, ["disk.img"])
        self.assertIn("esp/EFI/OC/config.plist", gone)
        res = self.lib.delete("a")
        self.assertEqual(res.kept, ["disk.img"])
        self.assertFalse((f / "esp").exists())

    def test_reset_removes_only_the_variable_store(self):
        self.lib.save(model.new_machine("a"))
        f = self.lib.folder("a")
        (f / "OVMF_VARS.fd").write_bytes(b"nv")
        self.assertEqual(self.lib.clear_saved_settings("a"), ["OVMF_VARS.fd"])
        self.assertTrue((f / "machine.json").is_file())


class StartUp(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        paths.use_install_dir(self.td.name)

    def tearDown(self):
        paths.use_install_dir(None)
        self.td.cleanup()

    def test_missing_qemu(self):
        self.assertIn("qemu-system-x86_64", paths.startup_problem("darwin"))
        self.assertIn("qemu-system-x86_64.exe", paths.startup_problem("win32"))

    def test_missing_opencore_and_firmware_are_listed(self):
        (Path(self.td.name) / paths.qemu_binary_name()).write_text("")
        text = paths.startup_problem()
        self.assertIn("pc-bios/edk2-x86_64-code.fd", text)
        self.assertIn("pc-bios/edk2-i386-vars.fd", text)
        self.assertIn("OpenCore/X64/EFI/OC/OpenCore.efi", text)
        self.assertIn("OpenCore/Docs/Sample.plist", text)

    def test_a_complete_install_has_no_problem(self):
        support.make_install(self.td.name)
        self.assertIsNone(paths.startup_problem())
        self.assertTrue((Path(self.td.name) / "Machines").is_dir())


if __name__ == "__main__":
    unittest.main()
