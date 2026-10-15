#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
if [[ $(id -u) == 0 ]]; then
    id builder &>/dev/null || useradd --create-home builder
    chown -R builder:builder packages dist
    build=(runuser -u builder --)
else
    build=()
fi
for package in packages/*; do
    (
        cd "$package"
        "${build[@]}" makepkg --force --cleanbuild --noconfirm --nodeps
        "${build[@]}" makepkg --printsrcinfo > .SRCINFO
    )
    cp "$package"/*.pkg.tar.zst dist/
done
python scripts/check_packages.py dist
