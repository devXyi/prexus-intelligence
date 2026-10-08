#!/usr/bin/env bash
# Run the control-plane test-suite inside a network namespace that has ONLY a loopback device.
# Needs CAP_SYS_ADMIN (root, or `unshare -rn`). Proves the suite passes — and the app reports
# `air_gapped_verified: true` — with no possible egress.
set -euo pipefail
cd "$(dirname "$0")/../control-plane"
exec unshare --net bash -c '
python3 - <<PY
import fcntl, socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
flags = struct.unpack("16sH14s", fcntl.ioctl(s, 0x8913, struct.pack("16sH14s", b"lo", 0, b"")))[1]
fcntl.ioctl(s, 0x8914, struct.pack("16sH14s", b"lo", flags | 0x1 | 0x40, b""))   # IFF_UP | IFF_RUNNING
PY
echo "interfaces in namespace: $(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d " " | tr "\n" " ")"
PREXUS_EXPECT_NETNS=1 node --test
'
