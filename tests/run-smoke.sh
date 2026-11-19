#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "${1:-}" != "--synthetic" ]; then
    if pgrep -x hyprlock >/dev/null; then
        echo "SKIP: unlock the desktop before real-pointer testing."
        exit 77
    fi
    BUILD=/tmp/opencode/token-tracker-pointer-build
    mkdir -p "$BUILD"
    wayland-scanner client-header tests/virtual-pointer.xml "$BUILD/virtual-pointer-client.h"
    wayland-scanner private-code tests/virtual-pointer.xml "$BUILD/virtual-pointer-protocol.c"
    cc -Wall -Wextra -I"$BUILD" tests/virtual_pointer.c "$BUILD/virtual-pointer-protocol.c" \
        -lwayland-client -o /tmp/opencode/token-tracker-pointer
fi
exec /usr/bin/python3 tests/smoke_overlay.py "$@"
