---
name: allegro-package
description: Create Allegro PCB component packages from PDFs, dimensioned images, CAD, or explicit dimensions; generate replay/SKILL, build DRA in Package Editor, compile PSM, and reopen DRA to verify pins and geometry. Use allegro-padstack for pads; this skill does not perform PCB placement or routing.
---

# Allegro Package

Extract PCB lands, pin numbering, and view orientation into a reviewable specification. Source documents and existing libraries remain read-only; generate into a new directory. Read the [specification](references/specification.md) and [synthetic SMD example](assets/smd2-example.json).

## From source to specification

Review copper/mask/paste with `allegro-padstack`. Use `allegro-library` for reverse DRA extraction, custom SSM, and paste FSM. Terminal drawings are not recommended land patterns; historical merged pins require electrical justification.

Extract PDF dimensions, then render critical pages to confirm dimension lines and pin 1. Use explicit image annotations, not unscaled pixels. Confirm CAD format, units, and view; use a suitable DXF parser or valid DWG/STEP converter. Distinguish body, terminals, and PCB lands. Convert bottom views to explicit top-view coordinates without guessing pin-number mirroring.

New designs use the body bounding-box center as `(0,0)`, not average pin position or silk/text center. Add `measurement` to translate pins, outlines, text, and placement bounds, and compensate rotated pins for PAD origin changes. Older specifications without it are treated as already centered. Record pages/layers, derivations, pad choices, and mask/paste evidence in `sources`. Missing dimensions remain unresolved; the helper consumes reviewed JSON rather than recognizing arbitrary documents.

`padstacks` must reference real PAD files. Create and verify missing pads first. The generator copies dependencies into an isolated job and compares embedded PADs with source native reports.

## Build

Paths are relative to this skill directory. Read [runtime requirements](references/runtime.md), then run:

```bash
python3 scripts/package.py build /absolute/spec.json --out /absolute/new-job --execute --cleanup-ended-session --timeout 45
```

Without `--execute`, the command generates text and copies PADs but does not create DRA. Do not pre-create `--out`. Use the maintained generator and actual results. Resolve execution restrictions through the host permission mechanism without altering host configuration to bypass it.

Linux uses Xvfb with `allegro -nograph -symbol package -s build.scr`; replay loads generated SKILL. No desktop input is used, but X dependencies remain. Native `create_sym -p` compiles PSM separately.

## Acceptance

Read `result.json`, `dra-check/readback.txt`, and compiler logs. Check pin sets, pad mappings, position/rotation, outlines, `PLACE_BOUND`, height, text/font dimensions, conservative silkscreen clearance, and embedded PAD consistency. Deliver DRA/PSM, specification, replay/SKILL, logs, and readback.

- `generated_only`: scripts and input copies only.
- `verified_dra_psm_compiled`: native DRA readback passed and PSM compiled; PCB loading/placement is not established.
- `verified`: additionally passed native PSM loading with `--pcb-product <available-product>`, requiring a suitable license.
- `failed`: a required step failed; preserve the job and retest a fix in a new directory.

`ended_session_cleanup=true` means an explicitly enabled compatibility path terminated a 17.2 P25 process that remained after task completion, Exit, and Journal end. Disclose this instead of claiming normal native exit.

The generator supports numbered SMD/through-hole pins, 0/90/180/270-degree pin rotations, straight outlines, rectangular placement bounds, and explicit text dimensions. Arcs, arbitrary placement contours, multiple height regions, unnumbered mechanical pins, bottom-side packages, complex shape/flash dependencies, and 3D are unsupported. Geometry/silkscreen checks do not replace datasheet, assembly, or full manufacturing DRC review.
