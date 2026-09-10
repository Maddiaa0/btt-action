#!/usr/bin/env bash
set -euo pipefail

fail() { echo "::error::$*" >&2; exit 1; }

version=${BTT_VERSION#v}
[[ $version =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || fail 'version must be an exact stable release, for example 0.2.0.'
case "$BTT_INSTALL_ONLY" in
  true|false) ;;
  *) fail 'install-only must be true or false.' ;;
esac
case "$RUNNER_ARCH" in
  X64) arch=x86_64 ;;
  ARM64) arch=aarch64 ;;
  *) fail 'Unsupported runner architecture. Use X64 or ARM64.' ;;
esac
case "$RUNNER_OS" in
  Linux) target=$arch-unknown-linux-musl ;;
  macOS) target=$arch-apple-darwin ;;
  *) fail 'Unsupported runner OS. btt publishes Linux and macOS binaries.' ;;
esac

archive=btt-cli-$target.tar.xz
url=https://github.com/Maddiaa0/btt/releases/download/v$version
download=$(mktemp -d "$RUNNER_TEMP/btt-download.XXXXXX")
trap 'rm -rf "$download"' EXIT
for file in "$archive" "$archive.sha256"; do
  curl --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --silent --show-error --location \
    --retry 3 --connect-timeout 15 --max-time 120 "$url/$file" -o "$download/$file" \
    || fail "Could not download btt v$version for $target. Check that the release and its checksum asset exist and that GitHub is reachable."
done

read -r expected _ < "$download/$archive.sha256" || true
[[ ${expected:-} =~ ^[[:xdigit:]]{64}$ ]] || fail 'The release checksum is malformed.'
actual=$(shasum -a 256 "$download/$archive")
[[ ${actual%% *} == "$expected" ]] || fail 'btt download checksum mismatch.'

# Extract only the executable from cargo-dist's archive.
tar -xJf "$download/$archive" -C "$download" "btt-cli-$target/btt"
binary=$download/btt-cli-$target/btt
[[ -f $binary && ! -L $binary ]] || fail 'The release archive does not contain a regular btt executable.'
chmod +x "$binary"
[[ $("$binary" --version) == "btt $version" ]] || fail 'The executable version does not match the requested release.'
install_dir=$(mktemp -d "$RUNNER_TEMP/btt-bin.XXXXXX")
mv "$binary" "$install_dir/btt"
echo "$install_dir" >> "$GITHUB_PATH"
echo "version=$version" >> "$GITHUB_OUTPUT"
echo "binary-path=$install_dir/btt" >> "$GITHUB_OUTPUT"
echo "Installed btt $version ($target)"
