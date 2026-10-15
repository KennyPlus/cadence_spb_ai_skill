# Portable schematic model

The Python 3.9+ tool uses only the standard library. Generation, checks, and previews do not require Cadence, a license, a display, a browser, or a Windows connection. Each command requires a new output directory. Run paths relative to this skill directory, or use their absolute equivalents.

```sh
python3 scripts/schematic.py check assets/design-example.json --library assets/library-example.xml --profile assets/profile-example.json --out jobs/check-01
python3 scripts/schematic.py build assets/design-example.json --library assets/library-example.xml --profile assets/profile-example.json --template assets/template-example.xml --out jobs/build-01
python3 scripts/schematic.py check-xml jobs/build-01/DEMO_DIVIDER.xml --profile assets/profile-example.json --grid 10 --out jobs/xml-check-01
python3 scripts/schematic.py preview jobs/build-01/DEMO_DIVIDER.xml --profile assets/profile-example.json --grid 10 --out jobs/preview-01
python3 scripts/schematic.py inspect jobs/build-01/DEMO_DIVIDER.xml --out jobs/inspect-01
```

`build` checks the plan, serializes Design XML, reconstructs its physical pin-to-net graph from the actual XML, compares that graph with the plan, and emits XML, page SVGs, a self-contained `preview.html`, expected netlist data, model PST files, hashes, and `result.json`. It neither emits a DSN nor includes/executes a GUI launcher. Model errors return nonzero and prevent XML/PST generation. Model PST is an offline planning artifact, not a Capture export.

`check-xml` and `preview` read the supported flat XML dialect directly, using its embedded library cache and a supplied pin-type profile; they do not need the original plan or library file. They validate cache/graphic references, root identity, instance attributes, physical pin mapping, explicit NCs, aliases, junctions, geometry, and offline electrical rules. `preview` writes SVG and HTML files without opening them. A changed XML value, pin, or wire changes the check/preview input; an old plan cannot conceal it. Use the actual design grid, whose default is 10 database units.

Successful results use `checked_xml`, `execution: headless`, and `native_execution: not_requested`. Native checks are listed separately under `native_checks_not_run`, not as blockers for this deliverable. Geometry/electrical errors return `xml_errors` and exit code 2; a preview may still be written to help locate them. Unsupported or malformed XML fails rather than producing a misleading preview. `inspect` remains a broader inventory-only reader, including for native-exported XML that contains objects outside the checked authoring dialect.

## Inputs

| Field | Meaning |
| --- | --- |
| `schema`, `name`, `root`, `units`, `grid` | `1`, design identifier, root schematic identifier, `capture_db`, positive integer grid |
| `sources[]` | `{location, basis}` documenting the requirements and device evidence |
| `pages[]` | `{name, size:[width,height]}` in Capture database coordinates |
| `parts[]` | `{refdes, package, page, at:[x,y], value, footprint, basis, no_connect}` |
| `parts[].no_connect[]` | `{pin, basis}` for explicitly reviewed NC pins; pin numbers are strings |
| `nets[]` | `{name, page, nodes:[[refdes,pin],...], wires:[[[x1,y1],[x2,y2]],...], basis}` |

Unknown fields and duplicate JSON keys fail. All positions are integer Capture database coordinates, not mm, mil, or GUI display inches. Rotation/mirroring are deliberately absent from schema 1; do not silently ignore such requested transformations. The library supplies pin hot points and body bounds. Only one normal-view unit per package, explicit visible non-global scalar pins, and complete physical pin mappings are supported. The profile maps Capture pin-type integers to names and records its evidence. Reuse supplied or previously evidenced profiles for offline work; do not launch Capture to probe one. Example values are demonstrations and carry that limitation.

Every physical pin must be assigned once, either to a named net or an explicit NC. Nets need at least two physical nodes and one connected wire graph. Branches and crossings within the same net need explicit XML junctions. Distinct nets may not touch or cross in this model, even where the native editor could represent an unconnected crossing. Reroute them or extend the offline representation/validator. Cross-page electrical connections are outside the current helper's coverage; do not switch to GUI execution automatically.

The checker detects missing/duplicate pins, multi-net assignments, inappropriate connections to library NCs, off-grid/out-of-page geometry, symbol overlap, broken wire graphs, dangling endpoints, unintended pin contact, distinct-net contact, and multiple push-pull outputs. It flags undriven inputs and conditional drivers for review. It does not calculate electrical operating points, prove voltage compatibility, apply the full Capture ERC matrix, reproduce all symbol graphics, or replace native DRC. SVG/HTML shows simplified body bounds, physical pins, wires, junction dots and NC markers; it has no remote assets or scripts.

The input template must be an empty single-page flat Design XML with `Defn`, `PageSizeInfo`, and optional supported page metadata; its single cache must be empty. Duplicate caches/default blocks, non-primitive defaults, hierarchical library links, pin swapping/sharing, and unmodeled library user properties (including population/PSpice-only settings) fail. Only `AgentElectricalRole` and `AgentEvidence` pin metadata are accepted as user properties; they do not change native ERC. Unsupported objects fail instead of disappearing. Prepare a dedicated minimal template if needed; do not strip these semantics from an existing project to force compatibility.

Design/root/page identifiers start with a letter or underscore and then use letters, digits, underscores, dots, plus, or minus. Scalar net names, physical pin numbers, and footprint names use those characters without the leading-letter requirement, so `3V3` and `+3V3` work. Bus expressions and hierarchy syntax are outside the current checked dialect and need additional offline handling. References are annotated uppercase letters followed by digits.

## Compare a native netlist

This is optional native evidence, outside the default XML-only deliverable. Reading existing PST files remains headless; generating DSN or launching Capture follows the explicit DSN request gate in `SKILL.md`.

After a real Capture export, parse its PST directory using the installed `allegro-pcb` skill:

```sh
python3 ../allegro-pcb/scripts/pcb.py netlist /task/native-pst --out /task/native-pst-readback
python3 scripts/schematic.py verify-netlist assets/design-example.json --library assets/library-example.xml --profile assets/profile-example.json --actual /task/native-pst-readback/netlist.json --out /task/compare-01
```

The second command checks the exact component set, footprint names, complete physical pin inventory, and named pin-to-net graph, including the absence of connections on NC pins. It does not authenticate where the supplied snapshot came from. Retain the native export log, DSN hash, settings, and PST hashes to establish provenance. Values, occurrence properties, symbol graphics, and constraints need their own native XML/property readback.

## Review native DRC reports

```sh
python3 scripts/schematic.py drc-report /task/design.drc --encoding utf-8-sig --out /task/drc-review-01
```

This extracts common `ERROR(ORCAP-...)` / `WARNING(ORCAP-...)` lines and keeps their line numbers. It intentionally returns `report_findings_only` and `completion_verified: false`. Localized or other report formats may not match. Read the entire report and native session log; zero extracted lines, empty marker lists, or zero errors under disabled rules must never be reported as a passing DRC run.
