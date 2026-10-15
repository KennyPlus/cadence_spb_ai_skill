# Package specification v1

Required top-level fields are `schema=1`, `name`, `units`, `accuracy`, `sources`, `padstacks`, `pins`, `outlines`, `place_bound`, `texts`, `text_style`, and `silk_clearance`. Unknown fields fail. Dimensions share the top-level unit; coordinates use a top view with X right and Y up.

- `name`: lowercase initial letter followed by letters/digits/underscores; at most 31 characters.
- `units`: `mm` or `mil`. `accuracy`: 2..4 for mm, 0..4 for mil. Values must be exactly representable; nonfinite numbers, booleans, and absolute values above 10000 fail.
- `sources`: nonempty array of nonempty `location` and `basis`, optionally `path`. Record pages/views, derivations, and process choices.
- `padstacks`: maps pad names to absolute paths of actual `.pad` files. Every listed pad must be used. Copy only required files; do not search or modify source libraries.
- `pins`: 1..1000 entries of `number` (string), `padstack` (mapping key), `xy:[x,y]`, and `rotation:0|90|180|270`. Numbers allow letters/digits/underscores, at most 16 characters, with case-insensitive uniqueness. Coincident pins are unsupported.
- `outlines`: nonempty array of `layer`, `width`, and `points:[[x,y],...]`. Supported layers are `PACKAGE GEOMETRY/ASSEMBLY_TOP` and `PACKAGE GEOMETRY/SILKSCREEN_TOP`; assembly is required. At least two points per polyline; repeat the first to close it. Zero-length segments fail.
- `place_bound`: `min:[x,y]`, `max:[x,y]`, and `height`. Produces a filled `PACKAGE GEOMETRY/PLACE_BOUND_TOP` rectangle and `PACKAGE_HEIGHT_MAX`; no default courtyard is added. Native pin bounds must fit inside.
- `texts`: entries of `layer`, `text`, `xy`, and `rotation`. Supports those geometry layers and `REF DES/ASSEMBLY_TOP` / `REF DES/SILKSCREEN_TOP`. Text is centered, not mirrored. Require at least one reference with uppercase prefix and one `*`, such as `U*`; both reference layers must match.
- `text_style`: explicit `width`, `height`, `line_space`, `char_space`, and `stroke`. Create and read back a dedicated text block rather than using database defaults. Pin numbers use it but are excluded from manufacturing silk checks.
- `silk_clearance`: nonnegative. Native pin bounds, including mask geometry, are obstacles. Line clearance subtracts half the stroke width; text uses actual glyph bounds. This conservative check can reject circular-pad corners more strictly than exact mask-polygon DRC.

External shape/flash mappings are not accepted. Missing dependencies fail native loading/readback; do not silently satisfy unknown dependencies from global libraries. Use verified basic PADs or extend the protocol and verification explicitly.

`verify spec.json readback.txt` checks supplied geometry but does not run Cadence or prove PAD provenance. Full `build --execute` also exports embedded PADs and compares their native reports with sources.

## Automatic measurement-origin centering

Normalize measurements to the specification unit and top-view axes, then add:

```json
"measurement": {
  "basis": "PDF body dimensions measured from the lower-left datum",
  "body_bounds": {"min":[9,19], "max":[11,21]},
  "pad_origin_shifts": {"pad_name":[0.1,0.2]}
}
```

Without `body_bounds`, use ASSEMBLY_TOP outline vertices, excluding stroke width, pin-1 marks, text, silk, and placement margin. Ensure that layer contains only the intended body outline, or supply explicit bounds. Center `C=(min+max)/2` is a bounding-box center, not an area centroid or average pin location.

Optional `pad_origin_shifts` gives each new PAD origin in the old PAD local frame, usually the pad centering result's `source_center`. Omit it when already centered to avoid double compensation. Keys must exist in `padstacks`; actual PADs must already have the corresponding centered geometry. Historical PADs are not modified.

`new_pin = old_pin + R(pin_angle) * PAD_origin_shift - C`. Subtract C from outlines, text, and placement bounds. At 0/90/180/270 degrees, rotate `(dx,dy)` to `(dx,dy)`, `(-dy,dx)`, `(-dx,-dy)`, and `(dy,-dx)`. Pin numbers, angles, sizes, and heights stay unchanged. PADs preserve internal copper/mask/paste relative positions.

`input-spec.json`, `spec.json`, and `coordinate-transform.json` retain the original, normalized specification, and per-pin transforms. Normalization removes `measurement` to prevent applying it twice. Unrepresentable half-grid coordinates fail rather than rounding. Older inputs without `measurement` preserve coordinates.
