#!/bin/sh
# Called AFTER the unmodified Cadence 17.2 wstarter environment setup.
# Keep MainWin libuuid and other private libraries; replace only incompatible host-facing libs.
exec env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libstdc++.so.6:/usr/lib/x86_64-linux-gnu/libX11.so.6:/usr/lib/x86_64-linux-gnu/libxcb.so.1 "$@"
