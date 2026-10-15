# Source in the installed Capture Tcl interpreter. No headless launcher is assumed.
namespace eval agentSchematic {}
proc agentSchematic::requireCommand {name} {
    if {![llength [info commands ::$name]]} {error "Capture command unavailable: $name"}
}
proc agentSchematic::newFile {path} {
    set path [file normalize $path]
    if {[file exists $path]} {error "Refusing to overwrite: $path"}
    file mkdir [file dirname $path]
    return $path
}
proc agentSchematic::distinct {paths} {
    set normalized {}
    foreach path $paths {lappend normalized [string tolower [file normalize $path]]}
    if {[llength $normalized] != [llength [lsort -unique $normalized]]} {error "Input and output paths must be distinct"}
}
proc agentSchematic::checkStatus {status action} {
    if {[$status Failed]} {error "Capture failed to $action"}
}
proc agentSchematic::designRoot {dsn {expected {}} {initialize 0}} {
    requireCommand DboTclHelper_sCreateSession
    set session [::DboTclHelper_sCreateSession]
    set code [catch {
        set status [::DboState]
        set design [$session GetDesign [::DboTclHelper_sMakeCString [file normalize $dsn]] $status]
        checkStatus $status "open $dsn"
        if {$design eq "NULL"} {error "No design loaded: $dsn"}
        set root [$design GetRoot $status]
        if {$root eq "NULL"} {
            if {!$initialize || $expected eq ""} {error "DSN has no root schematic: $dsn"}
            set root [$design GetSchematic [::DboTclHelper_sMakeCString $expected] $status]
            checkStatus $status "find root schematic $expected"
            if {$root eq "NULL"} {error "Root schematic not found: $expected"}
            checkStatus [$design SetRoot $root] "set root schematic $expected"
            checkStatus [$session SaveDesign $design] "save rooted DSN $dsn"
        } else {checkStatus $status "read root schematic"}
        set name [::DboTclHelper_sMakeCString]
        checkStatus [$design GetRootName $name] "read root name"
        set name [::DboTclHelper_sGetConstCharPtr $name]
        if {$expected ne "" && $name ne $expected} {error "Root mismatch: expected $expected, found $name"}
        set name
    } result options]
    ::DboTclHelper_sDeleteSession $session
    if {$code} {return -options $options $result}
    return $result
}
proc agentSchematic::probe {outDir} {
    if {[file exists $outDir]} {error "Probe directory must be new"}
    file mkdir $outDir
    set f [open [file join $outDir capabilities.txt] w]
    puts $f "tcl_patchlevel=[info patchlevel]"
    foreach name {XMATIC_DSN2XML XMATIC_XML2DSN XMATIC_OLB2XML Menu DboState DboTclHelper_sMakeCString} {
        puts $f "$name=[llength [info commands ::$name]]"
    }
    puts $f "native_capture_verified=false"
    close $f
    set f [open [file join $outDir enum-dump.tsv] w]
    foreach name [lsort [info globals ::DboValue_*]] {
        set value [set ::$name]
        if {[string is integer -strict $value]} {puts $f "$name\t$value"}
    }
    close $f
}
proc agentSchematic::exportDesign {dsn xml xsd log} {
    requireCommand XMATIC_DSN2XML
    distinct [list $dsn $xml $xsd $log]
    if {![file isfile $dsn] || ![file isfile $xsd]} {error "DSN and installed dsn.xsd are required"}
    # Capture 25.1's exporter can terminate the application on a rootless DSN.
    designRoot $dsn
    # Signatures: Cadence capXMLImportExport/tcl/OrHandlerXMLImportExport.tcl.
    set xml [newFile $xml]; set log [newFile $log]
    set result [::XMATIC_DSN2XML [file normalize $dsn] $xml [file normalize $xsd] $log 0]
    checkStatus $result "export XML; inspect $log"
    if {![file isfile $xml] || ![file size $xml]} {error "No XML produced; inspect $log"}
    return [list status exported_only nativeReturn $result native_capture_verified false]
}
proc agentSchematic::importDesign {xml dsn log generatedTcl {rootName {}}} {
    requireCommand XMATIC_XML2DSN
    distinct [list $xml $dsn $log $generatedTcl]
    if {![file isfile $xml]} {error "Input Design XML is required"}
    if {$rootName eq ""} {error "The expected root schematic name is required"}
    set dsn [newFile $dsn]; set log [newFile $log]; set generatedTcl [newFile $generatedTcl]
    # Fresh destination, no merge, no preservation of source database IDs.
    set result [::XMATIC_XML2DSN [file normalize $xml] $dsn 0 0 $log $generatedTcl]
    checkStatus $result "import XML; inspect $log"
    # XMATIC may save a design with no root despite XML's rootName attribute.
    # Only initialize the newly created output, using the model's explicit root.
    if {[file isfile $dsn]} {designRoot $dsn $rootName 1}
    # Some versions generate Tcl first. Review its paths before sourcing it.
    return [list status import_candidate nativeReturn $result dsnExists [file isfile $dsn] tclExists [file isfile $generatedTcl] native_capture_verified false]
}
