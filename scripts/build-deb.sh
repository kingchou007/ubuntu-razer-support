#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
VERSION="$(cat "$PROJECT_ROOT/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid VERSION' >&2; exit 1; }
BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_ROOT"' EXIT
install -d "$BUILD_ROOT/DEBIAN" "$BUILD_ROOT/usr/share/ubuntu-support/ubuntu_support" "$BUILD_ROOT/usr/bin" "$BUILD_ROOT/usr/libexec" "$BUILD_ROOT/usr/share/applications" "$BUILD_ROOT/usr/share/icons/hicolor/256x256/apps" "$BUILD_ROOT/lib/systemd/system" "$BUILD_ROOT/usr/share/polkit-1/actions" "$BUILD_ROOT/usr/share/doc/ubuntu-support"
install -m 644 "$PROJECT_ROOT"/ubuntu_support/*.py "$BUILD_ROOT/usr/share/ubuntu-support/ubuntu_support/"
install -m 644 "$PROJECT_ROOT/main.py" "$BUILD_ROOT/usr/share/ubuntu-support/main.py"
install -m 755 "$PROJECT_ROOT/ubuntu_support/kernel_helper.py" "$BUILD_ROOT/usr/libexec/ubuntu-support-kernel"
install -m 755 "$PROJECT_ROOT/ubuntu_support/fan_service.py" "$BUILD_ROOT/usr/libexec/ubuntu-support-fans"
cat > "$BUILD_ROOT/usr/bin/ubuntu-support" <<'LAUNCHER'
#!/bin/sh
exec /usr/bin/python3 /usr/share/ubuntu-support/main.py "$@"
LAUNCHER
chmod 755 "$BUILD_ROOT/usr/bin/ubuntu-support"
install -m 644 "$PROJECT_ROOT/packaging/ubuntu-support.desktop" "$BUILD_ROOT/usr/share/applications/"
install -m 644 "$PROJECT_ROOT/assets/ubuntu-support-icon.png" "$BUILD_ROOT/usr/share/icons/hicolor/256x256/apps/ubuntu-support.png"
install -m 644 "$PROJECT_ROOT/packaging/ubuntu-support-fans.service" "$BUILD_ROOT/lib/systemd/system/"
install -m 644 "$PROJECT_ROOT/packaging/io.github.kingchou007.ubuntu-support.policy" "$BUILD_ROOT/usr/share/polkit-1/actions/"
install -m 755 "$PROJECT_ROOT/packaging/postinst" "$PROJECT_ROOT/packaging/prerm" "$PROJECT_ROOT/packaging/postrm" "$BUILD_ROOT/DEBIAN/"
install -m 644 "$PROJECT_ROOT/README.md" "$PROJECT_ROOT/LICENSE" "$PROJECT_ROOT/THIRD_PARTY.md" "$BUILD_ROOT/usr/share/doc/ubuntu-support/"
cat > "$BUILD_ROOT/DEBIAN/control" <<CONTROL
Package: ubuntu-support
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Maintainer: Ubuntu Support maintainers <noreply@github.com>
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, policykit-1, power-profiles-daemon, systemd, kmod
Recommends: gnome-control-center, gnome-system-monitor, update-manager, x11-xserver-utils, grub2-common
Homepage: https://github.com/kingchou007/ubuntu-laptop-support
Description: Chinese Ubuntu management UI with Razer Blade support
 System monitoring, guarded fan control, NVIDIA monitoring, display settings,
 and one-time switching between installed generic and realtime kernels.
CONTROL
mkdir -p "$PROJECT_ROOT/dist"
dpkg-deb --root-owner-group --build "$BUILD_ROOT" "$PROJECT_ROOT/dist/ubuntu-support_${VERSION}_all.deb"
