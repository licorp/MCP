# IronPython, read-only: dump PDF2BIM floor sketches keeping arcs (start, end, mid) to JSON.
import json, os
FT = 304.8
out = []
for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor):
    cm = f.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
    if not (cm.startswith("PDF2BIM|") or cm.startswith("FILL|")):
        continue
    sk = doc.GetElement(f.SketchId)
    loops = []
    for loop in sk.Profile:
        items = []
        for c in loop:
            p = c.GetEndPoint(0)
            it = {"x": round(p.X * FT, 2), "y": round(p.Y * FT, 2)}
            if isinstance(c, DB.Arc):
                m = c.Evaluate(0.5, True)
                it["mid"] = {"x": round(m.X * FT, 2), "y": round(m.Y * FT, 2)}
            items.append(it)
        loops.append(items)
    st = f.get_Parameter(DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
    out.append({"id": f.Id.IntegerValue, "comments": cm, "type_id": f.GetTypeId().IntegerValue,
                "type": DB.Element.Name.__get__(doc.GetElement(f.GetTypeId())),
                "level_id": f.LevelId.IntegerValue, "level": doc.GetElement(f.LevelId).Name,
                "offset_mm": round(f.get_Parameter(DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).AsDouble() * FT, 2),
                "structural": st.AsInteger() if st else 1, "loops": loops})
path = os.path.join(os.environ.get("LOCALAPPDATA"), "RevitMCPPython", "slabs_export_fill.json")
with open(path, "w") as fh:
    fh.write(json.dumps(out))
print("exported", len(out))
