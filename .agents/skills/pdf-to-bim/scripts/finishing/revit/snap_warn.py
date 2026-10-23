# IronPython: snap walls flagged "slightly off axis" to the nearest axis (keep start point).
ids = set()
for w in doc.GetWarnings():
    if "Wall is slightly off axis" in w.GetDescriptionText():
        ids.update(i.IntegerValue for i in w.GetFailingElements())
t = DB.Transaction(doc, "MCP: snap off-axis walls"); t.Start()
for i in ids:
    w = doc.GetElement(DB.ElementId(i)); c = w.Location.Curve
    if not isinstance(c, DB.Line): continue
    a, b = c.GetEndPoint(0), c.GetEndPoint(1)
    b = DB.XYZ(a.X, b.Y, b.Z) if abs(a.X - b.X) < abs(a.Y - b.Y) else DB.XYZ(b.X, a.Y, b.Z)
    w.Location.Curve = DB.Line.CreateBound(a, b)
t.Commit(); print("snapped", sorted(ids))
