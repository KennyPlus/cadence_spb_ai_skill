# Native execution and acceptance

Offline commands use Python 3.9+ standard library on Windows/macOS/Linux. Native commands require an existing Cadence installation and valid license. Linux uses `<cadence-root>/tools.lnx86/bin` with `xvfb-run`; Windows uses `<cadence-root>/tools/bin/*.exe`. macOS prepares offline jobs for transfer without changing global configuration.

Initialize the environment for the actual installation first. On Linux, source `/path/to/cadence-env.sh` in the calling shell or pass `--env-file /path/to/cadence-env.sh` to a `native-*` command. The latter sources it in a child Bash, preserving exported and unset variables before applying job-specific paths and the explicit root. `--cadence-root` or PATH alone cannot replace license/library initialization. Windows must start from an initialized terminal; Bash `--env-file` is unsupported there.

Use a new `--out` directory. Inputs, full SHA-256 inventories, commands, exit codes, timeouts, and logs are retained. Environment scripts are recorded by path/hash without copying them or saving exported values. `--license` overrides inherited/sourced licensing; omission preserves it. Timeout, nonzero exit, and missing outputs fail. Keep failed jobs as evidence instead of reusing them as new runs.

Examples require actual paths/root. Resolve release/product differences from installed batchhelp/native docs. Calls are based on SPB 24 documentation and still need target native validation.

## PST import

```sh
python3 scripts/pcb.py native-import /path/to/sch/allegro --seed /path/to/board-template.brd --library /path/to/compiled-library --cadence-root /path/to/SPB --env-file /path/to/cadence-env.sh --out /path/to/jobs/import-01
```

Repeat `--library` as needed. Only immediate `.psm/.pad/.ssm/.fsm` files are copied; conflicting same-name contents fail. Every PST `JEDEC_TYPE` needs a matching PSM. A seed can carry real outline/stackup/rules; omission requests a new board without inventing those requirements.

The helper calls `netrev -e -i netlist seed.brd imported.brd`, or `-n new.brd imported.brd` without a seed. PST does not use Telesis `netin`. Recognized constraint companions are copied, not silently dropped. Options disabling DRC, ignoring FIXED, or ripping etch are not used. Job `ALLEGRO_PCBENV` holds isolated library configuration without modifying user pcbenv.

Import automatically runs `report -v cpn` and compares every logical component, physical pin, and net name with `netlist.json`. Missing connections, wrong nets, and extra/missing pins fail. Reports also require a working license environment. Separately verify actual footprint versions. Obtain existing library dependencies first; use dedicated pad/package skills when genuinely required and available. Placeholder rectangles are not production footprints.

## Placement import and readback

```sh
python3 scripts/pcb.py native-place /path/to/imported.brd --plan /path/to/placement-plan.json --netlist /path/to/netlist.json --baseline /path/to/baseline.json --library /path/to/compiled-library --cadence-root /path/to/SPB --env-file /path/to/cadence-env.sh --out /path/to/jobs/place-01
```

The model is rechecked before `plctxt -r -m source.brd placed.brd place_txt.txt`; exported `actual.txt` is then compared. Unplaced components need libraries supplied through repeated `--library`; netlist import does not necessarily embed every footprint. Moves of already embedded footprints can omit it. `-m` allows moving unfixed parts; the helper does not use `-z` to ignore FIXED or `-s` to save errors. Mechanical/format symbols are outside this exchange. Source boards remain intact.

Component Pin reports are also compared after placement to catch correct positions with lost connectivity. Apply `fixed` intent separately, for example `axlDBAddProp` on actual component/symbol dbids and `axlDBIsFixed` readback, without clearing existing locks. Then read physical pin XY, net, and padstack to verify asymmetric rotation/mirroring, actual outline, keepouts, and courtyards. Bounds and placement text cannot replace this step.

## Router batch execution

Persist/read back board constraints as in [routing.md](routing.md), then export `.dsn` and `_rules.do` with native `specctra_out`. Export/import uses Editor dialogs. Do not guess version-specific form replay fields; consult current documentation and record/verify the target replay or use an already verified integration.

```sh
python3 scripts/pcb.py native-route /path/to/native-export.dsn --rules /path/to/native-export_rules.do --plan /path/to/routing-plan.json --netlist /path/to/netlist.json --cadence-root /path/to/SPB --env-file /path/to/cadence-env.sh --out /path/to/jobs/router-01
```

The helper checks selected physical pin sets and layers, copies inputs, loads reviewed export rules, applies explicit model net rules, and runs `specctra source.dsn -do route.do -nog -quit`. Only requested groups run, saving `stage_XX.ses` and `routed.ses`. The rules file must come from the same export. Review references inside it; generate self-contained native rules rather than dropping dependent files.

Success means a candidate session. Import is not automatic and board constraint persistence is not claimed. Recheck the source board hash before import. If needed, adjust the session's base-design path to a controlled copy with identical content, then use `specctra_in` and save a new result. Check every stage's connectivity, conflicts, protection, and final rules, not just session existence.

## Native reports and delivery

```sh
python3 scripts/pcb.py native-report /path/to/result.brd --report net --report ucn --report drc --report drc_shorts --report elw --report vialist_net --cadence-root /path/to/SPB --env-file /path/to/cadence-env.sh --out /path/to/jobs/readback-01
```

Reports use `report -v CODE source.brd CODE.txt`. Update DRC in Editor and save the actual candidate first; offline reports do not force all dynamic checks to recompute. Read logs and report bodies for skipped checks, conversions, and missing libraries.

Deliver source hashes, requirement evidence, placement, routing groups/rules, execution logs, native reports, and an accepted board or explicitly labeled candidate. Distinguish text generation, model geometry, native logical/physical readback, DRC, and critical electrical acceptance. A generated file or candidate is not a completed board.

## Installed documentation

Consult `share/pcb/batchhelp/{netrev,plctxt,report}.txt`, `doc/scoms/{specctra_out,specctra_in}.html`, `doc/algroskill/18consmgt.html`, and `doc/spcmdref/ROcmds{R,S,P,U,W}.html` for exchange, reports, CSet rules, selections/protection, routing rules, and session semantics. Current documentation and current readback take precedence over historical runs.
