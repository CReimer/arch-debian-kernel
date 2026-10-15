#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GH_TOKEN:?Missing GitHub token}"
: "${GITHUB_REPOSITORY:?Missing repository}"
: "${PACMAN_SIGNING_KEY:?Missing dedicated package-signing key}"
key_home=$(mktemp -d)
trap 'rm -rf "$key_home"' EXIT
chmod 700 "$key_home"
export GNUPGHOME="$key_home"
printf '%s' "$PACMAN_SIGNING_KEY" | gpg --batch --quiet --import
unset PACMAN_SIGNING_KEY
fingerprint=$(tr -d '[:space:]' < keys/repository.fingerprint)
gpg --batch --list-secret-keys "$fingerprint" >/dev/null
release=repository
if ! gh release view "$release" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    gh release create "$release" --repo "$GITHUB_REPOSITORY" --target "$(git rev-parse HEAD)" \
        --title 'Pacman repository (x86_64)' --notes-file docs/release-notes.md
fi
# Package names are immutable. Reuse already published bytes on rebuilds; only
# database aliases are replaced. Old packages stay available to cached clients.
gh release view "$release" --repo "$GITHUB_REPOSITORY" --json assets --jq '.assets[].name' > dist/remote-assets.txt
for package in dist/*.pkg.tar.zst; do
    name=${package##*/}
    if grep -Fxq "$name" dist/remote-assets.txt; then
        gh release download "$release" --repo "$GITHUB_REPOSITORY" --pattern "$name" --pattern "$name.sig" --dir dist --clobber
        gpg --batch --verify "$package.sig" "$package"
    else
        gpg --batch --yes --local-user "$fingerprint" --detach-sign "$package"
        gh release upload "$release" "$package" "$package.sig" --repo "$GITHUB_REPOSITORY"
    fi
done
(
    cd dist
    rm -f arch-debian-kernel.db* arch-debian-kernel.files*
    repo-add --sign --key "$fingerprint" --include-sigs arch-debian-kernel.db.tar.gz ./*.pkg.tar.zst
    # GitHub assets cannot represent symlinks; pacman downloads these aliases.
    cp --remove-destination arch-debian-kernel.db.tar.gz arch-debian-kernel.db
    cp --remove-destination arch-debian-kernel.db.tar.gz.sig arch-debian-kernel.db.sig
    cp --remove-destination arch-debian-kernel.files.tar.gz arch-debian-kernel.files
    cp --remove-destination arch-debian-kernel.files.tar.gz.sig arch-debian-kernel.files.sig
    gpg --verify arch-debian-kernel.db.sig arch-debian-kernel.db
)
# Payloads and their signatures are available before clients can see a new DB.
gh release upload "$release" dist/arch-debian-kernel.db* dist/arch-debian-kernel.files* keys/repository.asc --repo "$GITHUB_REPOSITORY" --clobber
