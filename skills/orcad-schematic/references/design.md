# Reference inspection and schematic design

## Understand a reference project

Read available XML exports, PDF pages, BOM, OPJ metadata, and companion PST files together without starting Capture. The OPJ is project configuration, not authoritative connectivity. Record hashes and distinguish source files from older exports. Never save upgrades, annotations, or DRC changes into the reference directory.

Capture DSN is commonly an OLE compound document. An optional `olefile` inspection can identify `Views/<schematic>/Pages/<page>`, `Cache`, and `Hierarchy` streams without modifying the file. This establishes file identity and page names only. Do not infer a complete pin graph from stream names or `strings` output. Use existing Design XML with `schematic.py inspect` for a bounded inventory. If only a binary DSN is available, report that its connectivity has not been inspected and continue independent design work from the available requirements. GUI export is reserved for an explicitly requested native DSN workflow. Inventory preserves instance properties and reports unsupported page objects; it does not certify connectivity.

Separate page-local instances from instantiated occurrences. Preserve the physical reference, package/unit mapping, pin number, net alias, hierarchy path, and relevant instance/occurrence properties. Review `PCB Footprint`, value, part selection, population/DNP rules, power groups, and net constraints in the actual design. A schematic coordinate is not a PCB placement coordinate.

## Create or change the circuit

Use the requirements and device documentation to choose the circuit. Check input/output voltage compatibility, absolute limits, pull resistors, startup/default state, decoupling, return paths, clock and feedback connections, protection, and connector pinouts. Review reserved/DNU/thermal pins individually. Do not infer no-connect status from a pin named NC, or power direction from a net name.

Lay out readable pages with explicit supply and signal flow, short local feedback/decoupling connections, meaningful labels, and unambiguous junctions. Keep symbol graphics and physical pin mapping separate. Use the offline `orcad-symbol` XML workflow when a new symbol is needed, then embed the reviewed library package in Design XML. OLB generation and placement in Capture are not prerequisites.

For a design that fits the portable model, use a supplied/reviewed empty Design XML template and Library XML. They may be authored offline; a fresh native export is not required. Review the evidence for the pin-type profile without probing Capture. The generator copies template metadata, embeds selected packages, checks the serialized XML's graph, and renders previews. The bundled template and library are synthetic examples; production component selection still requires engineering evidence.

For features outside the current offline helper, preserve their XML semantics and extend the offline handling when required, or state which checks/previews are unsupported. Do not silently flatten hierarchy or substitute a GUI session. Native database editing, when a DSN deliverable is explicitly requested, follows [capture.md](capture.md); compare native readback separately from the offline result.

## Review the deliverable

Inspect the generated SVG/HTML for readability, net labels, physical pin numbers, junctions, and NC markers. Preview generation requires no GUI; the files can be viewed independently later. The helper uses symbol bounds and pins and does not reproduce every library graphic. Review XML connectivity changes as added/removed/changed physical pin-to-net assignments, not only component and net counts. Deliver offline findings and coverage limits with the XML. Native DRC is not a completion gate for this deliverable.
