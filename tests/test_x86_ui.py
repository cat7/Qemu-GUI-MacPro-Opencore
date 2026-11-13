"""Tk-backed tests for the editor and main window.

These build real but withdrawn Tk windows, so they are skipped where there
is no working tkinter. Real dialogs are blocked (see support.py).

Run:  python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import support  # noqa: E402
from qemugui import x86_model as model  # noqa: E402
from qemugui import paths  # noqa: E402
from qemugui.x86_model import Machine, Drive, Share  # noqa: E402


def _tk_available():
    try:
        import tkinter
        r = tkinter.Tk(); r.withdraw(); r.destroy(); return True
    except Exception:
        return False


class EditorCase(unittest.TestCase):
    """A withdrawn editor on a temp Machines folder."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.roots = []
        self.saved_platform = paths.HOST_PLATFORM

    def tearDown(self):
        paths.HOST_PLATFORM = self.saved_platform
        for r in self.roots:
            r.destroy()
        self.td.cleanup()

    def _editor(self, m: Machine, qemu_dir: str = "/q", is_new: bool = False):
        import tkinter as tk
        from qemugui.x86_ui_machine import MachineEditor
        root = tk.Tk(); root.withdraw()
        self.roots.append(root)
        ed = MachineEditor(root, m, model.Library(self.td.name), qemu_dir,
                           on_save=lambda *a: None, is_new=is_new)
        ed.withdraw()
        return ed


@unittest.skipUnless(_tk_available(), "no display")
class MachineTab(EditorCase):

    def test_defaults(self):
        m = self._editor(model.new_machine("t")).collect()
        self.assertEqual((m.mac_model, m.os, m.smp, m.ram_mb, m.accel, m.resolution),
                         ("MacPro2,1", "10.5", 1, 2048, "tcg", "1440x900"))
        self.assertFalse(m.show_picker)
        self.assertEqual(m.boot_args, "")
        self.assertFalse(m.serial_log)
        self.assertTrue(m.usb_tablet)
        self.assertFalse(m.usb_audio)

    def test_loads_and_collects(self):
        m = Machine.load(HERE / "fixtures" / "x86-leopard.json")
        got = self._editor(m).collect()
        self.assertEqual(got.to_dict(), m.to_dict())

    def test_comboboxes_offer_the_fixed_choices(self):
        ed = self._editor(Machine(name="t"))
        self.assertEqual(list(ed.model_var and ed.nb.winfo_children()[0].winfo_children()[3]
                              .cget("values")), list(model.MAC_MODELS))
        self.assertEqual(model.SMP_CHOICES, (1, 2, 4, 8))
        self.assertEqual(model.RAM_CHOICES, (1024, 2048, 3072, 4096))

    def test_the_uuid_survives_editing(self):
        m = model.new_machine("t")
        self.assertEqual(self._editor(m).collect().uuid, m.uuid)

    def test_no_ppc_widgets_are_left(self):
        ed = self._editor(Machine(name="t"))
        for name in ("bios_var", "gpu_model_var", "decr_cap_var", "boot_device_var",
                     "cd_audio_var", "audio_var", "share_volume", "boot_into_ofw_var"):
            self.assertFalse(hasattr(ed, name), name)


@unittest.skipUnless(_tk_available(), "no display")
class AccelerationFollowsTheHost(EditorCase):

    def labels(self, platform, arch):
        return model.accel_labels_for_host(platform, None, arch)

    def test_choices_per_host(self):
        self.assertEqual(model.accel_choices("darwin", "arm64"), ("tcg",))
        self.assertEqual(model.accel_choices("darwin", "x86_64"), ("tcg", "hvf"))
        self.assertEqual(model.accel_choices("win32", "AMD64"), ("tcg", "whpx"))
        self.assertEqual(model.accel_choices("linux", "x86_64"), ("tcg",))

    def test_the_editor_hides_what_does_not_apply(self):
        paths.HOST_PLATFORM = "win32"
        ed = self._editor(Machine(name="t"))
        values = list(ed.accel_cb.cget("values"))
        self.assertEqual([model.accel_by_label(v) for v in values], ["tcg", "whpx"])
        self.assertEqual(ed.collect().accel, "tcg")

    def test_a_saved_choice_the_host_lacks_is_kept(self):
        paths.HOST_PLATFORM = "linux"
        ed = self._editor(Machine(name="t", accel="whpx"))
        self.assertEqual(ed.collect().accel, "whpx")


