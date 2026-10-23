# IronPython: walls (not US/PBS upstands) and columns whose top ends at a slab TOP -> stop at the slab underside
# (highest underside of the slabs they meet), so nothing shows through the slab surface.
FT = 304.8
TOL_BELOW = 120.0
DRY = globals().get("DRY_RUN", False)
floors = [(f, f.get_BoundingBox(None), doc.GetElement(f.GetTypeId()).get_Parameter(DB.BuiltInParameter.FLOOR_ATTR_DEFAULT_THICKNESS_PARAM).AsDouble() * FT)
          for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor)]
def hits(x, y, zt):
    out = []
    for f, bb, th in floors:
        if not (bb.Min.X <= x <= bb.Max.X and bb.Min.Y <= y <= bb.Max.Y) or abs(bb.Max.Z * FT - zt) > 120: continue
        for r in DB.HostObjectUtils.GetTopFaces(f):
            pr = f.GetGeometryObjectFromReference(r).Project(DB.XYZ(x, y, bb.Max.Z + 10))
            if pr and abs(pr.XYZPoint.X - x) < 1e-3 and abs(pr.XYZPoint.Y - y) < 1e-3:
                top = pr.XYZPoint.Z * FT
                if -15 < zt - top < TOL_BELOW: out.append(top - th)   # ca san ha cot thap hon dinh tuong <= TOL_BELOW
                break
    return out
plan = []
for bic in (DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_StructuralColumns):
    for e in DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
        if isinstance(e, DB.Wall):
            n = DB.Element.Name.__get__(e.WallType)
            if "UPSTAND" in n or "PBS1" in n or not isinstance(e.Location, DB.LocationCurve): continue
            c = e.Location.Curve; pts = [c.Evaluate(t, True) for t in (0.05, 0.3, 0.5, 0.7, 0.95)]
        elif isinstance(e.Location, DB.LocationPoint):
            pts = [e.Location.Point]
        else: continue
        bb = e.get_BoundingBox(None); zt = bb.Max.Z * FT
        b = [z for p in pts for z in hits(p.X, p.Y, zt)]
        if not b: continue
        target = max(b)
        if zt - target > 50: plan.append((e, zt - target))
import collections
print("to lower:", len(plan), collections.Counter((e.Category.Name, int(round(d / 10.0) * 10)) for e, d in plan).most_common(12))
if not DRY:
    t = DB.Transaction(doc, "MCP: walls/columns stop at slab underside"); t.Start()
    n = 0
    for e, d in plan:
        p = e.get_Parameter(DB.BuiltInParameter.WALL_TOP_OFFSET) if isinstance(e, DB.Wall) else e.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM)
        if p and not p.IsReadOnly: p.Set(p.AsDouble() - d / FT); n += 1
    t.Commit(); print("COMMITTED", n)
