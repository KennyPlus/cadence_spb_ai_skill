# Padstack specification v1

Top-level fields: `schema=1`, `name` (lowercase initial letter, letters/digits/underscores, at most 31 characters), `kind=smd|thru|mounting`, `units=mm|mil`, `accuracy=0..4`, nonempty `sources`, and `pads`. Sources require `location` and `basis`, optionally an actual `path`; runtime reads source files and records SHA-256. User dimensions without a file belong in `basis`. Relative source paths resolve from the invocation directory; absolute paths are preferable across machines.

Decimal strings are recommended. Reject NaN/Infinity, negative sizes, implicit rounding beyond `accuracy`, and unknown fields. Hole tolerances are nonnegative; `minus` is the subtracted amount. All dimensions use the top-level unit.

Each pad is `{ "shape": "rectangle|circle|square", "width": "0.2", "height": "0.6" }`. Circle width/height are its diameter; square values are its side length. General rotation/thermal/antipad geometry is unsupported. SMD requires exactly `begin`, `mask_top`, and `paste_top`; mask/paste may be explicit `null`, but begin cannot. New templates clear bottom pad/mask/paste.

Through/mounting holes require `begin`, `internal`, `end`, `mask_top`, `mask_bottom`, `paste_top`, and `paste_bottom`. Copper cannot be null; other layers can. Also provide `drill={"diameter":"0.8","plating":"plated|non_plated","plus":"0.05","minus":"0.05","symbol_diameter":"0.4"}`. `symbol_diameter` is the circular legend, explicitly supplied to avoid save warnings, not tool diameter. `diameter` is the finished hole size. Copper must exceed the maximum hole, but the checker does not invent a minimum annulus. Project PTH/NPTH rules still apply.

SMD pXML uses `padstacks/padstack version=1.0`, `SMD_PIN`, and `REGULAR_PAD`, based on observed native exports. Through holes use replay rather than unverified XML fields. The synthetic 0.2 by 0.6 mm example's equal mask/paste sizes illustrate format, not production recommendations.

## Verification

```bash
python3 scripts/padstack.py verify spec.json readback.txt
```

Supply an actual `report -v pad name.pad readback.txt` export. Every populated layer must match; extra conductive layers and external shape/flash dependencies fail. Hashes establish identity and geometry checks establish semantics; neither replaces the other.

On 17.2 P19, `thru` is plated Thru Pin. Non-plated holes use `kind=mounting` / Mounting Hole. Mounting still requires three explicit copper lands and two nullable mask layers; bare mechanical holes are unsupported. Usage must match the report.

## Automatic measurement-origin centering

New designs use the copper bounding-box center, not area centroid. Existing inputs without `measurement` preserve coordinates. First normalize units and top-view X-right/Y-up axes; centering translates without guessing mirroring or image scale.

```json
"measurement": {
  "basis": "PDF page 6, lower-left datum, specification units",
  "layer_centers": {
    "begin": [10, 20],
    "mask_top": [10.025, 20],
    "paste_top": [10, 19.975]
  }
}
```

Every present layer requires a center. Alternatively, `layer_bounds` maps each layer to `{"min":[x1,y1],"max":[x2,y2]}`; calculate centers and check bound sizes against the specification. Do not mix forms or include absent layers. Here copper becomes `(0,0)`, mask offset `(0.025,0)`, and paste offset `(0,-0.025)`, preserving sizes.

Outputs include `input-spec.json`, normalized `spec.json`, and `coordinate-transform.json`. Normalized `offset:[x,y]` is relative to copper; BEGIN must be zero. Nonzero SMD offsets require XML, emitting `<offset>(x;y)</offset>` and comparing native values; replay does not pretend to support them. Through/mounting inputs require `drill_center` aligned with copper; eccentric holes/noncoaxial layers are unsupported.

Do not silently round half-grid translations. Increase accuracy and recheck, or fail if the native format cannot represent them. After changing a PAD origin, use the same `source_center` as package `pad_origin_shifts`; changing only PAD would move actual copper.
