; Geometry snapshot only. Operates on a staged copy, never saves the source DRA.
procedure(libPoint(p) list(xCoord(p) yCoord(p)))
procedure(libPoly(p)
  list(p->area foreach(mapcar v p->vertices list(libPoint(car(v)) cadr(v)))
    foreach(mapcar h p->holes libPoly(h)) p->isHole)
)
procedure(libSegments(o)
  foreach(mapcar s o->segments
    cond(
      (s->objType == "line" list("line" s->width libPoint(car(s->startEnd)) libPoint(cadr(s->startEnd)) s->font))
      (s->objType == "arc" list("arc" s->width libPoint(car(s->startEnd)) libPoint(cadr(s->startEnd)) libPoint(s->xy) s->isClockwise s->isCircle s->font))
      (t list("unsupported" s->objType))
    )
  )
)
procedure(libInspect()
  let((f objects tb record)
    f=outfile("snapshot.sexpr")
    unless(f error("Snapshot output failed"))
    fprintf(f "%L\n" list("units" car(axlDBGetDesignUnits()) cadr(axlDBGetDesignUnits())))
    fprintf(f "%L\n" list("type" axlDesignType(t)))
    foreach(pin axlDBGetDesign()->pins
      fprintf(f "%L\n" list("pin" pin->number pin->name libPoint(pin->xy) pin->rotation pin->isMirrored pin->isMech))
      foreach(layer list("ETCH/TOP" "ETCH/BOTTOM" "PIN/SOLDERMASK_TOP" "PIN/PASTEMASK_TOP" "PIN/SOLDERMASK_BOTTOM" "PIN/PASTEMASK_BOTTOM")
        foreach(poly axlPolyFromDB(pin ?layer layer)
          fprintf(f "%L\n" list("padpoly" pin->number layer libPoly(poly)))))
    )
    axlVisibleDesign(t)
    axlSetFindFilter(?enabled list("noall" "alltypes") ?onButtons list("noall" "alltypes"))
    axlAddSelectAll()
    objects=axlGetSelSet()
    foreach(o copy(objects)
      when(o->objType == "net"
        objects=remove(o objects)
        foreach(branch o->branches
          foreach(child branch->children
            unless(member(child objects) objects=cons(child objects)))))
    )
    foreach(o objects
      record=nil
      cond(
        (o->objType == "pin" nil)
        (o->objType == "path" record=list("path" o->layer libSegments(o)))
        (o->objType == "shape"
          record=list("shape" o->layer o->fill !null(o->voids) libSegments(o)
            cadr(assoc('PACKAGE_HEIGHT_MAX axlDBGetProperties(o))) o->shapeIsBoundary))
        (o->objType == "text"
          unless(o->layer == "PACKAGE GEOMETRY/PIN_NUMBER"
            tb=axlGetParam(strcat("paramTextBlock:" o->textBlock))
            record=list("text" o->layer o->text libPoint(o->xy) o->rotation o->justify o->isMirrored
              list(tb->width tb->height tb->lineSpace tb->charSpace tb->photoWidth))))
        (t record=list("unsupported" o->objType))
      )
      when(record fprintf(f "%L\n" record))
    )
    fprintf(f "%L\n" list("end"))
    close(f)
    foreach(pad axlDBGetDesign()->padstacks
      unless(axlPadstackToDisk(pad->name strcat("pad_" lowerCase(pad->name))) error("PAD export failed")))
    f=outfile("inspect.done") fprintf(f "done\n") close(f)
  )
)
libInspect()
