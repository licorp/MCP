# IronPython: dung lai san theo merge_snap_plan.json (gop + nan truc); moi cum 1 transaction, loi -> giu san cu.
import json, os
from System.Collections.Generic import List as CList
FT = 304.8
with open(os.path.join(os.environ.get("LOCALAPPDATA"), "RevitMCPPython", "merge_snap_plan.json")) as fh:
    plan = json.loads(fh.read())


class Swallow(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        for m in list(fa.GetFailureMessages()):
            if m.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(m)
        return DB.FailureProcessingResult.Continue


def loop_of(items, z):
    cl = DB.CurveLoop(); n = len(items)
    for k in range(n):
        a, b = items[k], items[(k + 1) % n]
        p0 = DB.XYZ(a["x"] / FT, a["y"] / FT, z); p1 = DB.XYZ(b["x"] / FT, b["y"] / FT, z)
        if "mid" in a:
            cl.Append(DB.Arc.Create(p0, p1, DB.XYZ(a["mid"]["x"] / FT, a["mid"]["y"] / FT, z)))
        else:
            cl.Append(DB.Line.CreateBound(p0, p1))
    return cl


groups = []
for p in plan:
    if p["old"] or not groups:
        groups.append([p])
    else:
        groups[-1].append(p)
ok, failed, made = 0, [], 0
for g in groups:
    t = DB.Transaction(doc, "MCP: gop san + nan truc")
    fho = t.GetFailureHandlingOptions(); fho.SetFailuresPreprocessor(Swallow()); t.SetFailureHandlingOptions(fho)
    t.Start()
    try:
        for p in g:
            z = doc.GetElement(DB.ElementId(p["level_id"])).Elevation
            L = CList[DB.CurveLoop](); L.Add(loop_of(p["outer"], z))
            for h in p["holes"]:
                L.Add(loop_of(h, z))
            f = DB.Floor.Create(doc, L, DB.ElementId(p["type_id"]), DB.ElementId(p["level_id"]))
            f.get_Parameter(DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(p["offset_mm"] / FT)
            f.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(p["comments"])
            sp = f.get_Parameter(DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
            if sp and not sp.IsReadOnly:
                sp.Set(int(p["structural"]))
            made += 1
        for i in g[0]["old"]:
            doc.Delete(DB.ElementId(i))
        t.Commit(); ok += 1
    except Exception as ex:
        t.RollBack(); failed.append((g[0]["old"][:3], str(ex)[:70]))
print("cum ok", ok, "/", len(groups), "san moi", made, "loi", failed)
