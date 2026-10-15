# arch-debian-kernel

Official Debian-signed kernels for Arch Linux, distributed as Pacman packages
with automatic updates and a signed binary repository hosted on GitHub Releases.

This project repackages **unmodified Debian binaries**. It does not compile kernels
or replace Secure Boot signatures. A separate OpenPGP key signs only the Pacman
packages and repository databases.

## Set up the repository

Arch Linux x86_64 is supported. First, download the public signing key:

```sh
curl -fL https://raw.githubusercontent.com/CReimer/arch-debian-kernel/main/keys/repository.asc -o /tmp/arch-debian-kernel.asc
pacman-key --add /tmp/arch-debian-kernel.asc
pacman-key --finger 4F38BF98657DB9563E17271547C5CB6E551D4869
```

Compare the complete fingerprint with [keys/repository.fingerprint](keys/repository.fingerprint).
Then locally sign the key:

```sh
pacman-key --lsign-key 4F38BF98657DB9563E17271547C5CB6E551D4869
```

Add the following section to `/etc/pacman.conf`:

```ini
[arch-debian-kernel]
SigLevel = Required
Server = https://github.com/CReimer/arch-debian-kernel/releases/download/repository
```

Install the packages as part of a full system upgrade:

```sh
pacman -Syu linux-debian-bin systemd-boot-debian-bin shim-debian-signed-bin
```

Subsequent updates arrive through `pacman -Syu`. GitHub Actions checks Debian twice
a day. All packages and databases require valid repository signatures;
`SigLevel = Never` is not needed.

## Available packages

| Package | Contents |
|---|---|
| `linux-debian-bin` | Current Debian Sid signed kernel, matching original modules, kernel configuration and mkinitcpio preset |
| `systemd-boot-debian-bin` | Debian-signed systemd-boot EFI binary |
| `shim-debian-signed-bin` | Microsoft-signed Debian Shim and Debian-signed helpers, including MokManager |

Installing the packages **does not create a firmware boot entry** or enroll Secure
Boot keys. The existing Arch kernel can remain installed alongside the Debian
kernel. The Debian bootloader is stored outside bootctl's standard source directory,
at `/usr/lib/arch-debian-kernel/systemd-boot/systemd-bootx64.efi.signed`. Installing
this package does not add a `.signed` override to Arch's bootctl source directory.
The separate Debian boot path must be maintained explicitly.

## Boot with systemd-boot

The intended boot chain is:

```text
UEFI → Debian Shim → Debian systemd-boot → Debian kernel → Arch initramfs → Arch
```

The kernel uses Arch's mkinitcpio integration. On a conventional Arch installation,
the following files will be available under `/boot`:

- `vmlinuz-linux-debian-bin`
- `initramfs-linux-debian-bin.img`
- `initramfs-linux-debian-bin-fallback.img`

If needed, generate the initramfs with `mkinitcpio -p linux-debian-bin`. Successful
generation using your existing mkinitcpio hooks is required before rebooting. The
files must reside on the ESP or a systemd-boot-readable XBOOTLDR partition. If your
`/boot` layout differs, adjust the preset and boot files accordingly.

Example **additional** Type 1 entry at `loader/entries/arch-debian.conf`:

```ini
title Arch Linux (Debian signed kernel)
linux /vmlinuz-linux-debian-bin
initrd /initramfs-linux-debian-bin.img
options root=UUID=YOUR-ROOT-UUID rw lockdown=integrity iommu.passthrough=0 sysctl.kernel.kexec_load_disabled=1
```

Copy the actual root, LUKS, LVM and Btrfs parameters from your working Arch entry.
Intel systems may also need `intel_iommu=on`. Existing `lsm=` parameters must include
`bpf`. Use a separate initramfs; a locally signed UKI introduces a different trust
path.

For the separate EFI boot path, copy the signed Debian binaries into a dedicated
directory on the ESP. By default, Shim expects its second-stage loader there to be
named `grubx64.efi`; in this setup, that file contains **systemd-boot**, not GRUB.
Copy the Debian bootloader from
`/usr/lib/arch-debian-kernel/systemd-boot/systemd-bootx64.efi.signed` to that
separate ESP directory as `grubx64.efi`. List the installed package files with:

```sh
pacman -Ql systemd-boot-debian-bin shim-debian-signed-bin
```

Kernel and initramfs updates are integrated through mkinitcpio. Copying updated
Shim/systemd-boot files to your ESP and selecting the firmware boot entry remain
separate setup steps. This project does not include an automatic ESP installation
hook.

## Upgrading from the initial bootloader package

