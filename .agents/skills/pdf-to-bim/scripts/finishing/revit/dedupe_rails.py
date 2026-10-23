# IronPython: tuong lan can trung nhau (canh bao "walls overlap") -> xoa doan ngan hon
FT = 304.8
dele = set(); info = []
for w in doc.GetWarnings():
    if "walls overlap" not in w.GetDescriptionText(): continue
    ws = [doc.GetElement(i) for i in list(w.GetFailingElements()) + list(w.GetAdditionalElements())]
    ws = [x for x in ws if isinstance(x, DB.Wall)]
    if len(ws) != 2: continue
    rail = [x for x in ws if "PBS1" in DB.Element.Name.__get__(x.WallType) or "180mm - PC1" in DB.Element.Name.__get__(x.WallType)]
    if not rail: continue
    victim = min(rail, key=lambda x: x.Location.Curve.Length)
    if victim.Id.IntegerValue in dele: continue
    dele.add(victim.Id.IntegerValue)
    info.append((victim.Id.IntegerValue, DB.Element.Name.__get__(victim.WallType)[-5:], round(victim.Location.Curve.Length * FT), [ (x.Id.IntegerValue, DB.Element.Name.__get__(x.WallType)[-6:]) for x in ws]))
t = DB.Transaction(doc, "MCP: xoa lan can trung"); t.Start()
for i in dele: doc.Delete(DB.ElementId(i))
t.Commit(); print("xoa", len(dele))
for x in info: print(x)
