"""
Batch create structural columns, beams, floors, and foundations via pyRevit MCP.
"""
import httpx
import json
import sys

def create_structural_framing(beams_data, mcp_url="http://localhost:48884/revit_mcp/execute_code/"):
    """
    beams_data: list of dicts:
    [
        {"start": [x1, y1, z1], "end": [x2, y2, z2], "level": "Level 1", "type": "400x700mm", "mark": "B1"}
    ]
    """
    code = f'''
import json
from Autodesk.Revit import DB

beams = json.loads({json.dumps(json.dumps(beams_data))})

t = DB.Transaction(doc, "Batch Create Structural Beams")
t.Start()

created_count = 0
errors = []

# Tìm level và family symbol
levels = {{l.Name: l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()}}
beam_symbols = {{s.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString(): s 
                for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_StructuralFraming).ToElements()}}

default_symbol = None
for s in beam_symbols.values():
    default_symbol = s
    break

if default_symbol and not default_symbol.IsActive:
    default_symbol.Activate()

for b in beams:
    try:
        p1 = DB.XYZ(b["start"][0] / 304.8, b["start"][1] / 304.8, b["start"][2] / 304.8)
        p2 = DB.XYZ(b["end"][0] / 304.8, b["end"][1] / 304.8, b["end"][2] / 304.8)
        lvl_name = b.get("level", "")
        lvl = levels.get(lvl_name, list(levels.values())[0])
        
        sym_name = b.get("type", "")
        sym = beam_symbols.get(sym_name, default_symbol)
        
        line = DB.Line.CreateBound(p1, p2)
        inst = doc.Create.NewFamilyInstance(line, sym, lvl, DB.Structure.StructuralType.Beam)
        
        mark = b.get("mark")
        if mark:
            inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK).Set(str(mark))
            
        created_count += 1
    except Exception as ex:
        errors.append(str(ex))

t.Commit()
print("Created " + str(created_count) + " beams. Errors: " + str(len(errors)))
'''
    res = httpx.post(mcp_url, json={"code": code, "description": "Batch Create Structural Beams"}, timeout=60)
    return res.json()

if __name__ == "__main__":
    print("Structural Modeling Helper initialized.")
