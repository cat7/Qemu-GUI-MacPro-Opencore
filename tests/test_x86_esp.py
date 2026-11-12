"""The OpenCore folder generator: the generated config.plist is loaded with
plistlib and checked; the OpenCore release is a small fake tree."""

from __future__ import annotations

import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import support  # noqa: E402
from qemugui import fatimg, paths  # noqa: E402
from qemugui import x86_esp as esp  # noqa: E402
from qemugui import x86_model as model  # noqa: E402
from qemugui.x86_model import Machine, Network  # noqa: E402

UUID = "11111111-2222-3333-4444-555555555555"
APPLE = "7C436110-AB2A-4BBB-A880-FE41995C9F82"


def machine(**kw) -> Machine:
    kw.setdefault("name", "t")
    kw.setdefault("uuid", UUID)
    kw.setdefault("builtin_audio", False)
    return Machine(**kw)


class Case(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.install = support.make_install(Path(self.td.name) / "install")
        self.out = Path(self.td.name) / "esp"

    def tearDown(self):
        self.td.cleanup()

    def build(self, m: Machine | None = None) -> dict:
        plist = esp.build_esp(m or machine(), self.install, self.out)
        self.assertEqual(plist, self.out / "EFI/OC/config.plist")
        return plistlib.loads(plist.read_bytes())


class Tree(Case):

    def test_files(self):
        self.build()
        got = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file())
        want = sorted(["EFI/BOOT/BOOTx64.efi", "EFI/BOOT/.contentVisibility",
                       "EFI/OC/OpenCore.efi", "EFI/OC/config.plist",
                       "EFI/OC/Tools/OpenShell.efi"]
                      + [f"EFI/OC/Drivers/{d}" for d in paths.OPENCORE_DRIVERS])
        self.assertEqual(got, want)
        for d in ("ACPI", "Kexts", "Resources"):
            self.assertTrue((self.out / "EFI/OC" / d).is_dir(), d)

    def test_efi_files_are_the_releases(self):
        self.build()
        self.assertEqual((self.out / "EFI/BOOT/BOOTx64.efi").read_bytes(),
                         (self.install / "OpenCore" / paths.OPENCORE_BOOT_EFI).read_bytes())
        self.assertEqual((self.out / "EFI/OC/Drivers/OpenRuntime.efi").read_bytes(),
                         b"MZOpenRuntime.efi")

    def test_content_visibility_is_always_disabled(self):
        for picker in (False, True):
            self.build(machine(show_picker=picker))
            self.assertEqual((self.out / "EFI/BOOT/.contentVisibility").read_text(), "Disabled")

    def test_an_old_folder_is_replaced(self):
        (self.out / "EFI").mkdir(parents=True)
        (self.out / "EFI/stale.txt").write_text("old")
        self.build()
        self.assertFalse((self.out / "EFI/stale.txt").exists())

    def test_a_missing_release_file_is_a_plain_error(self):
        (self.install / "OpenCore" / paths.OPENCORE_MAIN_EFI).unlink()
        with self.assertRaises(esp.EspError) as cm:
            esp.build_esp(machine(), self.install, self.out)
        self.assertIn("OpenCore.efi", str(cm.exception))

    def test_a_broken_sample_plist_is_a_plain_error(self):
        (self.install / "OpenCore" / paths.OPENCORE_SAMPLE_PLIST).write_bytes(b"junk")
        with self.assertRaises(esp.EspError):
            esp.build_esp(machine(), self.install, self.out)

    def test_the_sample_comments_are_dropped(self):
        self.assertFalse([k for k in self.build() if k.startswith("#")])


