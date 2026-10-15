# Runtime requirements

Offline `package.py` generation uses the Python standard library. The native backend is Linux and requires the target Cadence installation, a valid license, `xvfb-run`, `xauth`, and vendor dependencies. macOS/Windows can prepare specifications and scripts for that backend. Skill installation support does not imply native editor support on every platform.

Use `--runtime native --cadence-root /path/to/cadence`, with `--license-file /path/to/license` when needed. `--env-file` sources the supplied environment script in a separate bash process. Do not record licenses, credentials, or complete environments.

Xvfb and `allegro -nograph -symbol package -s` load generated SKILL; `create_sym -p` compiles PSM. `--pcb-product` enables PCB loading verification using a licensed product. Without it, the highest result is `verified_dra_psm_compiled`.

Legacy `spb172` and `--cleanup-ended-session` apply only to matching old-release behavior and require normal completion markers plus geometry readback. A timeout is not success. The normal `native` backend does not apply those treatments. `prepare_spb24.py` creates a job-private launcher copy only when its format checks match; it is not a universal patch.
