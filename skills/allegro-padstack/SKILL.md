---
name: allegro-padstack
description: Create Cadence Allegro padstacks from PDFs, dimensioned images, CAD, or explicit dimensions; generate pXML or Padstack Editor replay, build PAD files in batch, and verify native readback. Use for pad libraries, not DRA packages or BRD PCB design.
---

# Allegro Padstack

Identify PCB lands, units, view, and dimensional evidence first. Documents and existing libraries are read-only; generate into a new directory. Supported geometry includes top SMD, plated through holes, and non-plated mounting holes with copper lands, using circles/squares/rectangles. See the [specification](references/specification.md).

## From inputs to specification

Read [layer intent](references/layer-intent.md) to review copper, mask, and paste independently. Use `allegro-library` for custom SSM/FSM; the simple-geometry limits of `padstack.py` still apply.

- PDF: use `pdftotext -layout`, then `pdftoppm` as needed to check dimension lines, pin 1, and recommended lands. Use the PDF skill when layout matters.
- Images: read explicit annotations; do not estimate dimensions from unscaled pixels.
- CAD: verify format/units and use a suitable entity/dimension parser or valid DWG/STEP converter. Distinguish body, terminals, and PCB lands.
- Record pages/layers/annotations, derivations, and process choices in `sources`. The helper consumes reviewed data; it does not perform general OCR or infer packages. List missing dimensions and finish independently evidenced pads where possible.
- Supply mask/paste geometry or explicit `null`; no hidden expansion defaults. Annular rings, hole tolerances, fabrication, and stencil rules come from current requirements, not examples.

New designs center the PAD on the BEGIN copper bounding box. Supply measured coordinates through `measurement`; the generator computes relative layer offsets. Do not center mask/paste independently. See [automatic centering](references/specification.md#automatic-measurement-origin-centering).

## Generate and execute

Paths are relative to this skill directory. Prepare reviewable artifacts first:

```bash
python3 scripts/padstack.py build /absolute/spec.json --out /absolute/new-output
```

After reviewing [runtime requirements](references/runtime.md), execute with options appropriate to the target release:

```bash
python3 scripts/padstack.py build /absolute/spec.json --out /absolute/new-run --execute --backend replay --cadence-root /path/to/cadence --display xvfb --compat-172 --cleanup-mainwin-exit --timeout 30
```

`--display none` clears display variables. Xvfb uses an isolated display and replay without desktop input, but retains X dependencies. Compatibility options apply only to matching Linux 17.2 behavior; do not modify installations/system libraries. Resolve sandbox restrictions through the host approval mechanism rather than treating them as format failures.

Newer XML workflows use `--backend xml`; verify `-x/-xo` on the actual release first. 17.2 P19 lacks the required conversion interface. The XML backend generates SMD pXML; native report semantics, not XML existence, determine acceptance.

## Acceptance and limits

Deliver PAD, specification, replay/pXML, `readback.txt`, logs, and `result.json`. `verified` means normal native exit and matching readback. `verified_with_exit_cleanup` means the explicitly enabled compatibility path terminated an old MainWin process after its normal end journal, with matching readback; disclose that cleanup. `generated_only` is text preparation. `verified_geometry_process_failed` is matching geometry with a failed/timed-out process, not a clean run. Preserve failed evidence and retest in a new directory.

Nonzero SMD layer offsets require XML. Replay offsets, eccentric holes, slots, microvias, backdrill, thermal pads, and antipads are unsupported. Delegate SHAPE_SYMBOL/FLASH to `allegro-library`; bounds cannot replace actual contours.
