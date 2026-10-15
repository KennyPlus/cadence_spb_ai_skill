# Netlists and placement

## Inputs and commands

```sh
python3 scripts/pcb.py netlist /path/to/sch/allegro --out /path/to/jobs/netlist-01
python3 scripts/pcb.py placement /path/to/placement-plan.json --netlist /path/to/jobs/netlist-01/netlist.json --out /path/to/jobs/placement-01
python3 scripts/pcb.py read-placement /path/to/place_txt.txt --out /path/to/jobs/read-01
python3 scripts/pcb.py verify-placement /path/to/placement-plan.json /path/to/native-place.txt --out /path/to/jobs/compare-01
```

`netlist` reads `pstchip.dat`, `pstxprt.dat`, and `pstxnet.dat` from one directory, retaining components, physical pins, connections, properties, and SHA-256 hashes of the files and constraint companions. UTF-8/BOM is the default; specify actual older encodings with `--encoding gb18030`, for example. Do not guess encodings or replace corrupt characters. Compressed `pstdedb.cdsz` alone is unsupported; obtain a native traditional PST export rather than renaming it.

External CM companions are inventoried and copied for native import; Python does not decode their electrical constraints. `XY`, `SCH_LOC`, and `SCH_ORIENT` describe the schematic, not PCB placement. Multiple-net pins, missing mappings, and duplicate references fail. Distinct components must not share `SECTION_NUMBER` hierarchy paths; `NODE_NAME` paths must belong to the corresponding reference, or native import can silently lose connections. Unconnected physical pins remain inventoried.

## Model-led placement

Establish origin, units, outline, stackup/sides, fixed mechanical anchors, connector exits, and package origins. Use schematics/documentation to identify functional blocks, power/return paths, decoupling, oscillators, and feedback. Minimum nearest-neighbor wire length is not a universal circuit objective.

Express fixed coordinates, exclusions, functional spacing, pin/component distances, and directions as checks. Keep requirements outside the schema for native verification. Satisfy hard constraints before optimizing length, routing channels, and maintainability; do not quietly relax them.

### Placement schema 1

See `../assets/placement-example.json`. Misspelled/unknown fields fail.

| Field | Meaning |
| --- | --- |
| `schema`, `units`, `accuracy`, `basis` | `1`, `mm` or `mil`, decimal precision `0..6`, engineering evidence; all dimensions share the unit |
| `board.outline` | Simple closed polygon with repeated first/last point; represent holes as keepouts and check them natively |
| `board.edge_clearance` | Minimum package occupancy bounds to board edge |
| `board.component_clearance` | Minimum same-side package bounds spacing; through parts occupy both sides |
| `board.keepouts[]` | `{name,polygon,sides,basis}`, sides drawn from `top`/`bottom`; touching also fails |
| `footprints[SYMBOL]` | `{bounds:[xmin,ymin,xmax,ymax],pins:{"1":[x,y],...},through,basis}`, local to package origin |
| `components[]` | `{refdes,symbol,xy:[x,y],rotation,side,fixed,role,basis}`, rotation `0/90/180/270`; every logical part appears |
| `rules[]` | `{kind,from,to,min,max,basis}`, endpoint `{refdes,pin?}`; absent pin means package origin |

`kind` is Euclidean `distance`, signed `delta_x`, or signed `delta_y` (to minus from). Combine displacement limits for direction/channel requirements, with evidence for both limits.

Rectangle bounds must conservatively cover the actual courtyard/assembly occupancy, not only body/silk while hiding pad collisions. Opposite-side overlap is only a 2D allowance; check thickness, holes, height, and assembly. Bottom-side coordinates mirror local X first, then rotate counterclockwise in top view. Calibrate asymmetric footprints using native physical pin coordinates, not bounds alone.

`--baseline baseline.json` accepts `{units,components:[{refdes,symbol,xy,rotation,side,fixed},...]}` derived from current native positions and FIXED states. Moving, rotating, flipping, changing symbols, or unfixing locked parts fails. Without a baseline, `fixed:true` is only intended state. Native `plctxt` preserves existing FIXED, but placement text does not carry that property; apply and read back new fixed states separately.

Successful output includes `plan.json`, `netlist.json`, `place_txt.txt`, `placement.svg`, and `result.json`. Geometry failures return nonzero and do not emit an importable placement.

## Allegro placement exchange

```text
VERSION = 2.0
UUNITS = MILLIMETERS
# refdes ! symbol_x ! symbol_y ! rotation ! mirror ! symbol_name ! embedded_layer
R1 ! 8 ! 10 ! 0 !  ! DEMO_R !
R2 ! 16 ! 10 ! 180 ! m ! DEMO_R !
```

Exactly seven columns, with an optional empty last field. Empty mirror means top, `m` bottom; negative coordinates are allowed. `MILS` is supported with exact decimal conversion `1 mil = 0.0254 mm`. Coordinates use symbol origin: do not add `plctxt -c` (body center) or `-p` (pin 1). Embedded layers, older formats, and arbitrary units are not guessed.

`verify-placement` compares text sources without proving they came from Cadence. `native-place` runs native import/export in a new job and compares the result. Insufficient-precision rounding is not approximately correct: increase native accuracy or explicitly quantize the model and repeat.
