# IronPython: join floors reported as overlapping (thicker floor cuts the thinner one).
t = DB.Transaction(doc, "MCP: join overlapping floors (arc vs polyline slivers)")
t.Start()
try:
    n = 0
    for w in doc.GetWarnings():
        if "overlap" not in w.GetDescriptionText():
            continue
        ids = list(w.GetFailingElements()) + list(w.GetAdditionalElements())
        if len(ids) != 2:
            continue
        a, b = doc.GetElement(ids[0]), doc.GetElement(ids[1])
        if not DB.JoinGeometryUtils.AreElementsJoined(doc, a, b):
            DB.JoinGeometryUtils.JoinGeometry(doc, a, b)
        ta = doc.GetElement(a.GetTypeId()).get_Parameter(DB.BuiltInParameter.FLOOR_ATTR_DEFAULT_THICKNESS_PARAM).AsDouble()
        tb = doc.GetElement(b.GetTypeId()).get_Parameter(DB.BuiltInParameter.FLOOR_ATTR_DEFAULT_THICKNESS_PARAM).AsDouble()
        cutter = a if ta >= tb else b
        if not DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, cutter, b if cutter is a else a):
            DB.JoinGeometryUtils.SwitchJoinOrder(doc, a, b)
        n += 1
    t.Commit()
    print("COMMITTED joined pairs:", n)
except Exception as ex:
    t.RollBack()
    print("ROLLED BACK: " + str(ex))