@unittest.skipUnless(_tk_available(), "no display")
class DisplayAndBoot(EditorCase):

    def test_boot_fields_load_and_collect(self):
        m = Machine(name="t", show_picker=True, boot_args="  cpus=1   -x ", serial_log=True,
                    resolution="1920x1200")
        ed = self._editor(m)
        self.assertTrue(ed.picker_var.get())
        self.assertTrue(ed.serial_var.get())
        self.assertEqual(ed.resolution_var.get(), "1920x1200")
        got = ed.collect()
        self.assertEqual((got.show_picker, got.serial_log, got.boot_args, got.resolution),
                         (True, True, "cpus=1 -x", "1920x1200"))

    def test_verbose_in_the_extra_arguments_is_accepted(self):
        ed = self._editor(Machine(name="t"))
        ed.boot_args_var.set("-v")
        errors, _ = model.validate(ed.collect(), None, "darwin", check_files=False)
        self.assertEqual(errors, [])

    def test_verbose_checkbox(self):
        ed = self._editor(Machine(name="t"))
        self.assertFalse(ed.verbose_var.get())
        self.assertFalse(ed.collect().verbose)
        ed.verbose_var.set(True)
        self.assertTrue(ed.collect().verbose)
        self.assertTrue(self._editor(Machine(name="t", verbose=True)).verbose_var.get())

    def test_graphics_card_choice(self):
        ed = self._editor(Machine(name="t"))
        self.assertEqual(ed.gpu_var.get(), "Standard VGA")
        self.assertEqual(ed.collect().gpu, "std")
        self.assertEqual(str(ed.resolution_cb.cget("state")), "readonly")
        self.assertEqual(list(ed.gpu_cb.cget("values")),
                         ["Standard VGA", "ATI Radeon X1900 XT", "ATI Radeon HD 5770"])
        ed.gpu_var.set("ATI Radeon X1900 XT")
        ed._gpu_changed()
        got = ed.collect()
        self.assertEqual((got.gpu, got.resolution), ("x1900", "1024x768"))
        self.assertEqual(str(ed.resolution_cb.cget("state")), "disabled")
        ed.gpu_var.set("Standard VGA")
        ed._gpu_changed()
        self.assertEqual(str(ed.resolution_cb.cget("state")), "readonly")

    def test_a_saved_x1900_loads_with_the_size_locked(self):
        ed = self._editor(Machine(name="t", gpu="x1900", resolution="1920x1200"))
        self.assertEqual(ed.gpu_var.get(), "ATI Radeon X1900 XT")
        self.assertEqual(ed.resolution_var.get(), "1024x768")
        self.assertEqual(str(ed.resolution_cb.cget("state")), "disabled")

    def test_vnc_switch(self):
        ed = self._editor(Machine(name="t"))
        self.assertEqual(ed.collect().vnc, "")
        ed.vnc_on.set(True)
        ed._vnc_changed()
        self.assertEqual(ed.collect().vnc, ":1")