Version `262.deb1-1` installed the Debian bootloader in bootctl's standard source
directory. Upgrading to `262.deb1-2` or later removes that override and installs
the binary in the dedicated project directory above.

The upgrade does not restore EFI files that were already copied to the ESP by
`bootctl install`, `bootctl update` or `systemd-boot-update.service`. If you used
that initial version, verify your normal and fallback ESP bootloader files and
restore the bootloader trusted by your existing Secure Boot setup when needed.
An existing locally signed override created by your own signing tools is separate
from this package; those tools may need to regenerate it after the upgrade.

## Secure Boot and EAC Linux v2

A correctly signed stack does not establish EAC compatibility. This project checks
static prerequisites; it does not guarantee support for a game or successful
attestation.

After the first boot, verify at least Secure Boot, TPM 2.0, the TPM event log,
IOMMU, lockdown, BPF LSM and the kexec restriction on your hardware:

```sh
mokutil --sb-state
cat /sys/kernel/security/lockdown
cat /sys/kernel/security/lsm
cat /proc/sys/kernel/kexec_load_disabled
cat /proc/cmdline
```

Install `mokutil` separately if you want to use it for diagnostics. When using
Shim, Epic requires all enrolled MOKs to be recognized. These packages do not
automatically cover your own DKMS modules. NVIDIA requires compatible kernel
modules signed by a recognized key, together with matching userspace drivers.

- [Epic's published requirements](https://onlineservices.epicgames.com/news/introducing-easy-anti-cheat-linux-v2)
- [Debian Secure Boot documentation](https://wiki.debian.org/SecureBoot)

## Build locally

On an up-to-date Arch system:

```sh
sudo pacman -Syu --needed base-devel python python-cryptography debian-archive-keyring sbsigntools mkinitcpio libarchive
python -m unittest discover -s tests -v
python scripts/update.py
bash scripts/build.sh
```

`makepkg` runs without root privileges. When run as root, the build script uses the
`builder` account. Binary packages are written to `dist/`. Building does not modify
the installed Arch packages or kernel.

## Automation and trust

1. `scripts/update.py` verifies Debian's `InRelease` using Arch's
   `debian-archive-keyring` package. It checks the suite, architecture, expiration
   time and maximum metadata age.
2. The package index is checked against its authenticated SHA-256 checksum.
   Exact package versions and SHA-256 checksums are recorded in `sources.lock.json`
   and the generated `PKGBUILD` files.
3. `makepkg` checks the downloaded `.deb` files again. Repackaging does not change
   kernel, module or EFI binaries.
4. `check_packages.py` compares these files byte for byte and verifies Debian CA
   trust and the required kernel options. A container installation test also
   checks that official bootctl install/update behavior is unchanged. The build
   stops if Debian's package layout changes or required capabilities are missing.
5. Only main-branch, scheduled and manual runs receive the dedicated signing key
   during publication. Pull requests are built but cannot sign or publish.
6. Packages and signatures are uploaded before the new database. Older package
   files remain available to clients with cached databases. Published package
   filenames are never overwritten. Changes to the Arch integration require a
   `pkgrel` increment.

GitHub replaces databases and signatures as separate release assets. A client
connecting during publication may briefly encounter a signature error. Retrying
after publication finishes resolves it without disabling signature verification.
A failed build leaves the existing repository files untouched; a failed upload
may require a manual workflow rerun.

## Maintenance and forks

The workflow is defined in `.github/workflows/repository.yml`. It runs on pushes to
`main`, pull requests, twice-daily schedules and manual **Run workflow** requests.

For your own fork:

- Update the repository URLs in the documentation and Pacman configuration.
- Generate a dedicated OpenPGP signing key. Save its public key to
  `keys/repository.asc` and its complete fingerprint to
  `keys/repository.fingerprint`.
- Store the ASCII-armored private key as the Actions secret `PACMAN_SIGNING_KEY`.
  Use a key dedicated to this repository.
- Enable Actions with permission to write repository contents. GitHub Pages is
  not required.

The signing key is available as a secret only during the signing step. The trust
boundary therefore includes the workflow files and people with write access to
the main branch. Actions are pinned to commit SHAs and the Arch base image to a
digest. Installed Arch tools are intentionally kept up to date.

## License

Original scripts and package recipes use the MIT license; see [LICENSE](LICENSE).
Debian binaries retain their respective upstream licenses, and their included
copyright files remain in the packages. Corresponding source packages are
available in the [Debian archive](https://deb.debian.org/debian/pool/main/l/linux/)
and [Debian Snapshot](https://snapshot.debian.org/package/linux/).
