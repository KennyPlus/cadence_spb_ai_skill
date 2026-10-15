# Capture execution, DRC, and netlisting

Use this path only when the user explicitly requests a native DSN deliverable. XML generation, offline checking, and preview delivery are complete without it. A reference binary DSN, a general request to check a schematic, or a missing runtime profile does not authorize opening Capture. Do not contact a worker or request Cadence environment/license setup during ordinary XML work.

## Native interface and prerequisites

Initialize the installed Cadence environment and license before starting Capture. A Linux installation may include Capture scripts and XSDs without a Capture executable. Use a real supported Capture interpreter; do not invent a universal `capture.exe -headless` command or load arbitrary DLLs into system Tcl. A request for offline work does not authorize contacting a Windows worker.

The bridge signatures are based on the installed Cadence `tools/capture/tclscripts/capXMLImportExport/tcl/OrHandlerXMLImportExport.tcl`:

```tcl
XMATIC_DSN2XML input.dsn output.xml dsn.xsd export.log 0
XMATIC_XML2DSN input.xml output.dsn 0 0 import.log generated.tcl
```

Probe the target runtime, then use new destinations in a task directory:

```tcl
source /task/capture_bridge.tcl
agentSchematic::probe /task/probe-01
agentSchematic::exportDesign /task/source-copy.dsn /task/source.xml /installed/capDB/dsn.xsd /task/export.log
agentSchematic::importDesign /task/generated.xml /task/generated.dsn /task/import.log /task/generated.tcl SCHEMATIC1
```

Export after saving the task copy. XML import may emit a Tcl recipe before producing a DSN. Inspect that recipe and its destinations before sourcing it in Capture. The bridge never runs generated Tcl automatically or treats an API return/file existence as acceptance. Native schema files remain installation inputs and are not redistributed.

Pass the model's expected root schematic name to `importDesign`. In Capture 25.1, XMATIC can successfully save an imported DSN without establishing its root, even when the XML declares `rootName`. The bridge checks native error states, initializes a missing root only in its newly created DSN, and rejects an unexpected root. `exportDesign` checks that the source has a root before calling XMATIC; the native exporter can terminate Capture on a rootless design.

## XML-driven automation

Design XML and Library XML can be prepared, schema-checked, inspected, and compared without a desktop. XML is the interchange representation; the model still owns circuit intent, part selection, and engineering review. Writing valid XML alone does not establish Capture database semantics or a completed native DRC.

Keep native execution behind a Windows worker with the installed Capture environment and a valid license. Cadence documents startup Tcl execution with Capture's GUI, not a universal headless Capture interpreter. An authorized worker can automate this without manual schematic editing, but a desktop session, modal dialogs, and release-specific APIs remain native dependencies. Do not silently substitute System Capture's command-line switches for OrCAD Capture's.

Use a one-line startup file that sources the actual job script:

```tcl
source {C:/task/run.tcl}
```

Launch it using the target release's supported startup syntax, for example:

```powershell
& 'C:\Cadence\SPB_25.1\tools\bin\Capture.exe' '-product=OrCAD Capture' 'C:\task\startup.tcl'
```

On the tested 25.1 runtime, passing a multiline job directly as the startup file did not preserve ordinary Tcl control flow. The single-line `source` wrapper executes it with normal Tcl semantics and a meaningful `info script`. Record explicit completion and failures inside the job. A process starting, exiting, or emitting some output is insufficient. When using SSH, verify the actual Windows session: a Session 0 process does not establish desktop execution. Use a dedicated task and fresh directories; bound its lifetime and handle only that task's windows and processes. Save the task design and close the project before `Menu "File::Exit"`; a raw Tcl `exit` can leave startup/recovery prompts for the next run.

Validate generated XML against the target installation's `dsn.xsd`, for example with `xmllint --noout --schema /installed/capDB/dsn.xsd generated.xml`. XSD permits string-valued metadata and cannot establish semantic correctness of all enums, cached symbols, or instance attributes. Import into a new design, save, close/reopen, export fresh XML, and compare references, values, footprints, pin mappings, NC markers, page geometry, and connectivity.

## Run full DRC

Select the intended design in Project Manager and use **PCB > Design Rules Check** in current releases, or **Tools > Design Rules Check** in older releases. Review the full-design scope, electrical rule matrix, physical rules, warnings, and any waivers. Include checks appropriate to the design: annotation/duplicate references, invalid pin numbers, package/pin consistency, unconnected pins, output conflicts, off-page/hierarchical connections, hanging wires, and footprint properties. Record actual settings and the run's completion evidence with the current DSN hash.

