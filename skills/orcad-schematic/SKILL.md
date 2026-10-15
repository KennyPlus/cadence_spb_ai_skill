---
name: orcad-schematic
description: Design OrCAD schematics as headless Design XML, check physical pin and wire connectivity, and generate SVG/HTML previews without Capture or a desktop. Use Capture GUI conversion only when DSN output is explicitly requested. Use for complete circuits and pages; use orcad-symbol for individual library symbols.
---

The model owns circuit design: component selection, values, supply domains, pin functions, page organization, connection intent, and review of electrical requirements. Helpers serialize and check explicit decisions; they do not infer a valid circuit from reference designators or net names.

## Default: headless XML

An ordinary request to design, check, or preview a schematic ends with XML, offline findings, and preview files. Do not launch Capture, connect to a Windows worker, probe a live runtime, or require a license/desktop for this flow. Native DSN/DRC checks are outside its acceptance criteria. Generate previews as files without opening a browser or another GUI.

- Read [design.md](references/design.md) for circuit design and reference handling without opening Capture.
- Read [model.md](references/model.md) for XML generation, direct XML checks, SVG/HTML previews, and model PST output. The examples are synthetic, not qualified components.
- Read [capture.md](references/capture.md) only when the user explicitly requests a native `.dsn` deliverable. A reference DSN alone is not a request to open a GUI.

## Engineering loop

1. Identify the actual source revision, component variants, existing XML libraries, and intended deliverables. Treat reference projects as read-only inputs. Prefer existing XML/PDF/PST evidence. A Capture binary `.dsn` and a SPECCTRA text `.dsn` are different formats; a binary stream inventory or printable strings is not a circuit model. If an essential reference exists only as binary DSN, state the missing offline evidence and continue independent XML work without opening Capture.
2. Derive the design from requirements and device documentation: voltage and current limits, pin electrical roles, supply/return paths, decoupling, reset/boot state, clocks, feedback, interfaces, protection, and footprint pin numbering. Record sources and unresolved engineering decisions. A reference circuit is evidence to examine, not a universal template to copy.
3. Place and connect parts in readable functional pages. Preserve intentional NCs and confirmed references. Represent required hierarchy/off-page semantics explicitly in XML; identical labels alone do not prove cross-page connectivity.
4. Generate XML, then check the actual XML cache, instance attributes, physical pin mapping, wires, aliases, and junctions. Inspect the resulting SVG/HTML connectivity preview and fix findings. Report unsupported semantics instead of dropping them or silently switching to a GUI.
5. Deliver the checked XML, findings, preview files, input/output hashes, and any requested model netlist. Report native execution as `not_requested`; it is not unfinished work for an XML-only request. Review electrical assumptions separately from the helper's structural/connectivity checks.

The portable generator and direct XML checker support a flat schematic with scalar, explicit visible pins, one unit per package, zero rotation, orthogonal wires, and no cross-page electrical connections. Unsupported features need additional offline XML handling and validation, or a clearly stated coverage limit. Do not flatten hierarchy or drop buses, implicit power, alternate views, or properties to fit the helper. The preview simplifies symbol bodies; it is not a Capture page rendering.

## Explicit DSN output

Only an explicit request to generate/save a native DSN enables the Capture GUI conversion path. First complete the headless XML checks and preview, then use a fresh task directory and the user's configured Capture environment to import, save, reopen, and compare XML readback. Use the native bridge from the skill; it is not included in ordinary XML output. Run native DRC/netlisting when included in the requested native deliverable and report their actual results separately.

`checked_model`, `checked_xml`, `inventory_only`, `report_findings_only`, and `netlist_matches_model` describe offline evidence. Helpers retain `native_capture_verified: false`. Offline electrical findings are not a full Capture DRC result; XSD checks, if available locally, are another separate validation layer.
