# From documentation to copper, mask, and paste

Confirm document revision, package suffix, units, pages, view, pin 1, and datum. Distinguish terminals from recommended PCB lands. Record bottom-view to PCB top-view transformations. Preserve MIN/NOM/MAX, BSC, REF, and positional tolerances separately; REF is not a manufacturing tolerance.

Record `location` and `basis` for each decision:

| Layer | Evidence to establish | Assumptions to avoid |
| --- | --- | --- |
| BEGIN/INTERNAL/END copper | Lands, terminal/solder dimensions, tolerances, electrical pin grouping, contour, origin, offset | Terminals equal PCB pads; every NC is open; adjacent identical pins can be merged |
| SOLDERMASK | SMD/NSMD, aperture/expansion/web requirements, relation to copper | All layers are equal; an old aperture is a vendor requirement |
| PASTEMASK | Stencil/process conditions, reduction, windows, spacing, total area/coverage | Universal reduction percentage/window count; windows automatically reuse copper shapes |

Identify choices as documented, calculated from explicit dimensions, inherited from specified project processes, or unresolved. Explicit user process rules may fill missing mask/paste requirements. Otherwise complete evidenced layers and list unresolved items instead of presenting an unqualified production PAD. Historical libraries are implementation/comparison evidence, not manufacturing standards.

Use `allegro-library` to build copper SHAPE DRA/SSM, then reference it in PAD. Ordinary custom copper must be one solid contour without holes. Multiple paste windows use separate FLASH DRA/FSM. Mask may use its own SSM or copper SSM according to actual requirements.

Keep Shape origin, PAD layer offset, and package pin position/rotation distinct. Native tools often derive offsets from shape bounds relative to origin; do not apply a translation twice. Place original and rotated pins and compare actual copper/mask/paste polygons, not only width/height.

Deliver layer evidence, unresolved choices, reviewable contours/overlays, all SSM/FSM dependencies, PAD/DRA, scripts, and native readback. The model interprets sources and makes engineering decisions; scripts generate and verify explicit data. Conversion success does not prove correct interpretation.
