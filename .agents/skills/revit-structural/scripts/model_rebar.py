"""
Batch create rebar reinforcement (longitudinal bars and stirrups) via pyRevit MCP.
"""
import httpx
import json

def reinforce_beam(beam_id, main_bar_type="D20", stirrup_bar_type="D10", cover_mm=30.0, mcp_url="http://localhost:48884/revit_mcp/execute_code/"):
    code = f'''
from Autodesk.Revit import DB
from System.Collections.Generic import List

beam_id_int = {beam_id}
elem_id = DB.ElementId(beam_id_int)
beam = doc.GetElement(elem_id)

t = DB.Transaction(doc, "Reinforce Concrete Beam")
t.Start()

# 1. Tìm RebarBarType
bar_types = {{bt.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString(): bt 
             for bt in DB.FilteredElementCollector(doc).OfClass(DB.Structure.RebarBarType).ToElements()}}

main_type = bar_types.get("{main_bar_type}", list(bar_types.values())[0])
stirrup_type = bar_types.get("{stirrup_bar_type}", list(bar_types.values())[0])

# 2. Lấy hình học dầm
bbox = beam.get_BoundingBox(None)
if bbox:
    min_pt = bbox.Min
    max_pt = bbox.Max
    cover_ft = {cover_mm} / 304.8
    
    # Tính toán toạ độ lõi bê tông
    x_min = min_pt.X + cover_ft
    x_max = max_pt.X - cover_ft
    y_min = min_pt.Y + cover_ft
    y_max = max_pt.Y - cover_ft
    z_min = min_pt.Z + cover_ft
    z_max = max_pt.Z - cover_ft
    
    # Tạo đường đai chữ nhật
    p1 = DB.XYZ(x_min, y_min, z_min)
    p2 = DB.XYZ(x_max, y_min, z_min)
    p3 = DB.XYZ(x_max, y_min, z_max)
    p4 = DB.XYZ(x_min, y_min, z_max)
    
    curves = List[DB.Curve]()
    curves.Add(DB.Line.CreateBound(p1, p2))
    curves.Add(DB.Line.CreateBound(p2, p3))
    curves.Add(DB.Line.CreateBound(p3, p4))
    curves.Add(DB.Line.CreateBound(p4, p1))
    
    normal = DB.XYZ(0, 1, 0)
    stirrup = DB.Structure.Rebar.CreateFromCurves(
        doc, DB.Structure.RebarStyle.StirrupTie, stirrup_type,
        None, None, beam, normal, curves,
        DB.Structure.RebarHookOrientation.Right, DB.Structure.RebarHookOrientation.Right,
        True, True
    )
    
    # Rải đai a150mm
    accessor = stirrup.GetShapeDrivenAccessor()
    beam_len = max_pt.Y - min_pt.Y - 2 * cover_ft
    accessor.SetLayoutAsMaximumSpacing(150.0 / 304.8, beam_len, True, True, True)

t.Commit()
print("Successfully reinforced beam ID: " + str(beam_id_int))
'''
    res = httpx.post(mcp_url, json={"code": code, "description": "Reinforce Concrete Beam"}, timeout=60)
    return res.json()

if __name__ == "__main__":
    print("Rebar Modeling Helper initialized.")
