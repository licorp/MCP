# IronPython, read-only: sampled points of every wall location curve (Revit mm) + base level, for overlap checks.
import json, os
FT = 304.8
out = []
for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall):
    lc = w.Location
    if not isinstance(lc, DB.LocationCurve): continue
    c = lc.Curve
    pts = [c.Evaluate(i / 10.0, True) for i in range(11)]
    bb = w.get_BoundingBox(None)
    out.append({"id": w.Id.IntegerValue, "type": DB.Element.Name.__get__(w.WallType), "level": doc.GetElement(w.LevelId).Name,
                "zmin": round(bb.Min.Z * FT), "zmax": round(bb.Max.Z * FT), "pts": [[round(p.X * FT, 1), round(p.Y * FT, 1)] for p in pts]})
with open(os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "walls_pts.json"), "w") as fh:
    fh.write(json.dumps(out))
print("walls", len(out))
