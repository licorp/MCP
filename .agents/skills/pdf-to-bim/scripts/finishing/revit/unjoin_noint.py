t = DB.Transaction(doc, "MCP: unjoin elements that no longer intersect"); t.Start()
n = 0
for w in doc.GetWarnings():
    if "joined but do not intersect" in w.GetDescriptionText():
        ids = list(w.GetFailingElements()) + list(w.GetAdditionalElements())
        if len(ids) == 2:
            DB.JoinGeometryUtils.UnjoinGeometry(doc, doc.GetElement(ids[0]), doc.GetElement(ids[1])); n += 1
t.Commit(); print("unjoined", n)
