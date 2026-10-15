# Portable preparation and native execution

The Python standard library supports preparation and text generation on macOS/Linux/Windows. Native adapters use Linux `tools.lnx86/bin` or Windows `tools/bin/*.exe`; verify the actual release on each machine. This skill provides no native macOS backend.

`prepare input.pad --out new-job` creates a transferable job. Transfer the job and skill scripts to the Cadence machine, then use `run new-job --cadence-root /path/to/cadence`. Specify an existing license with `--license-file` if needed. Inputs and dependencies remain read-only; helpers neither connect to workers nor store credentials.

Linux editors use Xvfb and `-nograph` batch execution without desktop input, but retain X dependencies. Windows does not use Linux compatibility libraries. Timeouts fail; process cleanup is restricted to the current job.

DRA reconstruction compares the declared geometry scope, not editing history, arbitrary properties, constraints, or 3D. Check origins and actual layer polygons of `dump_libraries` dependencies. Equal area or bounds do not excuse positional shifts. PAD pXML round trips also compare layer definitions and hole properties; retain differences and fail.

Deliver specifications, coordinate transforms, SSM/FSM dependencies, scripts, native logs, readback, and result hashes. Generated jobs are not repository payload.
