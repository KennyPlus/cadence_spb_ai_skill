# Symbol specification and power rules

Use `schema:1` with required `name`, `refdes`, `footprint`, `sources`, `units`, `body`, and `pins`; unknown fields fail. `name` is a safe ASCII library name and `refdes` an alphabetic prefix. Use an empty footprint string when unresolved rather than inventing one. Source `location` identifies file/page/region; `basis` records the evidence.

`units` is `capture_db`, the integer Capture XML coordinate system, not mm/mil. The generator uses observed coordinate conventions, 20-unit pins, and rectangular bodies. `body` is `[x1,y1,x2,y2]`; pin `side` is left/right/top/bottom and `offset` is an absolute coordinate along that edge. Corners and stacked pins are unsupported.

| Pin field | Meaning |
| --- | --- |
| `number`, `name` | Individual physical number and logical name; equal names do not imply equal numbers |
| `role` | `signal_input`, `signal_output`, `bidirectional`, `passive`, `power_input`, `power_output`, `power_return`, `no_connect`, `internal_switch`, `thermal` |
| `capture_type` | Evidenced `INPUT`, `OUTPUT`, `BIDIRECTIONAL`, `3STATE`, `PASSIVE`, `OPEN_COLLECTOR`, `OPEN_EMITTER`, or `POWER` |
| `visible` | Must currently be true |
| `implicit_net` | Must currently be null |
| `no_connect` | True only for a verified unconnected pin with role `no_connect` |
| `side`, `offset` | Separate visible connection position on the unit edge |
| `basis` | Functional/electrical justification, not the pin name alone |

`power_*` requires POWER; `signal_input` requires INPUT. Output roles use OUTPUT/OPEN_COLLECTOR/OPEN_EMITTER/3STATE. Internal switch, thermal, passive, and true NC use PASSIVE while retaining their different roles; only true NC sets the flag. Do not label every pin PASSIVE to work around a missing enum profile.

Generation supports one normal view/physical unit, not multiple units, alternate views, shared pins, hidden power, or stacked pins. Preserve the complete pin table and partitioning intent for multi-unit work instead of faking units or dropping a power unit. `inspect` can read multiple single-PhysicalPart normal-view units; that does not expand generator support.

Profiles use `{schema:1,basis:"runtime evidence and version",types:{"POWER":7,...}}`. Bundled values are partial demonstrations. Obtain a complete mapping from actual Capture `DboValue_*` variables; do not fabricate evidence for an unavailable runtime.
