# IronPython: for every "walls overlap" warning between a lower and an upper wall, put the upper wall base back to 0.
FT = 304.8
t = DB.Transaction(doc, "MCP: stacked walls keep base at level (continuous walls)")
t.Start()
try:
    fixed = []
    for w in doc.GetWarnings():
        if "walls overlap" not in w.GetDescriptionText():
            continue
        ws = [doc.GetElement(i) for i in list(w.GetFailingElements()) + list(w.GetAdditionalElements())]
        ws = [x for x in ws if isinstance(x, DB.Wall)]
        if len(ws) != 2:
            continue
        upper = max(ws, key=lambda x: x.get_BoundingBox(None).Min.Z)
        p = upper.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET)
        if abs(p.AsDouble() * FT + 70) < 1:
            p.Set(0.0)
            fixed.append(upper.Id.IntegerValue)
    t.Commit()
    print("COMMITTED stacked walls reset:", fixed)
except Exception as ex:
    t.RollBack()
    print("ROLLED BACK: " + str(ex))
