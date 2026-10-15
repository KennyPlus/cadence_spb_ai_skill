# Cadence Agent Skills

Portable skills for AI-assisted Cadence library, schematic, and PCB work. The model interprets engineering requirements and makes design decisions; scripts prepare files, check explicit constraints, invoke supported native operations, and compare readback.

The repository contains maintained source, English skill documentation, synthetic examples, and portable tests. Reference libraries, datasheets, native designs, licenses, credentials, and machine configuration are excluded from publication.

| Skill | Capabilities |
| --- | --- |
| [allegro-padstack](skills/allegro-padstack/SKILL.md) | Simple PAD pXML/replay, copper-origin centering, layer offsets, native readback |
| [allegro-package](skills/allegro-package/SKILL.md) | DRA/PSM packages, body centering, rotated PAD-origin compensation |
| [allegro-library](skills/allegro-library/SKILL.md) | PAD/DRA extraction and geometry round trips, custom copper SSM and paste FSM |
| [orcad-symbol](skills/orcad-symbol/SKILL.md) | Capture Library XML, physical pin/electrical-role checks, native OLB conversion |
| [orcad-schematic](skills/orcad-schematic/SKILL.md) | Headless Design XML, pin/connectivity checks, SVG/HTML previews; native DSN only on explicit request |
| [allegro-pcb](skills/allegro-pcb/SKILL.md) | PST import, checked placement, interactive widths/clearances, critical-net routing groups and native readback |

## Installation

Python 3.9+ is required; no third-party Python packages are needed. From the repository root:

```sh
python3 scripts/install.py --dry-run
python3 scripts/install.py
```

On Windows PowerShell, replace `python3` with `py -3`.

By default, the installer copies skills to the current user's `.codex/skills`, `.claude/skills`, and `.agents/skills`, without symlinks or administrator privileges. Codex honors `CODEX_HOME` or `--codex-home`. Restart the agent session to refresh skill discovery.

```sh
python3 scripts/install.py --host codex
python3 scripts/install.py --home /path/to/another/user --host all
python3 scripts/install.py --replace
```

Identical copies are skipped. Different copies are rejected unless `--replace` is supplied, which backs them up under the host's `skill-backups/<timestamp>/`. Each skill is staged, hash-verified, and switched separately; a failure restores that skill's prior copy while preserving earlier successful installs. JSON output records destinations and results. The explicit [distribution manifest](scripts/skill-files.json) prevents local extras from entering installations.

## Library workflows

Ask the agent to use the relevant skill and provide engineering sources. Measurement origins use the `measurement` protocol: PAD centers on copper bounds and Package on body bounds; mask/paste retain their position relative to copper.

```sh
python3 skills/allegro-padstack/scripts/padstack.py build skills/allegro-padstack/assets/smd-example.json --out jobs/pad
python3 skills/allegro-library/scripts/library.py design skills/allegro-library/assets/shape-example.json --out jobs/shape
python3 skills/orcad-symbol/scripts/symbol.py build skills/orcad-symbol/assets/power-terminals-example.json --profile skills/orcad-symbol/assets/observed-profile.json --out jobs/symbol
```

These commands prepare text without starting Cadence. Package examples need actual verified PAD paths. Capture enum examples require target runtime probing and review before native use.

## Headless schematic XML, checks, and previews

The [schematic skill](skills/orcad-schematic/SKILL.md) defaults to a fully headless workflow: the model designs the circuit, writes Design XML using reviewed Library XML, checks the actual XML, and produces SVG/HTML preview files. No Capture installation, license, desktop, browser launch, or Windows connection is required. Use existing XML/PDF/PST reference evidence; a binary reference DSN alone does not trigger GUI execution.

Run the synthetic example with Python 3.9+ and the standard library:

```sh
python3 skills/orcad-schematic/scripts/schematic.py build skills/orcad-schematic/assets/design-example.json --library skills/orcad-schematic/assets/library-example.xml --profile skills/orcad-schematic/assets/profile-example.json --template skills/orcad-schematic/assets/template-example.xml --out jobs/schematic
python3 skills/orcad-schematic/scripts/schematic.py check-xml jobs/schematic/DEMO_DIVIDER.xml --profile skills/orcad-schematic/assets/profile-example.json --grid 10 --out jobs/schematic-check
python3 skills/orcad-schematic/scripts/schematic.py preview jobs/schematic/DEMO_DIVIDER.xml --profile skills/orcad-schematic/assets/profile-example.json --grid 10 --out jobs/schematic-preview
```

