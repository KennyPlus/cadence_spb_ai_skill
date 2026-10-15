# Source inside an installed OrCAD Capture Tcl interpreter.
# These procedures do not launch windows, select UI objects, or contact a host.
# XMATIC command signatures are from Cadence's OrHandlerXMLImportExport.tcl.
namespace eval agentSymbol {}
proc agentSymbol::newFile {path} {
    set path [file normalize $path]
    if {[file exists $path]} {error "Refusing to overwrite: $path"}
    file mkdir [file dirname $path]
    return $path
}
proc agentSymbol::requireCommand {name} {
    if {[llength [info commands $name]] == 0} {error "Capture runtime command unavailable: $name"}
}
proc agentSymbol::probe {outDir} {
    file mkdir $outDir
    set path [newFile [file join $outDir enum-dump.tsv]]
    set f [open $path w]
    foreach name [lsort [info globals ::DboValue_*]] {
        set val [set ::[namespace tail $name]]
        if {[string is integer -strict $val]} {puts $f "[namespace tail $name]\t$val"}
    }
    close $f
    set f [open [newFile [file join $outDir capabilities.txt]] w]
    puts $f "tcl_patchlevel=[info patchlevel]"
    foreach command {XMATIC_OLB2XML XMATIC_XML2OLB} {puts $f "$command=[llength [info commands $command]]"}
    close $f
}
proc agentSymbol::exportLibrary {olb xml xsd log} {
    requireCommand XMATIC_OLB2XML
    if {![file isfile $olb] || ![file isfile $xsd]} {error "Input OLB and native olb.xsd must exist"}
    set xml [newFile $xml]; set log [newFile $log]
    set result [XMATIC_OLB2XML [file normalize $olb] $xml [file normalize $xsd] $log]
    if {![file isfile $xml] || [file size $xml]==0} {error "Export produced no XML; inspect $log; result=$result"}
    return $result
}
proc agentSymbol::importLibrary {xml olb log generatedTcl} {
    requireCommand XMATIC_XML2OLB
    if {![file isfile $xml]} {error "Input XML must exist"}
    set olb [newFile $olb]; set log [newFile $log]; set generatedTcl [newFile $generatedTcl]
    # Mode 0 targets a fresh output. Never merge or replace a historical library.
    set result [XMATIC_XML2OLB [file normalize $xml] $olb 0 $log $generatedTcl]
    # Some flows emit a Tcl recipe first. Never execute generated Tcl automatically:
    # review it and its paths in the task workspace before sourcing it in Capture.
    return [list nativeReturn $result olbExists [file isfile $olb] tclExists [file isfile $generatedTcl]]
}
