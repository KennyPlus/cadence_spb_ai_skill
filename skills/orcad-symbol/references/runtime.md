# Capture XML and runtime boundaries

The format is `Lib / Package / LibPart / NormalView / SymbolPinScalar`; `PhysicalPart / PinNumber` maps physical numbers by `position`. Offline generation and comparison use supplied XML/profile data and require no Cadence installation. Optionally validate against a locally available `capture/tclscripts/capDB/olb.xsd`; vendor schemas/libraries are not redistributed. Do not launch Capture or contact a worker for ordinary XML work.

Cadence's bundled `capXMLImportExport/tcl/OrHandlerXMLImportExport.tcl` uses:

```tcl
XMATIC_OLB2XML input.olb output.xml olb.xsd export.log
XMATIC_XML2OLB input.xml output.olb 0 import.log generated.tcl
```

These commands belong to Capture, not system `tclsh`. The bridge checks command availability and new destinations:

```tcl
source /task/scripts/capture_bridge.tcl
agentSymbol::probe /task/probe
agentSymbol::exportLibrary /input/library.olb /task/library.xml /installed/capDB/olb.xsd /task/export.log
agentSymbol::importLibrary /task/PART.xml /task/PART.olb /task/import.log /task/generated.tcl
```

`probe` records actual integer `DboValue_*` variables and command presence. Review `enum-dump.tsv`, create the JSON profile, and record the runtime version. Import can generate Tcl first; the bridge does not automatically execute it. Review paths before sourcing it in Capture. Re-export the OLB, run `verify`, place it, and check ERC/netlisting. API returns and OLB existence are not acceptance. References are not overwritten and workers are not contacted automatically.

Python generation and semantic comparison are portable. XSD checking needs an external validator such as xmllint. Native import/export requires actual Capture and a separately requested native deliverable; no universal `capture.exe -headless` invocation is claimed. Reuse supplied/evidenced enum profiles for XML-only work. The demonstration profile needs target verification before claiming native acceptance, not before producing an explicitly offline result.
