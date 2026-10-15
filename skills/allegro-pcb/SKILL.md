---
name: allegro-pcb
description: Import Cadence PST netlists, have the model plan PCB placement from schematics and engineering requirements, check and generate Allegro placement files, and turn interactive width/clearance requirements and critical-net priorities into routing groups with native batch execution and readback. Use for PCB placement/routing, not pad, package, or schematic library creation.
---

# Allegro PCB

The model makes engineering decisions. Helpers read/write data, check explicit constraints, and invoke native tools; they do not infer component functions, place parts automatically, or select critical nets. When requirements change, update the evidenced plan, check conflicts, and rerun affected steps.

## Choose the workflow

- Netlists and placement: read [placement.md](references/placement.md); examples are in `assets/example-netlist/` and `assets/placement-example.json`.
- Width/clearance and critical-net routing: read [routing.md](references/routing.md); see `assets/routing-example.json`.
- Native import/placement/Router/readback: read [runtime.md](references/runtime.md). Run `python3 scripts/pcb.py --help` relative to this skill directory.

## Model workflow

1. Read the current netlist, schematic, package geometry, outline/stackup, and requirements. Separate confirmed evidence from open questions. Schematic coordinates are not PCB coordinates; references and net names alone do not establish function.
2. Propose placement using signal flow, power/return paths, decoupling targets, connector orientation, mechanical anchors, isolation/keepouts, thermal needs, and manufacturability. Preserve fixed parts and accepted routes. Consult device documentation for electrical requirements; unverified dimensions are not confirmed constraints.
3. Express checkable decisions in JSON: position, rotation, side, bounds, pins, distance/direction rules; or explicit nets, widths, clearances, priorities, and rationale. Preserve complex requirements for native Constraint Manager/DRC rather than reducing them silently to simple spacing.
4. Run checks, inspect errors/SVG, and revise the model plan. Helpers do not move components to repair conflicts. Explain actual contradictions; clarify only missing information that affects engineering decisions.
5. For native work, source the environment for the actual installation or pass `--env-file`; installation root alone is insufficient. Work on isolated copies and compare native readback with the imported netlist and constraints. Verify critical nets, rules, and protection before ordinary nets. Continue within existing authorization.

## Result meanings

- `parsed` / `generated_only`: text read or generated.
- `checked_model`: explicit geometry/rules passed offline checks, not native DRC or electrical acceptance.
- `native_import_candidate`: board generated and every component pin's logical net compared; package geometry/properties still need readback.
- `native_route_candidate`: Router produced a candidate session requiring import and readback.
- `native_placement_matched`: native exported component/package/position/rotation/side and logical pin-to-net assignments match. Actual pin geometry, routed continuity, FIXED, outline, and DRC remain pending.

Helpers retain `native_verified: false` and list pending checks. Report exactly what passed. Without a usable native environment, deliver generated data and pending items. Exit codes, file existence, disappearing ratsnests, or one statistic cannot establish full-board acceptance.

Use a fresh `--out` directory and retain input hashes. References inform formats but do not enter the published skill. Offline checks cover orthogonal rotations, rectangular package occupancy, simple outlines, and side-specific keepouts. Arbitrary angles, holes, complex courtyards, differential/length/impedance rules, and special vias require model-led native work.