@unittest.skipUnless(_tk_available(), "no display")
class DrivePositions(EditorCase):

    def test_five_sata_positions_each_a_disk_or_a_cd(self):
        ed = self._editor(Machine(name="t"))
        self.assertEqual([r.kind_cb.cget("values") and list(r.kind_cb.cget("values"))
                          for r in ed.drive_rows], [["Empty", "Hard disk", "CD"]] * 5)
        self.assertFalse(hasattr(ed.drive_rows[0], "boot"))

    def test_a_typed_file_takes_its_kind_from_the_suffix(self):
        ed = self._editor(Machine(name="t"))
        ed.drive_rows[0].file.set("/images/install.iso")
        ed.drive_rows[1].file.set("/images/disk.img")
        d = ed.collect().drives
        self.assertEqual((d[0].kind, d[1].kind), ("cdrom", "disk"))

    def test_round_trip(self):
        drives = [Drive("cdrom", "/c.iso"), None, Drive("disk", "/a.qcow2", "qcow2"),
                  Drive("disk", "/b.img"), Drive("cdrom", "drive:Some Drive")]
        self.assertEqual(self._editor(Machine(name="t", drives=drives)).collect().drives, drives)

    def test_a_new_disk_goes_to_the_chosen_position(self):
        import qemugui.x86_ui_machine as ui_machine
        ed = self._editor(Machine(name="t"))

        class FakeDialog:
            def __init__(self, *_a, **_k):
                self.result = ("/new/disk.img", "raw", 4)

        orig, ui_machine.CreateDiskDialog = ui_machine.CreateDiskDialog, FakeDialog
        try:
            ed._new_disk()
        finally:
            ui_machine.CreateDiskDialog = orig
        self.assertEqual(ed.collect().drives[4], Drive("disk", "/new/disk.img", "raw"))

    def test_new_disk_button_needs_qemu_img(self):
        with tempfile.TemporaryDirectory() as d:
            paths.use_install_dir(d)
            try:
                self.assertIsNone(self._editor(Machine(name="t")).new_disk_button)
                (Path(d) / paths.qemu_img_name()).write_text("")
                self.assertIsNotNone(self._editor(Machine(name="t")).new_disk_button)
            finally:
                paths.use_install_dir(None)


@unittest.skipUnless(_tk_available(), "no display")
class ShareTab(EditorCase):

    def test_defaults_to_no_shared_folder(self):
        ed = self._editor(Machine(name="t"))
        self.assertEqual(ed.share_folder_var.get(), "")
        self.assertFalse(ed.share_ftp.get())
        self.assertEqual(ed.collect().share, Share())

    def test_loads_and_collects_a_share(self):
        m = Machine(name="t", share=Share("/shared", "mac", "secret", "all-interfaces", True))
        self.assertEqual(self._editor(m).collect().share, m.share)


@unittest.skipUnless(_tk_available(), "no display")
class UsbTab(EditorCase):

    def test_tablet_and_audio(self):
        ed = self._editor(Machine(name="t"))
        self.assertTrue(ed.usb_tablet_var.get())
        self.assertFalse(ed.usb_audio_var.get())
        self.assertTrue(ed.builtin_audio_var.get())
        ed.usb_tablet_var.set(False)
        ed.usb_audio_var.set(True)
        ed.builtin_audio_var.set(False)
        got = ed.collect()
        self.assertEqual((got.usb_tablet, got.usb_audio, got.builtin_audio),
                         (False, True, False))


@unittest.skipUnless(_tk_available(), "no display")
class PortForwardRows(EditorCase):

    def test_four_rows_load_and_collect_with_values_kept_when_disabled(self):
        rules = [model.HostFwd("udp", "5353", "53"), model.HostFwd("tcp", "8080", "80")]
        ed = self._editor(Machine(name="t", network=model.Network("user", model.DEFAULT_MAC, "",
                                                                  rules)))
        self.assertEqual(len(ed.fwd_rows), 4)
        self.assertEqual(str(ed.fwd_rows[0][3][1].cget("state")), "normal")
        ed.net_mode.set(model.network_mode_label("none"))
        ed._net_mode_changed()
        self.assertEqual(str(ed.fwd_rows[0][3][1].cget("state")), "disabled")
        got = [r.to_dict() for r in ed.collect().network.hostfwd if not r.empty]
        self.assertEqual(got, [r.to_dict() for r in rules])


