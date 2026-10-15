# Interactive constraints and critical-net routing

## Engineering decisions

Identify critical nets from schematics, attributes, interface/device documentation, stackup, and user requirements. Net names are clues, not proof. Explain priorities such as clocks/sampling, differential links, sensitive analog, feedback, or high di/dt loops; these examples are not a fixed universal order.

Resolve requests such as a width of 0.2 mm, minimum clearance of 0.15 mm, clock-first routing, or protected traces into exact physical net sets, units, scope, and rationale. Distinguish width, copper clearance, differential intra-pair gap, and external pair spacing. Impedance additionally requires stackup calculation/field solving. Explain conflicts with escape geometry, manufacturing, or existing rules rather than relaxing constraints merely to route.

Check pin mapping, escapes, reference planes/returns, and critical paths against placement. Choose group order, protected geometry, and permitted reroutes. Return to placement when needed; unrestricted rip-up should not hide placement problems. Ordinary nets must preserve accepted critical routes.

## Routing schema 1

Example: `../assets/routing-example.json`.

```sh
python3 scripts/pcb.py route /path/to/routing-plan.json --netlist /path/to/netlist.json --out /path/to/jobs/route-plan-01
python3 scripts/pcb.py route /path/to/routing-plan.json --netlist /path/to/netlist.json --dsn /path/to/native-export.dsn --out /path/to/jobs/route-plan-02
```

| Field | Meaning |
| --- | --- |
| `schema`, `units`, `basis` | `1`, `mm` / `mil`, evidence |
| `passes` | Maximum Router passes per group, `1..100`; no completion guarantee |
| `protected_nets` | Exact net names, excluded from routing groups |
| `groups[]` | Nonempty groups: `{name,nets,priority,width,clearance,basis,layers?,max_vias_per_connection?}` |
| `name` | Unique letter-initial alphanumeric/underscore name, at most 24 characters |
| `nets` | Explicit nonempty exact names, no duplicates or inter-group overlap |
| `priority` | `1..255`; smaller executes first, ties ordered by group name |
| `width`, `clearance` | Positive width and minimum copper clearance; simple net rules, not differential/impedance rules |
| `layers` | Optional native layer names, checked when `--dsn` is supplied |
| `max_vias_per_connection` | Optional `0..255` per connection, not total vias for the net |

`resolved.json` records order and unselected nets. `route.do` routes specified groups, protects existing wires/vias and preceding results, and saves `stage_XX.ses`. No automatic completion of omitted nets, inferred priority, or hidden parameter defaults. Add ordinary-net groups explicitly.

An empty Router selection permits whole-board routing. Before execution, `native-route` therefore requires selected DSN nets to match their physical pin sets, with at least two pins. To avoid wildcard expansion, supported net names contain letters, digits, `_ . / : + -`. Names with `[] * ?` or spaces require a verified exact-selection native workflow; do not silently rename them. Unknown constraint fields fail.

## Persist constraints and execute

1. Persist requirements in Constraint Manager on the current board copy and read effective physical/spacing/electrical rules. Preserve more specific region, differential, netclass, and from-to constraints; resolve conflicting overrides. `PHYSICAL_CONSTRAINT_SET` / `SPACING_CONSTRAINT_SET` are associations, not merely displayed numbers.
2. Where supported by the installed SKILL API, clone an existing CSet with `axlCNSCreate`, change requested items with `axlCNSSetPhysical` / `axlCNSSetSpacing`, and associate target nets. Query supported items through `axlCNSGetPhysical(nil nil nil)` / `axlCNSGetSpacing(nil nil nil)` rather than guessing release-specific names. `width_min` and `line_line` cover only part of the rules; copper clearance must include relevant wire/pin/via/shape pairs. Do not pass nil CSet to overwrite every board CSet.
3. Save/reopen and read associations/effective values. Editing CSet does not remove net/region overrides. Record the board hash and export matching `.dsn` / `_rules.do`; check higher-priority rules before executing. Editor `ROUTE_PRIORITY` favors smaller values, whereas Router `priority` favors larger values. This helper uses explicit execution order instead of copying that number.
4. Follow [runtime.md](runtime.md). Each group has a session checkpoint. For per-group acceptance, run only the current group, read back, then export the updated board for the next group. If a critical group is incomplete/conflicting, revise it before marking it accepted.
5. Import `.ses` through `specctra_in` into a copy of the same board revision used for export. Changes to netlist, placement, rules, or stackup require a new export/run. Sessions do not persist newly created Router rules, so generated `.do` cannot replace board constraint persistence/readback.

## Readback and iteration

Reopen the result, update native DRC, and compare logical connectivity, routed components/unroutes, shorts, group widths/clearances, layers/vias, critical constraints, and protected geometry. Keep a baseline and explain added/removed violations, incomplete connections, and waivers. An unchanged DRC count is insufficient.

`native-report` supports reports including `net`, `npr`, `ucn`, `drc`, `drc_shorts`, `elw`, `vialist_net`, and `waived_drc`. Also inspect paths, returns, differential/length behavior, and effective rules. Record why and where the model changed the plan so subsequent interaction can preserve accepted work.
