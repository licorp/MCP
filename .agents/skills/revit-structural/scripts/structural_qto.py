"""
Extract concrete volumes and rebar take-off quantities (QTO) via pyRevit MCP.
"""
import httpx
import json

def extract_structural_qto(mcp_url="http://localhost:48884/revit_mcp/execute_code/"):
    code = '''
from Autodesk.Revit import DB
import json

# 1. Concrete Volumes (m3)
cats = [
    ("Beams", DB.BuiltInCategory.OST_StructuralFraming),
    ("Columns", DB.BuiltInCategory.OST_StructuralColumns),
    ("Floors", DB.BuiltInCategory.OST_Floors),
    ("Foundations", DB.BuiltInCategory.OST_StructuralFoundation)
]

concrete_qto = {}
total_vol_m3 = 0.0

for name, cat in cats:
    collector = DB.FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType().ToElements()
    cat_vol = 0.0
    for el in collector:
        param_vol = el.get_Parameter(DB.BuiltInParameter.HOST_VOLUME_COMPUTED)
        if param_vol and param_vol.HasValue:
            # 1 cu.ft = 0.0283168 m3
            cat_vol += param_vol.AsDouble() * 0.0283168
    concrete_qto[name] = round(cat_vol, 2)
    total_vol_m3 += cat_vol

# 2. Rebar Schedule (kg)
rebar_collector = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rebar).WhereElementIsNotElementType().ToElements()
rebar_qto = {}
total_weight_kg = 0.0

for r in rebar_collector:
    # Lấy đường kính thanh (ft -> mm)
    bar_type = doc.GetElement(r.GetTypeId())
    bar_name = bar_type.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if bar_type else "Unknown"
    
    # Lấy tổng chiều dài (ft -> m)
    param_len = r.get_Parameter(DB.BuiltInParameter.REBAR_ELEM_TOTAL_LENGTH)
    total_len_m = param_len.AsDouble() * 0.3048 if param_len else 0.0
    
    # Tính đường kính từ tên hoặc tham số
    try:
        # Nếu tên dạng D20 hoặc 20mm
        d_mm = float(''.join(c for c in bar_name if c.isdigit()))
    except:
        d_mm = 16.0
        
    weight_kg = total_len_m * (d_mm * d_mm / 162.2)
    
    if bar_name not in rebar_qto:
        rebar_qto[bar_name] = {"length_m": 0.0, "weight_kg": 0.0}
    rebar_qto[bar_name]["length_m"] += total_len_m
    rebar_qto[bar_name]["weight_kg"] += weight_kg
    total_weight_kg += weight_kg

for k in rebar_qto:
    rebar_qto[k]["length_m"] = round(rebar_qto[k]["length_m"], 1)
    rebar_qto[k]["weight_kg"] = round(rebar_qto[k]["weight_kg"], 1)

report = {
    "concrete_volume_m3": concrete_qto,
    "total_concrete_m3": round(total_vol_m3, 2),
    "rebar_breakdown": rebar_qto,
    "total_rebar_kg": round(total_weight_kg, 1)
}
print(json.dumps(report, indent=2))
'''
    res = httpx.post(mcp_url, json={"code": code, "description": "Extract Structural QTO"}, timeout=60)
    return res.json()

if __name__ == "__main__":
    print("Structural QTO Helper initialized.")
