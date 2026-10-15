---
name: orcad-symbol
description: Design OrCAD Capture Library XML symbols from PDF/image datasheets or explicit pin tables, checking physical numbers, electrical types, and supply connectivity; provide Tcl for native OLB/XML conversion. Use for schematic library symbols, not PCB PAD/DRA or complete schematic circuits.
---

# OrCAD Symbol

Use the specific device/package variant, pin definitions, and application guidance to create a reviewable pin specification before deterministic generation. The model reads source material; the helper does not claim general OCR. Confirm ambiguous numbers, overbar names, bottom views, and exposed-pad numbering against pin tables.

## Workflow

1. Treat references as read-only. Use existing Library XML or device pin tables for offline work. OLB is a binary database; printable strings are not a complete pin table. Do not open Capture to export it as a prerequisite for XML generation. Merged PCB pads cannot replace all logical chip terminals.
2. Read [specification and power rules](references/specification.md), then follow `assets/power-terminals-example.json`. Keep each physical terminal, evidence, role, and explicit electrical type separate. Identify source PDF pages or image regions.
3. Choose a supplied or previously evidenced enum profile using [runtime guidance](references/runtime.md); do not guess type numbers or start a runtime probe during XML-only work. The bundled mapping is a demonstration; retain that limitation until separately verified for a native deliverable.
4. Generate offline with Python 3.9+ on macOS/Linux/Windows:

   ```sh
   python3 scripts/symbol.py build spec.json --profile profile.json --out new-job
   python3 scripts/symbol.py inspect new-job/PART.xml
   python3 scripts/symbol.py verify spec.json new-job/PART.xml --profile profile.json
   ```

   Windows may use `py -3`. Output directories must be new. Pass paths rather than hardcoding installations/hosts. Optionally validate against installed `olb.xsd` with `xmllint --noout --schema PATH PART.xml`.
5. Deliver checked XML/specification as the completed offline result. Native OLB/DSN work is a separate explicit request; it is not required to finish XML generation. When used by `orcad-schematic`, obey its explicit DSN gate for GUI execution. The native bridge and ERC/netlisting workflow in the runtime reference remain available for that requested native work.

## Power and physical terminals

- Supply inputs, outputs, and returns use Capture POWER. `AgentElectricalRole` retains semantic direction as review metadata; it is not evidence that Capture ERC distinguishes power input from power output.
- The generator requires visible physical pins/numbers and `IsGlobal=0`. Hidden/implicit power, shared multi-unit power, and stacked numbering are rejected rather than simplified.
- Names are insufficient: OUTS may be sense input, NC may be an internal switch/thermal terminal, and GND may be a measurement reference. Read function descriptions. Use NC only for truly unconnected pins; review reserved, DNU, thermal, and internal-switch roles separately.
- Same-name GND/VCC pins retain distinct physical numbers. Do not let repeated names remove terminals.
- Review electrical attributes and numbering after generation. XML syntax, XSD validation, or attractive graphics do not establish production acceptance.
