# IronPython, read-only: duong tim cac tuong lan can (PBS1 / PC1 180 / US1) kem cung (start, mid, end) -> rails_export.json
import json, os
FT = 304.8
out = []
for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall):
    n = DB.Element.Name.__get__(w.WallType)
    if not ("PBS1" in n or "180mm - PC1" in n or "UPSTAND - US1" in n): continue
    c = w.Location.Curve
    a, b = c.GetEndPoint(0), c.GetEndPoint(1)
    it = {"id": w.Id.IntegerValue, "type": n, "level": doc.GetElement(w.LevelId).Name,
          "base_offset": round(w.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble() * FT, 1),
          "kind": "arc" if isinstance(c, DB.Arc) else "line",
          "start": [round(a.X * FT, 1), round(a.Y * FT, 1)], "end": [round(b.X * FT, 1), round(b.Y * FT, 1)]}
    if isinstance(c, DB.Arc):
        m = c.Evaluate(0.5, True); it["mid"] = [round(m.X * FT, 1), round(m.Y * FT, 1)]
    out.append(it)
with open(os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "rails_export.json"), "w") as fh:
    fh.write(json.dumps(out))
print("rails", len(out))