@unittest.skipUnless(_tk_available(), "no display")
class NetworkTabFollowsTheHost(EditorCase):

    def tab(self, platform):
        paths.HOST_PLATFORM = platform
        return self._editor(model.new_machine(""), is_new=True)

    def test_windows(self):
        ed = self.tab("win32")
        values = list(ed.net_mode_cb.cget("values"))
        self.assertEqual(values[0], "default (slirp)")
        self.assertIn("tap", values)
        self.assertFalse(any(v.startswith("vmnet") for v in values), values)
        self.assertEqual(str(ed.ifname_label.cget("text")), "Tap device name:")
        self.assertEqual(ed.mac_var.get(), "52:54:00:12:34:56")

    def test_mac(self):
        ed = self.tab("darwin")
        values = list(ed.net_mode_cb.cget("values"))
        self.assertIn("vmnet-bridged", values)
        self.assertNotIn("tap", values)
        self.assertEqual(str(ed.ifname_label.cget("text")), "Vmnet host interface:")


@unittest.skipUnless(_tk_available(), "no display")
class DateAndTime(EditorCase):

    def test_loads_and_collects(self):
        ed = self._editor(Machine(name="t", rtc_base="localtime"))
        self.assertEqual(ed.rtc_base_var.get(), "localtime")
        ed.rtc_base_var.set(" 2005-04-29T10:30:00 ")
        self.assertEqual(ed.collect().rtc_base, "2005-04-29T10:30:00")

    def test_a_bad_value_is_reported_on_save(self):
        import qemugui.x86_ui_machine as ui_machine
        ed = self._editor(Machine(name="t"))
        ed.rtc_base_var.set("yesterday")
        shown = []
        orig = ui_machine.show_validation
        ui_machine.show_validation = lambda parent, errors, warnings: (shown.append(errors), False)[1]
        try:
            ed.save()
        finally:
            ui_machine.show_validation = orig
        self.assertTrue(any("Date and time" in e for e in shown[0]))


class _FakeRun:
    exit_code = None
    share = None

    def poll(self):
        return None

    def uptime(self):
        return 0.0


class MainWindowCase(unittest.TestCase):
    """A main window on a temp install folder made by support.make_install."""

    def setUp(self):
        from qemugui import x86_ui_main as ui
        self.ui = ui
        self.td = tempfile.TemporaryDirectory()
        support.make_install(self.td.name)
        paths.use_install_dir(self.td.name)
        self.saved = (paths.HOST_PLATFORM, ui.start_in_terminal, ui.start_machine,
                      ui.subprocess.Popen)
        self.roots = []
        support.shown.clear()

    def tearDown(self):
        (paths.HOST_PLATFORM, self.ui.start_in_terminal, self.ui.start_machine,
         self.ui.subprocess.Popen) = self.saved
        for r in self.roots:
            r.destroy()
        paths.use_install_dir(None)
        self.td.cleanup()

    def window(self, platform: str, settings=None):
        paths.HOST_PLATFORM = platform
        w = self.ui.MainWindow(settings or paths.Settings(),
                               settings_path=Path(self.td.name) / "settings.json")
        w.withdraw()
        self.roots.append(w)
        w.library.save(model.new_machine("t"))
        w.refresh_list(select="t")
        return w


@unittest.skipUnless(_tk_available(), "no display")
class StartDispatch(MainWindowCase):
    """On macOS every start goes through Terminal, sudo or not; on any other
    host the GUI runs the launcher itself and tracks the process."""

    def setUp(self):
        super().setUp()
        self.calls: list[str] = []
        ui = self.ui
        ui.start_in_terminal = lambda m, d, k=None: (self.calls.append("terminal"),
                                                     (Path(d) / "run.command", None))[1]
        ui.start_machine = lambda m, d, k=None: (self.calls.append("direct"), _FakeRun())[1]

    def test_macos_starts_in_terminal_without_sudo(self):
        w = self.window("darwin")
        self.assertIsNone(w.start_selected())
        self.assertEqual(self.calls, ["terminal"])
        self.assertIn("t", w.terminal_started)
        self.assertTrue(w.run_status.cget("text").startswith(self.ui.TERMINAL_STATUS))

    def test_other_hosts_run_the_launcher_directly(self):
        w = self.window("linux")
        self.assertIsNotNone(w.start_selected())
        self.assertEqual(self.calls, ["direct"])
        self.assertIn("t", w.running)

    def test_a_missing_key_file_blocks_the_start(self):
        w = self.window("darwin")
        (Path(self.td.name) / paths.SMC_KEY_FILE_NAME).unlink()
        self.ui.messagebox.showerror = lambda title, text, **kw: support.shown.append(text)
        self.assertIsNone(w.start_selected())
        self.assertEqual(self.calls, [])
        self.assertTrue(any("SMC key file" in t for t in support.shown), support.shown)