class Settings(Case):

    def test_platform_info(self):
        gen = self.build(machine(mac_model="MacPro3,1",
                                 network=Network("user", "52:54:00:AA:BB:CC")))["PlatformInfo"]
        self.assertTrue(gen["Automatic"])
        g = gen["Generic"]
        self.assertEqual(g["SystemProductName"], "MacPro3,1")
        self.assertEqual(g["SystemUUID"], UUID)
        self.assertEqual(g["ROM"], bytes.fromhex("525400AABBCC"))
        self.assertTrue(g["SpoofVendor"])

    def test_every_model(self):
        for mac in model.MAC_MODELS:
            cfg = self.build(machine(mac_model=mac))
            self.assertEqual(cfg["PlatformInfo"]["Generic"]["SystemProductName"], mac)

    def test_rom_falls_back_to_the_default_card_address(self):
        cfg = self.build(machine(network=Network("none", "junk")))
        self.assertEqual(cfg["PlatformInfo"]["Generic"]["ROM"], bytes.fromhex("525400123456"))

    def test_resolution(self):
        for res in model.RESOLUTIONS:
            cfg = self.build(machine(resolution=res))
            self.assertEqual(cfg["UEFI"]["Output"]["Resolution"], res)
        out = self.build()["UEFI"]["Output"]
        self.assertEqual((out["ProvideConsoleGop"], out["TextRenderer"], out["UgaPassThrough"],
                          out["InitialMode"]), (True, "BuiltinText", True, "Text"))

    def test_boot_args(self):
        def args(**kw):
            return self.build(machine(**kw))["NVRAM"]["Add"][APPLE]["boot-args"]
        self.assertEqual(args(), "keepsyms=1 debug=0x100")
        self.assertEqual(args(boot_args="cpus=1  -x"), "keepsyms=1 debug=0x100 cpus=1 -x")
        self.assertNotIn("slto_us", args())

    def test_verbose_and_serial_boot_args(self):
        def args(**kw):
            return self.build(machine(**kw))["NVRAM"]["Add"][APPLE]["boot-args"]
        self.assertEqual(args(verbose=True), "keepsyms=1 debug=0x100 -v")
        self.assertEqual(args(serial_log=True), "keepsyms=1 debug=0x108 serial=3")
        self.assertEqual(args(verbose=True, serial_log=True),
                         "keepsyms=1 debug=0x108 serial=3 -v")
        self.assertEqual(args(verbose=True, boot_args="cpus=1"),
                         "keepsyms=1 debug=0x100 -v cpus=1")
        self.assertEqual(args(verbose=True, serial_log=True, boot_args="-x"),
                         "keepsyms=1 debug=0x108 serial=3 -v -x")

    def test_a_typed_dash_v_is_kept_once(self):
        def args(**kw):
            return self.build(machine(**kw))["NVRAM"]["Add"][APPLE]["boot-args"]
        self.assertEqual(args(boot_args="-v"), "keepsyms=1 debug=0x100 -v")
        self.assertEqual(args(verbose=True, boot_args="cpus=1 -v"),
                         "keepsyms=1 debug=0x100 cpus=1 -v")
        self.assertEqual(args(verbose=True, boot_args="-v").split().count("-v"), 1)

    def test_the_standard_card_adds_no_device_properties(self):
        d = self.build(machine(gpu="std"))["DeviceProperties"]
        self.assertEqual((d["Add"], d["Delete"]), ({}, {}))

    def test_the_x1900_device_properties(self):
        cfg = self.build(machine(gpu="x1900"))
        add = cfg["DeviceProperties"]["Add"]
        self.assertEqual(list(add), ["PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)"])
        p = add["PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)"]
        fb = "ATY,Alopias"
        want = {
            "name": fb + "Parent", "device_type": fb + "Parent",
            "model": "ATI Radeon X1900 XT",
            "VRAM,totalsize": bytes.fromhex("00000010"),
            "ATY,Copyright": b"Copyright ATI Technologies Inc. 2005",
            "ATY,EFIVersion": b"01.00.068",
            "ATY,Rom#": b"113-A52027-202",
            "ATY,Card#": b"109-A52027-00",
            "ATY,PlatformInfo": bytes(128),
        }
        for i in (0, 1):
            want.update({f"@{i},name": fb, f"@{i},compatible": fb, f"@{i},device_type": "display"})
        self.assertEqual(p, want)
        for k, v in want.items():
            self.assertIs(type(p[k]), type(v), k)

    def test_the_x1900_fixes_the_boot_screen_size(self):
        for res in model.RESOLUTIONS:
            out = self.build(machine(gpu="x1900", resolution=res))["UEFI"]["Output"]
            self.assertEqual(out["Resolution"], "1024x768", res)
        for res in model.RESOLUTIONS:
            out = self.build(machine(gpu="std", resolution=res))["UEFI"]["Output"]
            self.assertEqual(out["Resolution"], res)

    def test_nvram_section(self):
        nv = self.build()["NVRAM"]
        add = nv["Add"][APPLE]
        self.assertEqual(add["csr-active-config"], b"\x00\x00\x00\x00")
        self.assertEqual(add["prev-lang:kbd"], b"en:0")
        self.assertEqual(add["run-efi-updater"], "No")
        self.assertEqual(nv["Delete"][APPLE], ["boot-args", "csr-active-config", "prev-lang:kbd"])
        self.assertTrue(nv["WriteFlash"])

    def test_picker(self):
        boot = self.build(machine(show_picker=True))["Misc"]["Boot"]
        self.assertEqual((boot["ShowPicker"], boot["HideAuxiliary"], boot["Timeout"],
                          boot["PickerMode"]), (True, False, 5, "Builtin"))
        boot = self.build(machine(show_picker=False))["Misc"]["Boot"]
        self.assertEqual((boot["ShowPicker"], boot["HideAuxiliary"], boot["Timeout"]),
                         (False, True, 0))
        self.assertTrue(boot["PollAppleHotKeys"])

    def test_kernel(self):
        k = self.build()["Kernel"]
        self.assertEqual(k["Scheme"]["KernelArch"], "i386")
        self.assertEqual(k["Scheme"]["KernelCache"], "Mkext")
        self.assertTrue(k["Quirks"]["ProvideCurrentCpuInfo"])
        self.assertTrue(k["Quirks"]["DisableLinkeditJettison"])
        self.assertTrue(k["Emulate"]["DummyPowerManagement"])
        for key in ("Block", "Patch", "Force"):
            self.assertEqual(k[key], [])

    def test_booter(self):
        b = self.build()["Booter"]
        self.assertEqual((b["MmioWhitelist"], b["Patch"]), ([], []))
        q = b["Quirks"]
        for key in ("AvoidRuntimeDefrag", "EnableSafeModeSlide", "EnableWriteUnprotector",
                    "ProvideCustomSlide", "RebuildAppleMemoryMap", "AllowRelocationBlock",
                    "ClearTaskSwitchBit"):
            self.assertTrue(q[key], key)
        for key in ("SetupVirtualMap", "DevirtualiseMmio", "ProtectUefiServices"):
            self.assertFalse(q[key], key)

    def test_acpi_rtc_patch(self):
        acpi = self.build()["ACPI"]
        self.assertEqual((acpi["Add"], acpi["Delete"]), ([], []))
        (patch,) = acpi["Patch"]
        self.assertEqual(patch["Base"], "\\_SB.PCI0.SF8.RTC")
        self.assertEqual(patch["Find"], bytes.fromhex("4701700070000108"))
        self.assertEqual(patch["Replace"], bytes.fromhex("4701700070000102"))
        self.assertEqual(patch["TableSignature"], b"DSDT")
        self.assertTrue(patch["Enabled"])

    def add_chime_files(self):
        oc = self.install / paths.OPENCORE_DIR_NAME
        (oc / "X64/EFI/OC/Drivers" / paths.OPENCORE_AUDIO_DRIVER).write_bytes(b"driver")
        (oc / paths.OPENCORE_CHIME).parent.mkdir(parents=True, exist_ok=True)
        (oc / paths.OPENCORE_CHIME).write_bytes(b"chime")

    def test_startup_chime(self):
        self.add_chime_files()
        cfg = self.build(machine(builtin_audio=True))
        u = cfg["UEFI"]
        self.assertEqual([d["Path"] for d in u["Drivers"]],
                         list(paths.OPENCORE_DRIVERS) + ["AudioDxe.efi"])
        audio = u["Audio"]
        self.assertTrue(audio["AudioSupport"])
        self.assertEqual(audio["AudioDevice"], "PciRoot(0x0)/Pci(0x1b,0x0)")
        self.assertEqual((audio["AudioCodec"], audio["AudioOutMask"]), (0, 1))
        self.assertEqual(audio["PlayChime"], "Enabled")
        nv = cfg["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]
        self.assertEqual(nv["SystemAudioVolumeDB"], b"\xf1")
        self.assertEqual((self.out / "EFI/OC/Drivers/AudioDxe.efi").read_bytes(), b"driver")
        self.assertEqual((self.out / "EFI/OC/Resources/Audio/OCEFIAudio_VoiceOver_Boot.mp3")
                         .read_bytes(), b"chime")

    def test_no_startup_chime(self):
        def off(cfg):
            self.assertFalse(cfg["UEFI"]["Audio"]["AudioSupport"])
            self.assertEqual([d["Path"] for d in cfg["UEFI"]["Drivers"]],
                             list(paths.OPENCORE_DRIVERS))
            self.assertNotIn("SystemAudioVolumeDB",
                             cfg["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"])
            self.assertFalse((self.out / "EFI/OC/Resources/Audio").exists())
        off(self.build(machine(builtin_audio=True)))
        self.add_chime_files()
        off(self.build(machine(builtin_audio=True, startup_chime=False)))
        off(self.build(machine(builtin_audio=False)))
        (self.install / paths.OPENCORE_DIR_NAME / paths.OPENCORE_CHIME).unlink()
        off(self.build(machine(builtin_audio=True)))

    def test_startup_chime_round_trip_and_default(self):
        self.assertTrue(Machine.from_dict({"name": "old"}).startup_chime)
        m = machine(startup_chime=False)
        self.assertFalse(Machine.from_json(m.to_json()).startup_chime)

    def test_builtin_audio_device_properties_and_acpi_patch(self):
        cfg = self.build(machine(builtin_audio=True))
        add = cfg["DeviceProperties"]["Add"]
        self.assertEqual(add, {"PciRoot(0x0)/Pci(0x1b,0x0)": {
            "layout-id": bytes.fromhex("0c000000"),
            "PinConfigurations": bytes.fromhex(
                "f000004050410101f0000040f0000040407021011031810130011390f0000040f0000040"
                "f000004060e1450120e1c501")}})
        self.assertIs(type(add["PciRoot(0x0)/Pci(0x1b,0x0)"]["layout-id"]), bytes)
        rtc, hdef = cfg["ACPI"]["Patch"]
        self.assertEqual(rtc["Base"], "\\_SB.PCI0.SF8.RTC")
        want = dict(Base="", BaseSkip=0, Comment="SD8 to HDEF", Count=0, Enabled=True,
                    Find=b"SD8_", Limit=0, Mask=b"", OemTableId=bytes(8), Replace=b"HDEF",
                    ReplaceMask=b"", Skip=0, TableLength=0, TableSignature=b"DSDT")
        self.assertEqual(hdef, want)

    def test_no_builtin_audio_properties_or_patch_when_off(self):
        cfg = self.build(machine(builtin_audio=False))
        self.assertEqual(cfg["DeviceProperties"]["Add"], {})
        self.assertEqual(len(cfg["ACPI"]["Patch"]), 1)

    def test_builtin_audio_from_extra_args_adds_nothing(self):
        cfg = self.build(machine(builtin_audio=True, extra_args="-device hda-alc885"))
        self.assertEqual(cfg["DeviceProperties"]["Add"], {})
        self.assertEqual(len(cfg["ACPI"]["Patch"]), 1)

    def test_builtin_audio_and_the_x1900_coexist(self):
        cfg = self.build(machine(gpu="x1900", builtin_audio=True))
        add = cfg["DeviceProperties"]["Add"]
        self.assertEqual(list(add), ["PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)",
                                     "PciRoot(0x0)/Pci(0x1b,0x0)"])
        self.assertEqual(add["PciRoot(0x0)/Pci(0x1,0x0)/Pci(0x0,0x0)"], esp.x1900_properties())

    def test_uefi(self):
        u = self.build()["UEFI"]
        self.assertEqual([d["Path"] for d in u["Drivers"]], list(paths.OPENCORE_DRIVERS))
        self.assertTrue(all(d["Enabled"] for d in u["Drivers"]))
        self.assertTrue(u["Quirks"]["RequestBootVarRouting"])

    def test_misc(self):
        m = self.build()["Misc"]
        self.assertEqual(m["Entries"], [])
        (tool,) = m["Tools"]
        self.assertEqual((tool["Path"], tool["Enabled"], tool["Auxiliary"]),
                         ("OpenShell.efi", True, True))
        self.assertEqual(m["Debug"]["Target"], 0x09)
        self.assertEqual(m["Debug"]["DisplayLevel"], 0x80000042)
        self.assertTrue(m["Serial"]["Init"])
        sec = m["Security"]
        self.assertEqual((sec["SecureBootModel"], sec["Vault"], sec["ScanPolicy"]),
                         ("Disabled", "Optional", 0))

    def test_device_properties_are_emptied(self):
        d = self.build()["DeviceProperties"]
        self.assertEqual((d["Add"], d["Delete"]), ({}, {}))

    def test_the_serial_number_is_not_random(self):
        a = self.build()["PlatformInfo"]["Generic"]
        b = self.build()["PlatformInfo"]["Generic"]
        self.assertEqual(a, b)

    def test_no_key_anywhere(self):
        self.build()
        for f in self.out.rglob("*"):
            if f.is_file():
                self.assertNotIn(b"osk", f.read_bytes().lower(), f)


class Kexts(Case):

    def kext(self, name, executable=None, info=True):
        k = self.install / "Kexts" / name
        (k / "Contents").mkdir(parents=True)
        if info:
            (k / "Contents/Info.plist").write_bytes(plistlib.dumps(
                {"CFBundleExecutable": executable} if executable else {}))
        if executable:
            (k / "Contents/MacOS").mkdir()
            (k / "Contents/MacOS" / executable).write_bytes(b"bin")
        return k

    def test_no_kexts_folder(self):
        self.assertEqual(self.build()["Kernel"]["Add"], [])
        self.assertEqual(list((self.out / "EFI/OC/Kexts").iterdir()), [])

    def test_kexts_are_copied_and_listed(self):
        self.kext("B.kext", "BBin")
        self.kext("A.kext")
        (self.install / "Kexts" / "readme.txt").write_text("not a kext")
        (self.install / "Kexts" / "NotAKext").mkdir()
        add = self.build()["Kernel"]["Add"]
        self.assertEqual([a["BundlePath"] for a in add], ["A.kext", "B.kext"])
        a, b = add
        self.assertEqual(a["ExecutablePath"], "")
        self.assertEqual(b["ExecutablePath"], "Contents/MacOS/BBin")
        for entry in add:
            self.assertEqual((entry["PlistPath"], entry["Arch"], entry["Enabled"]),
                             ("Contents/Info.plist", "Any", True))
        self.assertTrue((self.out / "EFI/OC/Kexts/B.kext/Contents/MacOS/BBin").is_file())
        self.assertTrue((self.out / "EFI/OC/Kexts/A.kext/Contents/Info.plist").is_file())
        self.assertFalse((self.out / "EFI/OC/Kexts/NotAKext").exists())

    def test_executable_without_info_plist_is_the_only_file(self):
        k = self.kext("C.kext", "CBin", info=False)
        self.assertEqual(esp.kext_executable(k), "Contents/MacOS/CBin")

    def test_kexts_end_up_in_the_image(self):
        self.kext("B.kext", "BBin")
        m = machine()
        md = Path(self.td.name) / "md"
        md.mkdir()
        esp.write_esp(m, self.install, md)
        sys.path.insert(0, str(HERE))
        from test_fatimg import Fat16
        tree = Fat16((md / "esp.img").read_bytes()).tree()
        self.assertEqual(tree["EFI/OC/Kexts/B.kext/Contents/MacOS/BBin"], b"bin")


class Image(Case):

    def test_write_esp_makes_folder_and_image(self):
        from test_fatimg import Fat16
        md = Path(self.td.name) / "md"
        md.mkdir()
        img = esp.write_esp(machine(show_picker=True), self.install, md)
        self.assertEqual(img, md / "esp.img")
        tree = Fat16(img.read_bytes()).tree()
        self.assertEqual(tree["EFI/BOOT/.contentVisibility"], b"Disabled")
        cfg = plistlib.loads(tree["EFI/OC/config.plist"])
        self.assertTrue(cfg["Misc"]["Boot"]["ShowPicker"])
        self.assertEqual(tree["EFI/OC/config.plist"], (md / "esp/EFI/OC/config.plist").read_bytes())

    def test_an_image_that_does_not_fit_is_a_plain_error(self):
        (self.install / "OpenCore" / paths.OPENCORE_MAIN_EFI).write_bytes(b"x" * (70 << 20))
        md = Path(self.td.name) / "md"
        md.mkdir()
        with self.assertRaises(esp.EspError) as cm:
            esp.write_esp(machine(), self.install, md)
        self.assertIn("cannot be made", str(cm.exception))
        self.assertIsInstance(cm.exception.__cause__, fatimg.FatError)


if __name__ == "__main__":
    unittest.main()
