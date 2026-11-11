# Qemu-system-x86_64 OpenCore GUI

A portable launcher for Intel Mac OS X 10.5 (Leopard, 32-bit kernel) on
`qemu-system-x86_64`: QEMU q35 with OVMF and OpenCore, presenting as a Mac
Pro. Target QEMU: branch `x86-opencore` of github.com/cat7/qemu.

Machines are kept in a `Machines` folder beside the program, one folder
each, as `machine.json`. `run.command` (macOS) or `run.bat` (Windows) is
generated from that record every time it is saved or started. The OpenCore
boot disk (`esp/` and `esp.img`) is regenerated from the record at the same
time; `OVMF_VARS.fd` is the machine's NVRAM, copied from
`pc-bios/edk2-i386-vars.fd` once and never overwritten.

## Install folder

The program sits in the folder that holds:

    qemu-system-x86_64[.exe]
    qemu-img[.exe]                 (for making new disks)
    winusb-switch.exe              (Windows, host USB devices)
    pc-bios/edk2-x86_64-code.fd
    pc-bios/edk2-i386-vars.fd
    OpenCore/                      an unpacked OpenCore release:
        X64/EFI/BOOT/BOOTx64.efi
        X64/EFI/OC/OpenCore.efi
        X64/EFI/OC/Drivers/*.efi   (OpenRuntime, OpenHfsPlus,
                                    OpenPartitionDxe, ResetNvramEntry)
        X64/EFI/OC/Tools/OpenShell.efi
        Docs/Sample.plist
    Kexts/                         optional; every *.kext folder is injected
    OSK-Key.txt                    SMC key file (path is a setting)
    ati-r580-gop.rom               optional; ROM of the ATI Radeon X1900 XT card

The SMC key file is one line of exactly 64 printable characters. The key is
read by the launcher each time it runs and is stored nowhere else.

## Requirements

- To run from source: Python 3.11+ with tkinter, plus `pyftpdlib` for the
  shared folder (`python -m pip install pyftpdlib`).
- To build a bundle: PyInstaller, with `pyftpdlib` installed in the same
  Python.

## Run from source

    python x86_gui.py

## Build

macOS, with the python.org framework Python (Homebrew's Python has no
tkinter):

    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
        -m PyInstaller --noconfirm X86GUI.spec

Windows, a single `.exe`:

    python -m PyInstaller --noconfirm X86GUI.spec

Put the result in the install folder.

## Tests

    python -m unittest discover -s tests