`build` delivers XML, page SVGs, a self-contained `preview.html`, findings/hashes in `result.json`, expected pin-to-net data, and model PST files. It checks the serialized XML against the plan and renders from the XML. `check-xml` and `preview` need only the XML's embedded cache plus the pin-type profile and grid. They detect cache/instance mismatches, missing pins/junctions, broken wiring, unintended contacts, and supported electrical-rule violations. They never open a GUI or emit a DSN/launcher.

The current checked dialect covers flat scalar designs, explicit visible single-unit pins, zero rotation, and orthogonal wiring. SVG/HTML simplifies symbol bodies while showing physical pins, wires, junctions, and NC markers. Unsupported hierarchy, buses, implicit power, rotations, occurrence overrides, or other objects fail explicitly; they do not cause a GUI fallback. Example parts and enum profiles are synthetic, so engineering review remains separate. See the [offline model and commands](skills/orcad-schematic/references/model.md).

Offline XML delivery is complete after its requested checks and previews. Results record `execution: headless`, `native_execution: not_requested`, and `native_capture_verified: false`; native DRC is not a completion gate. Existing reports and PST files can be analyzed offline, but model PST and offline findings are not native Capture DRC evidence.

**Only an explicit request to generate/save a native DSN enables Capture GUI conversion.** Complete the headless work first, then follow the [native Capture workflow](skills/orcad-schematic/references/capture.md) in a fresh task directory. Native XML import/save/reopen/readback and command-line PST comparison have been exercised on Capture 25.1; full native DRC acceptance is separate. The Tcl bridge remains in the skill for this optional path and is not copied into ordinary XML output.

## PCB placement and routing

The model determines placement and critical-net priority from the schematic, package geometry, mechanical requirements, stackup, and interaction. Helpers check explicit constraints and preserve execution/readback evidence.

```sh
python3 skills/allegro-pcb/scripts/pcb.py netlist skills/allegro-pcb/assets/example-netlist --out jobs/pcb-netlist
python3 skills/allegro-pcb/scripts/pcb.py placement skills/allegro-pcb/assets/placement-example.json --netlist jobs/pcb-netlist/netlist.json --out jobs/pcb-placement
python3 skills/allegro-pcb/scripts/pcb.py route skills/allegro-pcb/assets/routing-example.json --netlist jobs/pcb-netlist/netlist.json --out jobs/pcb-routing
```

These produce placement/SVG and routing groups/Router `.do`. See the [PCB skill](skills/allegro-pcb/SKILL.md) for native import, placement comparison, candidate sessions, and reports. Differential/impedance/length constraints, board rule persistence, session import, and final DRC/electrical acceptance require model-led native work.

## Runtime and acceptance boundaries

Initialize the target Cadence environment before native execution. On Linux, source `/path/to/cadence-env.sh`; PCB `native-*` commands also accept `--env-file`. An installation root or PATH alone does not establish license/dynamic-library configuration.

Installation and offline Python work on Windows/macOS/Linux. Native PAD/Package backends are Linux; library/PCB adapters support Linux and Windows paths. Capture Tcl requires a real Capture interpreter, which is not established merely by finding bundled scripts/XSDs. Supply the actual installation, valid license, and dependencies. Xvfb avoids desktop input but retains X dependencies. The installer does not install Cadence, change global launchers, configure licenses, or connect to workers.

Use each native interface's supported format: Capture Design/Library XML, padstack pXML, PCB PST and placement files, and SKILL/Router commands. XML authoring does not make every Cadence operation desktop-independent or replace native database and rule checks.

Use fresh job directories. Preserve source hashes and distinguish generated text, checked models, native candidates, native readback, and final engineering acceptance. Never promote an existing file, zero exit code, model netlist, or unchecked report count to native acceptance.

## Tests

Repository content must not contain machine identities, personal accounts, LAN
addresses, private paths, credentials, or license data. Use generic examples and
runtime configuration instead. Publish only maintained source, documentation,
synthetic examples, and portable tests; exclude local jobs and Git metadata.
Check tracked files for local IP literals before publication;
include ignored local files with `--all-local` (Git metadata is excluded):

```sh
python3 scripts/check_no_local_ip.py
python3 scripts/check_no_local_ip.py --all-local
```

```sh
python3 -m unittest discover -s tests -p 'test_installer.py'
python3 -m unittest discover -s tests -p 'test_portable.py'
python3 -m unittest discover -s tests -p 'test_regressions.py'
python3 -m unittest discover -s tests -p 'test_pcb.py'
python3 -m unittest discover -s tests -p 'test_schematic.py'
```

Published tests use temporary directories and synthetic inputs without Cadence or private references. Optional local XSD validation uses the installed vendor schemas; those schemas are not distributed. Offline tests do not establish native PAD/DRA/OLB/DSN, placement, or ERC/DRC acceptance.
