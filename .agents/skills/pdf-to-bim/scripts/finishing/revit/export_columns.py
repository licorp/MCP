# IronPython: xuat cot ket cau (mark, type, x, y mm, level chan) ra %LOCALAPPDATA%/RevitMCPPython/columns.json
# dung de hieu chuan to PDF bang cot (column_calibration.calibrate_from_columns). Chi doc.
import os, json
FT = 304.8
nm = lambda x: DB.Element.Name.__get__(x)
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc
out = []
for c in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType():
    p = c.Location.Point
    mk = c.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK).AsString() or ""
    lv = doc.GetElement(c.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).AsElementId())
    out.append({"id": c.Id.IntegerValue, "mark": mk, "type": nm(doc.GetElement(c.GetTypeId())),
                "x": p.X * FT, "y": p.Y * FT, "level": lv.Name if lv else ""})
path = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "columns.json")
with open(path, "w") as f:
    f.write(json.dumps(out))
print(len(out), path)
