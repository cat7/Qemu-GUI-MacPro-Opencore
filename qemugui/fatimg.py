"""Write a FAT16 volume image holding a folder tree, with VFAT long names.

Pure Python, no host tools: the same image is produced on macOS and Windows.
The image has no partition table; UEFI firmware reads it as one volume.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

SECTOR = 512
ROOT_ENTRIES = 512
RESERVED = 1
NUM_FATS = 2
MEDIA = 0xF8
EOC = 0xFFFF
ATTR_DIR = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LFN = 0x0F
# 2026-01-01 00:00:00, fixed so the image depends only on its contents
FIXED_DATE = ((2026 - 1980) << 9) | (1 << 5) | 1
FIXED_TIME = 0
SHORT_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'()-@^_`{}~")


class FatError(ValueError):
    pass


def _geometry(size: int) -> tuple[int, int, int]:
    """(sectors per cluster, sectors per FAT, cluster count) for a FAT16 volume of *size* bytes."""
    total = size // SECTOR
    root_secs = ROOT_ENTRIES * 32 // SECTOR
    for spc in (1, 2, 4, 8, 16, 32, 64):
        fat_secs = 1
        while True:
            data = total - RESERVED - NUM_FATS * fat_secs - root_secs
            clusters = data // spc
            need = ((clusters + 2) * 2 + SECTOR - 1) // SECTOR
            if need <= fat_secs:
                break
            fat_secs = need
        if 4085 <= clusters < 65525:
            return spc, fat_secs, clusters
    raise FatError(f"no FAT16 layout for {size} bytes")


def _short_fits(name: str) -> bool:
    """True when *name* is its own 8.3 name (upper case, no long entry needed)."""
    if name in (".", ".."):
        return True
    base, dot, ext = name.rpartition(".")
    if not dot:
        base, ext = name, ""
    return (0 < len(base) <= 8 and len(ext) <= 3 and "." not in base
            and all(c in SHORT_OK for c in base + ext))


def _pack83(base: str, ext: str) -> bytes:
    return base.ljust(8).encode("ascii") + ext.ljust(3).encode("ascii")


def _short_name(name: str, taken: set[bytes]) -> bytes:
    if _short_fits(name):
        base, dot, ext = name.rpartition(".")
        if not dot:
            base, ext = name, ""
        short = _pack83(base, ext)
        if short in taken:
            raise FatError(f"duplicate name {name!r}")
        taken.add(short)
        return short
    stem, dot, ext = name.lstrip(".").rpartition(".")
    if not dot:
        stem, ext = name.lstrip("."), ""
    clean = lambda s: "".join(c if c in SHORT_OK else "_" for c in s.upper() if c not in " .")
    stem, ext = clean(stem) or "_", clean(ext)[:3]
    for n in range(1, 1000000):
        tail = f"~{n}"
        short = _pack83(stem[:8 - len(tail)] + tail, ext)
        if short not in taken:
            taken.add(short)
            return short
    raise FatError(f"no short name left for {name!r}")


def _lfn_checksum(short: bytes) -> int:
    s = 0
    for b in short:
        s = (((s & 1) << 7) | (s >> 1)) + b & 0xFF
    return s


def _dir_entry(short: bytes, attr: int, cluster: int, size: int) -> bytes:
    return struct.pack("<11sBBBHHHHHHHI", short, attr, 0, 0, FIXED_TIME, FIXED_DATE, FIXED_DATE,
                       0, FIXED_TIME, FIXED_DATE, cluster, size)


def _entries(name: str, short: bytes, attr: int, cluster: int, size: int) -> bytes:
    out = b""
    if not _short_fits(name):
        units = name.encode("utf-16-le")
        if len(units) // 2 > 255:
            raise FatError(f"name too long: {name!r}")
        units += b"\x00\x00"
        pad = -len(units) % 26
        units += b"\xff" * pad
        chunks = [units[i:i + 26] for i in range(0, len(units), 26)]
        csum = _lfn_checksum(short)
        for seq in range(len(chunks), 0, -1):
            c = chunks[seq - 1]
            order = seq | (0x40 if seq == len(chunks) else 0)
            out += struct.pack("<B10sBBB12sH4s", order, c[:10], ATTR_LFN, 0, csum, c[10:22], 0, c[22:26])
    return out + _dir_entry(short, attr, cluster, size)


class _Volume:
    def __init__(self, size: int, label: str):
        self.size = size
        self.spc, self.fat_secs, self.clusters = _geometry(size)
        self.cluster_bytes = self.spc * SECTOR
        self.fat = [0xFFF8, 0xFFFF]
        self.data: dict[int, bytes] = {}
        self.label = label.upper()[:11]

    def alloc(self, payload: bytes) -> int:
        """Store *payload* in a new chain; returns its first cluster (0 for nothing)."""
        if not payload:
            return 0
        n = (len(payload) + self.cluster_bytes - 1) // self.cluster_bytes
        first = len(self.fat)
        if first + n - 2 > self.clusters:
            raise FatError("the files do not fit in the image")
        for i in range(n):
            self.fat.append(first + i + 1 if i < n - 1 else EOC)
            self.data[first + i] = payload[i * self.cluster_bytes:(i + 1) * self.cluster_bytes]
        return first

    def add_dir(self, folder: Path, parent_cluster: int | None) -> bytes:
        """The directory table of *folder*; subfolders and files are stored on the way."""
        taken: set[bytes] = set()
        table = b""
        names = sorted(p.name for p in folder.iterdir() if not p.name.startswith("._")
                       and p.name != ".DS_Store")
        children = []
        for name in names:
            p = folder / name
            if p.is_symlink() or not (p.is_dir() or p.is_file()):
                raise FatError(f"not a plain file or folder: {p}")
            children.append((name, p, _short_name(name, taken)))
        # a subfolder's own cluster is known only after its table is built, so reserve it first
        for name, p, short in children:
            if p.is_dir():
                cluster = len(self.fat)
                self.fat.append(EOC)            # placeholder head, extended below
                sub = (_dir_entry(_pack83(".", ""), ATTR_DIR, cluster, 0)
                       + _dir_entry(_pack83("..", ""), ATTR_DIR, parent_cluster or 0, 0)
                       + self.add_dir(p, cluster))
                self._store_at(cluster, sub)
                table += _entries(name, short, ATTR_DIR, cluster, 0)
            else:
                payload = p.read_bytes()
                table += _entries(name, short, ATTR_ARCHIVE, self.alloc(payload), len(payload))
        return table

    def _store_at(self, head: int, payload: bytes) -> None:
        cb = self.cluster_bytes
        chunks = [payload[i:i + cb] for i in range(0, len(payload), cb)] or [b""]
        cur = head
        self.data[cur] = chunks[0]
        for chunk in chunks[1:]:
            nxt = len(self.fat)
            if nxt - 2 >= self.clusters:
                raise FatError("the files do not fit in the image")
            self.fat.append(EOC)
            self.fat[cur] = nxt
            self.data[nxt] = chunk
            cur = nxt

    def image(self, root_table: bytes) -> bytes:
        if len(root_table) > ROOT_ENTRIES * 32:
            raise FatError("too many entries in the top folder")
        total = self.size // SECTOR
        boot = bytearray(SECTOR)
        boot[0:3] = b"\xeb\x3c\x90"
        boot[3:11] = b"MSDOS5.0"
        struct.pack_into("<HBHBHHBHHHII", boot, 11, SECTOR, self.spc, RESERVED, NUM_FATS, ROOT_ENTRIES,
                         total if total < 0x10000 else 0, MEDIA, self.fat_secs, 63, 255, 0,
                         total if total >= 0x10000 else 0)
        struct.pack_into("<BBBI11s8s", boot, 36, 0x80, 0, 0x29, 0x58383643,
                         self.label.ljust(11).encode("ascii"), b"FAT16   ")
        boot[510:512] = b"\x55\xaa"
        fat = struct.pack(f"<{len(self.fat)}H", *self.fat).ljust(self.fat_secs * SECTOR, b"\0")
        root = (struct.pack("<11sB20x", self.label.ljust(11).encode("ascii"), 0x08)
                + root_table).ljust(ROOT_ENTRIES * 32, b"\0")
        out = bytearray(self.size)
        pos = 0
        for part in (bytes(boot), fat, fat, root):
            out[pos:pos + len(part)] = part
            pos += len(part)
        for cluster, chunk in self.data.items():
            at = pos + (cluster - 2) * self.cluster_bytes
            out[at:at + len(chunk)] = chunk
        return bytes(out)


def build_image(folder: str | os.PathLike, size_mb: int = 64, label: str = "OPENCORE") -> bytes:
    """The bytes of a FAT16 image of *size_mb* MiB holding the contents of *folder*."""
    root = Path(folder)
    if not root.is_dir():
        raise FatError(f"not a folder: {root}")
    vol = _Volume(size_mb << 20, label)
    return vol.image(vol.add_dir(root, None))


def write_image(folder: str | os.PathLike, image: str | os.PathLike, size_mb: int = 64,
                label: str = "OPENCORE") -> Path:
    data = build_image(folder, size_mb, label)
    path = Path(image)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path
