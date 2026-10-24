# IronPython: xuat mong don (FamilyInstance, Structural Foundations) trong view VIEW_NAMES[0]:
# id, type, Type Mark, tam (Location), Hand/Facing, kich thuoc theo Hand/Facing (tu dinh hinh hoc), cot nam trong mong.
# -> %LOCALAPPDATA%/RevitMCPPython/pads.json. Chi doc.
import os, json
FT = 304.8
nm = lambda x: DB.Element.Name.__get__(x)
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc
VN = globals().get("VIEW_NAMES", ["BUILDING A - FOOTING MARKING PLAN"])[0]
v = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if x.Name == VN and not x.IsTemplate][0]
lv = v.GenLevel
cols = [c for c in DB.FilteredElementCollector(doc, v.Id).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType()
        if c.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).AsElementId() == lv.Id]


def verts(f):
    pts = []
    def walk(geo, T):
        for g in geo:
            if isinstance(g, DB.GeometryInstance):
                walk(g.GetSymbolGeometry(), T.Multiply(g.Transform)); continue
            if isinstance(g, DB.Solid) and g.Volume > 0:
                for e in g.Edges:
                    for p in e.Tessellate(): pts.append(T.OfPoint(p))
    walk(f.get_Geometry(DB.Options()), DB.Transform.Identity)
    return pts


out = []
for f in DB.FilteredElementCollector(doc, v.Id).OfCategory(DB.BuiltInCategory.OST_StructuralFoundation).WhereElementIsNotElementType():
    if not isinstance(f, DB.FamilyInstance): continue
    o = f.Location.Point; u = f.HandOrientation; w = f.FacingOrientation
    P = verts(f)
    if not P: continue
    us = [(p - o).DotProduct(u) for p in P]; ws = [(p - o).DotProduct(w) for p in P]
    inside = []
    for c in cols:
        q = c.Location.Point
        du, dw = (q - o).DotProduct(u), (q - o).DotProduct(w)
        if min(us) - 0.01 <= du <= max(us) + 0.01 and min(ws) - 0.01 <= dw <= max(ws) + 0.01:
            inside.append({"id": c.Id.IntegerValue, "type": nm(c.Symbol), "x": q.X * FT, "y": q.Y * FT})
    tm = f.Symbol.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_MARK)
    out.append({"id": f.Id.IntegerValue, "type": nm(f.Symbol), "mark": tm.AsString() if tm else "",
                "x": o.X * FT, "y": o.Y * FT, "hand": [u.X, u.Y], "facing": [w.X, w.Y],
                "u0": min(us) * FT, "u1": max(us) * FT, "w0": min(ws) * FT, "w1": max(ws) * FT, "cols": inside})
path = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "pads.json")
with open(path, "w") as fh:
    fh.write(json.dumps(out))
print(len(out), path)
