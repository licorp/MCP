# IronPython, read-only: compare each structural column top with the top of the slab it meets.
import collections
FT = 304.8
floors = []
for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor):
    bb = f.get_BoundingBox(None)
    if bb:
        floors.append((f, bb))

def slab_hits(x, y, z_ref):
    """Floors whose top face is above point (x,y) within +-1.5 m of z_ref; returns [(top_mm, floor)]."""
    out = []
    p = DB.XYZ(x, y, 0)
    for f, bb in floors:
        if not (bb.Min.X <= x <= bb.Max.X and bb.Min.Y <= y <= bb.Max.Y):
            continue
        if abs(bb.Max.Z * FT - z_ref) > 1500:
            continue
        try:
            refs = DB.HostObjectUtils.GetTopFaces(f)
        except Exception:
            continue
        for r in refs:
            face = f.GetGeometryObjectFromReference(r)
            res = face.Project(DB.XYZ(x, y, bb.Max.Z + 10))
            if res is None:
                continue
            q = res.XYZPoint
            if abs(q.X - x) < 1e-3 and abs(q.Y - y) < 1e-3:
                out.append((q.Z * FT, f))
                break
    return out


PARAMS = {
    ("COL", "top"): DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM,
    ("COL", "base"): DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,
    ("WALL", "top"): DB.BuiltInParameter.WALL_TOP_OFFSET,
    ("WALL", "base"): DB.BuiltInParameter.WALL_BASE_OFFSET,
}
plan = []
for bic, tag in ((DB.BuiltInCategory.OST_StructuralColumns, "COL"), (DB.BuiltInCategory.OST_Walls, "WALL")):
    for e in DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
        bb = e.get_BoundingBox(None)
        loc = e.Location
        if not bb:
            continue
        if hasattr(loc, "Point"):
            p = loc.Point
        elif hasattr(loc, "Curve"):
            p = loc.Curve.Evaluate(0.5, True)
        else:
            continue
        for end, z in (("top", bb.Max.Z * FT), ("base", bb.Min.Z * FT)):
            hits = slab_hits(p.X, p.Y, z)
            if not hits:
                continue
            slab_top, f = min(hits, key=lambda h: abs(h[0] - z))
            d = z - slab_top
            if 60 <= d <= 80:
                plan.append((e, tag, end, d))
t = DB.Transaction(doc, "MCP: columns/walls flush with set-down (MIN) slabs")
t.Start()
try:
    done = collections.Counter()
    for e, tag, end, d in plan:
        p = e.get_Parameter(PARAMS[(tag, end)])
        if p is None or p.IsReadOnly:
            done["%s %s SKIPPED (no offset param)" % (tag, end)] += 1
            continue
        p.Set((p.AsDouble() * FT - d) / FT)
        done["%s %s -%d" % (tag, end, round(d))] += 1
    t.Commit()
    print("COMMITTED", dict(done))
except Exception as ex:
    t.RollBack()
    print("ROLLED BACK: " + str(ex))
