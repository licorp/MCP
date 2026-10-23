# IronPython: rebuild host slabs with fillers merged (lines + arcs), delete merged fillers; keep old slab if a rebuild fails.
import json, os
from System.Collections.Generic import List as CList
FT = 304.8
with open(os.path.join(os.environ.get("LOCALAPPDATA"), "RevitMCPPython", "merge_plan.json")) as fh:
    plan = json.loads(fh.read())
def loop_of(items, z):
    cl = DB.CurveLoop(); n = len(items)
    for k in range(n):
        a, b = items[k], items[(k + 1) % n]
        p0 = DB.XYZ(a["x"] / FT, a["y"] / FT, z); p1 = DB.XYZ(b["x"] / FT, b["y"] / FT, z)
        if "mid" in a: cl.Append(DB.Arc.Create(p0, p1, DB.XYZ(a["mid"]["x"] / FT, a["mid"]["y"] / FT, z)))
        else: cl.Append(DB.Line.CreateBound(p0, p1))
    return cl
ok, failed = 0, []
for p in plan:
    t = DB.Transaction(doc, "MCP: merge fillers into slab %d" % p["id"]); t.Start()
    try:
        z = doc.GetElement(DB.ElementId(p["level_id"])).Elevation
        L = CList[DB.CurveLoop](); L.Add(loop_of(p["outer"], z))
        for h in p["holes"]: L.Add(loop_of(h, z))
        f = DB.Floor.Create(doc, L, DB.ElementId(p["type_id"]), DB.ElementId(p["level_id"]))
        f.get_Parameter(DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(p["offset_mm"] / FT)
        f.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(p["comments"])
        sp = f.get_Parameter(DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
        if sp and not sp.IsReadOnly: sp.Set(int(p["structural"]))
        doc.Delete(DB.ElementId(p["id"]))
        for i in p["fills"]: doc.Delete(DB.ElementId(i))
        t.Commit(); ok += 1
    except Exception as ex:
        t.RollBack(); failed.append((p["id"], str(ex)[:80]))
print("merged", ok, "failed", failed)
