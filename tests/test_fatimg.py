"""fatimg: the image is parsed back in pure Python (boot sector, FAT chains,
long names, file contents, nested folders)."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from qemugui import fatimg  # noqa: E402


class Fat16:
    """A small FAT16 reader."""

    def __init__(self, data: bytes):
        self.d = data
        (self.bps, self.spc, self.reserved, self.nfats, self.root_entries, self.total16,
         self.media, self.fat_secs) = struct.unpack_from("<HBHBHHBH", data, 11)
        (self.total32,) = struct.unpack_from("<I", data, 32)
        self.fat_at = self.reserved * self.bps
        self.root_at = self.fat_at + self.nfats * self.fat_secs * self.bps
        self.data_at = self.root_at + self.root_entries * 32
        self.cb = self.spc * self.bps

    def fat(self, n: int, copy: int = 0) -> int:
        return struct.unpack_from("<H", self.d, self.fat_at + copy * self.fat_secs * self.bps
                                  + 2 * n)[0]

    def chain(self, first: int) -> list[int]:
        out = []
        n = first
        while 2 <= n < 0xFFF8:
            out.append(n)
            n = self.fat(n)
            assert len(out) < 100000, "loop in a FAT chain"
        assert n >= 0xFFF8, f"chain ends in {n:#x}"
        return out

    def read(self, first: int, size: int | None = None) -> bytes:
        if not first:
            return b""
        raw = b"".join(self.d[self.data_at + (c - 2) * self.cb:self.data_at + (c - 1) * self.cb]
                       for c in self.chain(first))
        return raw if size is None else raw[:size]

    @staticmethod
    def lfn_part(e: bytes) -> str:
        raw = e[1:11] + e[14:26] + e[28:32]
        text = raw.decode("utf-16-le")
        return text.split("\x00")[0].rstrip("￿")

    def entries(self, raw: bytes):
        """(name, attr, first cluster, size, short name) of a directory table."""
        out, parts = [], []
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5:
                continue
            if e[11] == 0x0F:
                parts.append((e[0] & 0x3F, e, self.lfn_part(e)))
                continue
            if e[11] & 0x08:
                parts = []
                continue
            short = e[:8].decode("ascii").rstrip() + (
                "." + e[8:11].decode("ascii").rstrip() if e[8:11].strip() else "")
            name = short
            if parts:
                csum = fatimg._lfn_checksum(e[:11])
                assert all(p[1][13] == csum for p in parts), "bad long name checksum"
                assert [p[0] for p in parts] == list(range(len(parts), 0, -1))
                assert parts[0][1][0] & 0x40
                name = "".join(p[2] for p in reversed(parts))
            parts = []
            attr = e[11]
            cluster, size = struct.unpack_from("<H", e, 26)[0], struct.unpack_from("<I", e, 28)[0]
            out.append((name, attr, cluster, size, short))
        return out

    def root(self):
        return self.entries(self.d[self.root_at:self.root_at + self.root_entries * 32])

    def listdir(self, entry):
        return self.entries(self.read(entry[2]))

    def tree(self, entries=None, prefix="") -> dict[str, bytes]:
        files = {}
        for name, attr, cluster, size, short in (entries if entries is not None else self.root()):
            if name in (".", ".."):
                continue
            if attr & 0x10:
                files.update(self.tree(self.entries(self.read(cluster)), prefix + name + "/"))
            else:
                files[prefix + name] = self.read(cluster, size)
        return files


def make_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


SAMPLE = {
    "EFI/BOOT/BOOTx64.efi": b"boot" * 1000,
    "EFI/BOOT/.contentVisibility": b"Disabled",
    "EFI/OC/OpenCore.efi": bytes(range(256)) * 300,
    "EFI/OC/config.plist": b"<plist/>",
    "EFI/OC/Drivers/OpenHfsPlus.efi": b"h" * 5000,
    "EFI/OC/Kexts/A Kext.kext/Contents/Info.plist": b"info",
    "EFI/OC/Kexts/A Kext.kext/Contents/MacOS/Binary": b"\x00\x01" * 70000,
    "top.txt": b"",
    "x": b"1",
}


class ImageLayout(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.src = Path(self.td.name) / "src"
        make_tree(self.src, SAMPLE)
        self.img = fatimg.build_image(self.src)
        self.fs = Fat16(self.img)

    def tearDown(self):
        self.td.cleanup()

    def test_boot_sector(self):
        d = self.img
        self.assertEqual(d[510:512], b"\x55\xaa")
        self.assertEqual(d[0], 0xEB)
        self.assertEqual(self.fs.bps, 512)
        self.assertIn(self.fs.spc, (1, 2, 4, 8, 16, 32, 64))
        self.assertEqual(self.fs.nfats, 2)
        self.assertEqual(self.fs.root_entries, 512)
        self.assertEqual(self.fs.media, 0xF8)
        self.assertEqual(len(d), 64 << 20)
        self.assertEqual(self.fs.total16 or self.fs.total32, len(d) // 512)
        self.assertEqual(d[54:62], b"FAT16   ")
        self.assertEqual(d[43:54], b"OPENCORE   ")

    def test_fat16_cluster_count(self):
        clusters = (len(self.img) // 512 - self.fs.reserved - 2 * self.fs.fat_secs
                    - self.fs.root_entries * 32 // 512) // self.fs.spc
        self.assertTrue(4085 <= clusters < 65525, clusters)

    def test_the_two_fats_agree_and_start_with_the_media_byte(self):
        self.assertEqual(self.fs.fat(0), 0xFFF8)
        self.assertEqual(self.fs.fat(1), 0xFFFF)
        a = self.img[self.fs.fat_at:self.fs.fat_at + self.fs.fat_secs * 512]
        b = self.img[self.fs.fat_at + self.fs.fat_secs * 512:self.fs.root_at]
        self.assertEqual(a, b)

    def test_volume_label_entry(self):
        e = self.img[self.fs.root_at:self.fs.root_at + 32]
        self.assertEqual(e[:11], b"OPENCORE   ")
        self.assertEqual(e[11], 0x08)

    def _find(self, parts):
        entries = self.fs.root()
        for part in parts:
            entry = next(e for e in entries if e[0] == part)
            entries = self.fs.entries(self.fs.read(entry[2]))
        return entry

    def test_every_file_reads_back(self):
        self.assertEqual(self.fs.tree(), SAMPLE)

    def test_chains_are_distinct_and_the_right_length(self):
        seen = set()

        def walk(entries):
            for name, attr, cluster, size, _s in entries:
                if name in (".", ".."):
                    continue
                if attr & 0x10:
                    chain = self.fs.chain(cluster)
                    walk(self.fs.entries(self.fs.read(cluster)))
                else:
                    chain = self.fs.chain(cluster) if cluster else []
                    self.assertEqual(len(chain), -(-size // self.fs.cb), name)
                self.assertFalse(seen & set(chain), name)
                seen.update(chain)
        walk(self.fs.root())
        self.assertTrue(seen)

    def test_an_empty_file_has_no_cluster(self):
        e = next(e for e in self.fs.root() if e[0] == "top.txt")
        self.assertEqual((e[2], e[3]), (0, 0))

    def test_long_names_with_spaces_and_case(self):
        kexts = self.fs.listdir(self._find(["EFI", "OC", "Kexts"]))
        self.assertEqual([k[0] for k in kexts if k[0] not in (".", "..")], ["A Kext.kext"])
        short = kexts[2][4]
        self.assertNotEqual(short, "A Kext.kext")
        self.assertIn("~1", short)

    def test_a_name_that_is_its_own_short_name_needs_no_long_entry(self):
        root = Path(self.td.name) / "short"
        make_tree(root, {"DATA.BIN": b"d"})
        data = fatimg.build_image(root)
        fs = Fat16(data)
        entry = data[fs.root_at + 32:fs.root_at + 64]
        self.assertEqual(entry[:11], b"DATA    BIN")
        self.assertNotEqual(entry[11], 0x0F)
        self.assertEqual(fs.tree(), {"DATA.BIN": b"d"})

    def test_a_lower_case_name_gets_a_long_entry(self):
        e = next(e for e in self.fs.root() if e[0] == "x")
        self.assertEqual(e[4], "X~1")

    def test_dot_entries(self):
        efi = self._find(["EFI"])
        sub = self.fs.entries(self.fs.read(efi[2]))
        self.assertEqual([sub[0][0], sub[1][0]], [".", ".."])
        self.assertEqual(sub[0][2], efi[2])
        self.assertEqual(sub[1][2], 0)             # parent is the root
        oc = self._find(["EFI", "OC"])
        sub = self.fs.entries(self.fs.read(oc[2]))
        self.assertEqual(sub[1][2], efi[2])

    def test_a_dot_file_gets_a_long_name(self):
        boot = self.fs.listdir(self._find(["EFI", "BOOT"]))
        self.assertIn(".contentVisibility", [b[0] for b in boot])

    def test_utf16_long_names(self):
        make_tree(self.src, {"Résumé über.txt": b"u"})
        fs = Fat16(fatimg.build_image(self.src))
        self.assertEqual(fs.tree()["Résumé über.txt"], b"u")

    @unittest.skipIf(sys.platform == "win32", "path longer than MAX_PATH")
    def test_a_name_of_255_characters(self):
        name = "n" * 251 + ".bin"
        make_tree(self.src, {name: b"long"})
        self.assertEqual(Fat16(fatimg.build_image(self.src)).tree()[name], b"long")

    def test_same_input_same_image(self):
        self.assertEqual(self.img, fatimg.build_image(self.src))

    def test_mac_junk_is_left_out(self):
        make_tree(self.src, {".DS_Store": b"j", "._x": b"j", "EFI/.DS_Store": b"j"})
        self.assertEqual(Fat16(fatimg.build_image(self.src)).tree(), SAMPLE)

    def test_clashing_short_names_get_numbers(self):
        files = {f"same long name {i}.txt": bytes([i]) for i in range(12)}
        root = Path(self.td.name) / "clash"
        make_tree(root, files)
        fs = Fat16(fatimg.build_image(root))
        self.assertEqual(fs.tree(), files)
        shorts = [e[4] for e in fs.root()]
        self.assertEqual(len(shorts), len(set(shorts)))

    def test_write_image_replaces_the_file(self):
        out = Path(self.td.name) / "esp.img"
        out.write_bytes(b"old")
        fatimg.write_image(self.src, out)
        self.assertEqual(out.read_bytes(), self.img)
        self.assertFalse((Path(self.td.name) / "esp.img.tmp").exists())

    def test_write_image_in_use_leaves_no_temporary_file(self):
        from unittest import mock
        out = Path(self.td.name) / "esp.img"
        out.write_bytes(b"old")
        with mock.patch.object(fatimg.os, "replace", side_effect=PermissionError("in use")):
            with self.assertRaises(PermissionError):
                fatimg.write_image(self.src, out)
        self.assertEqual(out.read_bytes(), b"old")
        self.assertFalse((Path(self.td.name) / "esp.img.tmp").exists())

    def test_a_label_and_a_size(self):
        data = fatimg.build_image(self.src, size_mb=32, label="mine")
        self.assertEqual(len(data), 32 << 20)
        self.assertEqual(data[43:54], b"MINE       ")
        self.assertEqual(Fat16(data).tree(), SAMPLE)

    def test_a_missing_folder(self):
        with self.assertRaises(fatimg.FatError):
            fatimg.build_image(Path(self.td.name) / "nope")


class DoesNotFit(unittest.TestCase):

    def test_files_larger_than_the_image(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(Path(td), {"big.bin": b"\x01" * (5 << 20)})
            with self.assertRaises(fatimg.FatError) as cm:
                fatimg.build_image(td, size_mb=4)
            self.assertIn("do not fit", str(cm.exception))

    def test_many_small_files_use_up_the_clusters(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(Path(td), {f"f{i}.bin": b"x" for i in range(200)})
            fatimg.build_image(td, size_mb=8)
            with self.assertRaises(fatimg.FatError):
                fatimg.build_image(td, size_mb=2)

    def test_a_subfolder_that_does_not_fit(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(Path(td), {"a/b/big.bin": b"\x01" * (5 << 20)})
            with self.assertRaises(fatimg.FatError):
                fatimg.build_image(td, size_mb=4)

    def test_too_many_entries_in_the_top_folder(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(Path(td), {f"file number {i}.txt": b"" for i in range(300)})
            with self.assertRaises(fatimg.FatError):
                fatimg.build_image(td)

    def test_a_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "real").write_bytes(b"x")
            (Path(td) / "link").symlink_to(Path(td) / "real")
            with self.assertRaises(fatimg.FatError):
                fatimg.build_image(td)


if __name__ == "__main__":
    unittest.main()