Fix errors and review warnings against component documentation and intended connections. Removing markers is not running DRC; waived or disabled rules are not clean results. Re-run after edits. Capture DRC is schematic validation, distinct from PCB spacing DRC and from circuit-level electrical/simulation review.

For repeated automation, record the target release's UI commands and inspect its Tcl APIs. Do not substitute a custom `capDRC` callback for the complete electrical/physical run, or guess an undocumented `RunDRC` command. Helpers can summarize report findings; the model must inspect scope, completion, settings, waivers, and the full log before asserting native DRC success.

Capture 25.1 exposes DRC settings through a web dialog. Its run payload includes `DoModal=1`; settings alone can be applied without running checks. Select **Reports** or **Both** when collecting a report, preserve the reviewed configuration, and use `DumpSessionLog C:/task/session.txt` to retain execution messages. A successful `Menu` return or saved DRC settings in the OPJ does not prove that the rule engine completed.

## Generate the PCB Editor netlist

Save and annotate the intended task design, preserving confirmed references. In Project Manager, select the DSN and use **Tools > Create Netlist**, then the **PCB Editor** flow. Review the output directory, occurrence/instance property behavior, footprint field mapping, population rules, and constraints. Export into a fresh directory. Use the netlist-only step while schematic checks are being resolved; board creation/import is a separate workflow.

Require nonempty `pstchip.dat`, `pstxprt.dat`, and `pstxnet.dat`, and retain constraint companions and logs. If the release produces only a compressed database such as `pstdedb.cdsz`, obtain a supported traditional PST export instead of renaming it. Parse the actual export and compare the physical pin-to-net graph with the intended model. Duplicate pin names, unit mapping, hidden power, and repeated hierarchy can produce differences that simple net/component counts miss.

Hand the native, compared PST directory and its provenance to `allegro-pcb` for import and placement. Do not use generated model PST as proof that a schematic exists or that Capture DRC passed.

### Command-line netlisting

The installed `pstswp.exe` can produce PCB Editor PST files from a saved DSN without Capture's GUI. This path was exercised on 25.1 in Windows Session 0, with exit code zero and the synthetic example's complete component/footprint/pin-to-net graph matching the model. It does not run full Capture DRC or convert XML to DSN.

Initialize the target environment first. Use a fresh output directory and a **copy** of the saved DSN: the tested netlister updated its input database and created a DBK backup while packaging the design view. Keep the source immutable and record both pre/post input hashes, executable/configuration versions, output hashes, exit code, and full log. For example, after preparing `C:\task\netlist-01\input.dsn`:

```powershell
$cadenceRoot = 'C:\Cadence\SPB_25.1'
$netlistJob = 'C:\task\netlist-01'
& "$cadenceRoot\tools\bin\pstswp.exe" -pst -d "$netlistJob\input.dsn" -n $netlistJob -c "$cadenceRoot\tools\capture\allegro.cfg" -v 3 -l 255 -j 'PCB Footprint'
if ($LASTEXITCODE -ne 0) { throw "Native netlisting failed: $LASTEXITCODE" }
```

Review the target's generated command/configuration when selecting name limits and property behavior. A short name limit can rename generated device identifiers; do not suppress those warnings or infer a graph match from counts. Require and compare all three PST files as above. CLI availability, license behavior, and supported switches must be verified on other releases.

## Primary references

- [Cadence: Capture XML import/export introduced in 17.2](https://www.cadence.com/japan/archive/soconline/vol22/tech/tech_3.html).
- [Cadence: startup Tcl runs with the Capture GUI](https://support1.cadence.com/public/docs/content/20466470.html).
- [Cadence: recording and replaying DRC settings](https://community.cadence.com/cadence_technology_forums/pcb-design/f/allegro-x-scripting-tcl/65002/design-rules-check-option-from-tcl).
- [Cadence Community: command-line PCB netlisting with pstswp](https://community.cadence.com/cadence_technology_forums/pcb-design/f/allegro-x-capture-cis/51628/bom-netlist-generation-using-command-prompt).
- [Cadence: Capture DRC scope and enhancements](https://community.cadence.com/cadence_blogs_8/b/pcb/posts/what-s-good-about-capture-s-design-rule-checks-16-6-has-several-new-enhancements).
- [Cadence: creating a netlist](https://resources.pcb.cadence.com/schematic-design-page/col/schematic-design/orcad-capture-creating-a-netlist-3).
- Installed `OrCAD_Capture_TclTk_Extensions.pdf`, `capDB/dsn.xsd`, `capDB/olb.xsd`, and `capXMLImportExport/tcl/OrHandlerXMLImportExport.tcl`. Verify their versions on the executing machine.
