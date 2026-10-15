; Read only: inspect actual DRA objects or loaded PSM definition.
procedure(pkgDumpObjects(port objects)
  foreach(o objects
    cond(
      (o->objType == "path"
        foreach(s o->segments
          if(s->objType == "line" then
            fprintf(port "LINE|%s|%.6f|%.6f|%.6f|%.6f|%.6f\n"
              o->layer s->width xCoord(car(s->startEnd)) yCoord(car(s->startEnd))
              xCoord(cadr(s->startEnd)) yCoord(cadr(s->startEnd)))
          else fprintf(port "UNSUPPORTED|%s\n" s->objType))
        )
      )
      (o->objType == "shape"
        if(o->isRect && o->fill == t && !o->voids then
          fprintf(port "RECT|%s|%.6f|%.6f|%.6f|%.6f\n" o->layer
            xCoord(car(o->bBox)) yCoord(car(o->bBox)) xCoord(cadr(o->bBox)) yCoord(cadr(o->bBox)))
        else fprintf(port "UNSUPPORTED|shape\n"))
        fprintf(port "HEIGHT|%L\n" cadr(assoc('PACKAGE_HEIGHT_MAX axlDBGetProperties(o))))
      )
      (o->objType == "text"
        unless(o->layer == "PACKAGE GEOMETRY/PIN_NUMBER"
          fprintf(port "TEXT|%s|%s|%.6f|%.6f|%.6f|%s|%L\n" o->layer o->text
            xCoord(o->xy) yCoord(o->xy) o->rotation o->justify o->isMirrored)
          fprintf(port "TEXTBOX|%s|%.6f|%.6f|%.6f|%.6f\n" o->layer xCoord(car(o->bBox)) yCoord(car(o->bBox)) xCoord(cadr(o->bBox)) yCoord(cadr(o->bBox)))
          ; Record actual text block parameters, independent of its numeric index.
          tb=axlGetParam(strcat("paramTextBlock:" o->textBlock))
          fprintf(port "FONT|%.6f|%.6f|%.6f|%.6f|%.6f\n" tb->width tb->height tb->lineSpace tb->charSpace tb->photoWidth)
        ))
      (t fprintf(port "UNSUPPORTED|%s\n" o->objType))
    )
  )
)
procedure(pkgReadback(mode name filename)
  let((port pins objects sym tb instance)
    port=outfile(filename)
    unless(port error("Cannot write readback"))
    fprintf(port "UNITS|%s|%d\n" car(axlDBGetDesignUnits()) cadr(axlDBGetDesignUnits()))
    if(mode == "psm" then
      axlSetVariable("psmpath" ".")
      axlSetVariable("padpath" ".")
      unless(axlDBChangeDesignExtents(list(-10000:-10000 10000:10000)) error("PCB extents failed"))
      instance=axlDBCreateSymbol(list(name "PACKAGE") 0:0 nil 0.0)
      unless(instance error("PSM did not load/place"))
      instance=car(instance)
      sym=instance->definition
      f=outfile("placement.txt")
      fprintf(f "PLACED|%s|%.6f|%.6f|%.6f|%d\n" instance->name xCoord(instance->xy) yCoord(instance->xy) instance->rotation length(instance->pins))
      close(f)
      fprintf(port "TYPE|%s\n" sym->type)
      pins=sym->pins
      objects=sym->children
    else
      fprintf(port "TYPE|%s\n" axlDesignType(t))
      pins=axlDBGetDesign()->pins
      axlVisibleDesign(t)
      axlSetFindFilter(?enabled list("noall" "lines" "shapes" "text") ?onButtons list("noall" "lines" "shapes" "text"))
      axlAddSelectAll()
      objects=axlGetSelSet()
    )
    foreach(pin pins
      fprintf(port "PIN|%s|%s|%.6f|%.6f|%.6f|%L|%L|%.6f|%.6f|%.6f|%.6f\n"
        pin->number pin->name xCoord(pin->xy) yCoord(pin->xy) pin->rotation pin->isMirrored pin->isMech
        xCoord(car(pin->bBox)) yCoord(car(pin->bBox)) xCoord(cadr(pin->bBox)) yCoord(cadr(pin->bBox)))
    )
    pkgDumpObjects(port objects)
    fprintf(port "END\n")
    close(port)
    foreach(pad axlDBGetDesign()->padstacks
      unless(axlPadstackToDisk(pad->name strcat(mode "_" lowerCase(pad->name))) error("Embedded pad export failed")))
    when(mode == "psm" unless(axlSaveDesign(?design "psm-load-check.brd" ?noMru t) error("PCB verification save failed")))
    port=outfile(strcat(mode ".done"))
    fprintf(port "done\n")
    close(port)
  )
)
