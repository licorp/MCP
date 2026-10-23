# IronPython: tuong ket cau (khong lan can) kem duong tim, kieu, level, rang buoc
import json, os
FT = 304.8
out = []
for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall):
    n = DB.Element.Name.__get__(w.WallType)
    if "PBS1" in n or "PC1" in n or "UPSTAND" in n or not isinstance(w.Location, DB.LocationCurve): continue
    c = w.Location.Curve; a, b = c.GetEndPoint(0), c.GetEndPoint(1)
    it = {"id": w.Id.IntegerValue, "type": n, "type_id": w.WallType.Id.IntegerValue, "level": doc.GetElement(w.LevelId).Name,
          "top": doc.GetElement(w.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()).Name if w.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId().IntegerValue > 0 else "",
          "kind": "arc" if isinstance(c, DB.Arc) else "line", "start": [round(a.X*FT, 1), round(a.Y*FT, 1)], "end": [round(b.X*FT, 1), round(b.Y*FT, 1)],
          "comments": w.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""}
    if isinstance(c, DB.Arc):
        m = c.Evaluate(0.5, True); it["mid"] = [round(m.X*FT, 1), round(m.Y*FT, 1)]
    out.append(it)
with open(os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "walls_full.json"), "w") as fh: fh.write(json.dumps(out))
print("walls", len(out))