@unittest.skipUnless(_tk_available(), "no display")
class KeyFileSetting(MainWindowCase):

    def test_default_is_beside_the_program_and_stored_empty(self):
        w = self.window("darwin")
        self.assertEqual(w.key_var.get(), str(Path(self.td.name).resolve() / "OSK-Key.txt"))
        w.key_file_changed()
        self.assertEqual(w.settings.smc_key_file, "")

    def test_a_chosen_file_is_remembered_as_a_path_only(self):
        w = self.window("darwin")
        other = support.write_key(Path(self.td.name) / "other.txt", "y" * 64)
        w.key_var.set(str(other))
        w.key_file_changed()
        saved = (Path(self.td.name) / "settings.json").read_text()
        self.assertIn(str(other), json.loads(saved).values())
        self.assertNotIn("y" * 64, saved)
        self.assertNotIn("x" * 64, saved)
        self.assertIn(str(other), w.command_line.get("1.0", "end"))

    def test_the_preview_never_holds_the_key(self):
        w = self.window("darwin")
        text = w.command_line.get("1.0", "end")
        self.assertIn('OSK="$(cat ', text)
        self.assertNotIn(support.DUMMY_KEY, text)


@unittest.skipUnless(_tk_available(), "no display")
class WritingTheLauncherFromTheWindow(MainWindowCase):

    def test_save_writes_vars_esp_and_launcher(self):
        w = self.window("darwin")
        w._write_launcher(w.library.load("t"))
        folder = w.library.folder("t")
        for f in ("OVMF_VARS.fd", "esp.img", "run.command", "esp/EFI/OC/config.plist"):
            self.assertTrue((folder / f).is_file(), f)
        self.assertEqual(support.shown, [])

    def test_a_missing_template_is_reported_through_the_dialog(self):
        w = self.window("darwin")
        (Path(self.td.name) / "pc-bios" / paths.OVMF_VARS_TEMPLATE_NAME).unlink()
        self.ui.messagebox.showerror = lambda title, text, **kw: support.shown.append(text)
        w._write_launcher(w.library.load("t"))
        self.assertTrue(any("could not be written" in t for t in support.shown), support.shown)


@unittest.skipUnless(_tk_available(), "no display")
class SpawnPerHost(MainWindowCase):

    def setUp(self):
        super().setUp()
        self.calls = []

        class FakePopen:
            pid = 4321

            def __init__(_s, argv, **kw):
                self.calls.append((argv, kw))

            def poll(_s):
                return None

        self.ui.subprocess.Popen = FakePopen

    def start(self, platform: str):
        paths.HOST_PLATFORM = platform
        return self.ui.start_machine(model.new_machine("t"), Path(self.td.name) / "t")

    def test_windows_gets_a_new_console_and_no_redirection(self):
        run = self.start("win32")
        argv, kw = self.calls[0]
        self.assertTrue(str(argv[-1]).endswith("run.bat"), argv)
        self.assertEqual(kw["creationflags"], self.ui.CREATE_NEW_CONSOLE)
        self.assertNotIn("stdout", kw)
        self.assertIsNone(run.poll())
        self.assertTrue(run.log_path.read_text().startswith("# "))
        self.assertNotIn(support.DUMMY_KEY, run.log_path.read_text())

    def test_other_hosts_run_the_launcher_with_bash_into_the_log(self):
        run = self.start("linux")
        try:
            argv, kw = self.calls[0]
            self.assertEqual(argv[0], "/bin/bash")
            self.assertTrue(str(argv[1]).endswith("run.command"))
            self.assertNotIn("creationflags", kw)
            self.assertIsNotNone(kw["stdout"])
            self.assertNotIn(support.DUMMY_KEY, run.log_path.read_text())
        finally:
            run._log_fh.close()


if __name__ == "__main__":
    unittest.main()
