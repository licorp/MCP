import System
# IronPython: join every floor with the walls / structural columns whose solids intersect it (floor surface edges disappear).
import collections
DRY = globals().get("DRY_RUN", False)
cats = System.Collections.Generic.List[DB.BuiltInCategory]([DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_StructuralColumns])
mf = DB.ElementMulticategoryFilter(cats)
pairs, joined_already = [], 0
for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor):
    for e in DB.FilteredElementCollector(doc).WherePasses(mf).WhereElementIsNotElementType().WherePasses(DB.ElementIntersectsElementFilter(f)):
        if DB.JoinGeometryUtils.AreElementsJoined(doc, f, e): joined_already += 1
        else: pairs.append((f, e))
c = collections.Counter((doc.GetElement(f.LevelId).Name[-8:], e.Category.Name) for f, e in pairs)
print("to join:", len(pairs), "already joined:", joined_already, dict(c))
if not DRY:
    t = DB.Transaction(doc, "MCP: join floors with walls/columns passing through")
    fho = t.GetFailureHandlingOptions(); t.Start()
    n, bad = 0, 0
    for f, e in pairs:
        try:
            DB.JoinGeometryUtils.JoinGeometry(doc, f, e); n += 1
        except Exception:
            bad += 1
    t.Commit(); print("COMMITTED joined", n, "failed", bad)
