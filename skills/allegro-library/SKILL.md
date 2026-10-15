---
name: allegro-library
description: Inspect existing Cadence PAD/DRA files in batch, export pXML and object snapshots, reconstruct SKILL/replay, and create single-contour copper SSM or windowed paste FSM with native geometry round trips. Python preparation works on macOS/Linux/Windows; native execution requires Linux/Windows Cadence.
---

# Allegro Library

Use for library extraction and Shape/Flash design. Source documents and libraries are read-only; work in a new job directory. This workflow does not recover editing history or treat component terminals as recommended PCB lands. First review copper, soldermask, and paste with the `allegro-padstack` layer workflow. Keep unresolved manufacturing requirements explicit.

## Inspect an existing file

Paths are relative to this skill directory:

```bash
python3 scripts/library.py prepare /path/input.pad --out /path/new-job
python3 scripts/library.py run /path/new-job --cadence-root /path/to/cadence
```

DRA uses the same `prepare` command. Add `--license-file /path/existing-license` when needed. See [execution and delivery](references/runtime.md). Preparation needs only the Python standard library and does not start Cadence. Jobs use relative internal paths for transfer. An existing `native` directory prevents another run; retain failed evidence and create a new job.

- PAD: native `padstack_editor -xo` exports `export.pxml`; `-x` rebuilds the PAD and the workflow compares complete native reports. Binary strings are not dimensional evidence.
- DRA: native SKILL produces `snapshot.json`, then `rebuild.il` / `rebuild.scr`; rebuild from an empty symbol, reopen for readback, and compile PSM/SSM/FSM natively.
- The `.scr` is a newly constructed replay entrypoint, usually loading `.il`. Original clicks and undo history cannot be recovered from DRA.
- Read the actual `result.json`. `verified_pad_roundtrip` and `verified_dra_geometry_roundtrip` cover different checks; an XML or DRA file alone proves neither.

## Copper shapes, soldermask, and paste

Create the copper contour, produce a Shape DRA, compile SSM with `create_sym -s`, then reference it as PAD `SHAPE_SYMBOL`. Regular custom copper must be one solid ETCH contour without holes. Do not force disconnected copper or holes into one SSM. Independent paste windows use FLASH DRA and `create_sym -t` to produce FSM; paste need not match copper.

The [synthetic L-shape example](assets/shape-example.json) contains no source library data.

```bash
python3 scripts/library.py design /path/shape-spec.json --out /path/new-shape
python3 scripts/library.py design /path/shape-spec.json --out /path/new-native-shape --execute --cadence-root /path/to/cadence --license-file /path/existing-license
```

`type=shape` accepts one closed polygon; `type=flash` accepts one or more closed windows. Declare `units`, `accuracy`, and `sources`. Forward JSON supports straight contours; reverse DRA extraction also supports native arcs.

For new copper, add `measurement:{"basis":"measurement source"}` to center its bounding box. Soldermask/FLASH must reuse the copper frame through `measurement.copper_bounds:{"min":[x1,y1],"max":[x2,y2]}`; never center FLASH independently on its windows. `coordinate-transform.json` records the translation. Propagate origin changes to PAD references and package pin compensation. Reverse extraction and older specifications without `measurement` preserve their original coordinates.

## Verification boundaries

Supported reconstruction covers pin mappings/positions/rotations, line/arc paths, solid shapes without holes, text fonts/positions/alignment, `PACKAGE_HEIGHT_MAX`, and actual top/bottom copper/mask/paste polygons. Unsupported objects prevent reconstruction while preserving the original snapshot.

Arbitrary properties/constraints, 3D, editing history, and pin-number annotation style are not preserved. Mirrored/mechanical pins, dynamic/hatched/holed shapes, and unsupported line fonts are rejected. Geometry verification is not manufacturing approval. Derive dimensions from the actual documentation and process; historical window counts or coverage percentages are not universal rules.

Package external SSM/FSM dependencies using repeated `prepare --symbol` arguments; missing dependencies fail. For initial custom-shape acceptance, place pins in original and rotated orientations, then use `axlPolyFromDB` to compare actual layer vertices, area, arc radii, and holes. PAD report width/height alone is insufficient.
