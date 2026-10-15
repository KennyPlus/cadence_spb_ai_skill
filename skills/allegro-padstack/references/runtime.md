# Runtime requirements

Offline generation needs only the Python standard library. The native backend uses Linux `tools.lnx86/bin`; provide Cadence, a valid license, and system dependencies on the target machine. Installing a skill does not install or modify those components.

For newer SMD workflows, use `--backend xml --cadence-root /path/to/cadence --display xvfb` after checking `-x/-xo`. Through holes use replay, with `--replay-mask-column Pad` or `Regular Pad` for the release. Do not assume XML support on older 17.2 releases.

Xvfb provides an isolated display, not freedom from X dependencies. It requires `xvfb-run`, `xauth`, and vendor libraries. Licensing uses the target `CDS_LIC_FILE`; do not commit licenses or complete environments.

`--compat-172` and cleanup options apply only to matching old Linux behavior. `prepare_spb24.py` creates a job-private correction for a specific launcher format only when the failure and its checks match. It does not modify the installation; a working normal entrypoint needs no `--starter-file`.

Native reports must match layer geometry, offsets, hole dimensions/tolerances, and plating. File existence is not verification. Recheck release/backend capabilities on each machine.
