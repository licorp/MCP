"""
Inject 3D PT Tendons into Autodesk Revit via pyRevit MCP server.
Creates HermiteSpline DirectShapes in OST_GenericModel category and sets up dedicated 3D view.
"""
import httpx
import json
import sys
import os

def import_tendons(tendons_3d_json_path, view_name="3D - PT TENDONS", mcp_url="http://localhost:48884/revit_mcp/execute_code/"):
    with open(tendons_3d_json_path, "r", encoding="utf-8") as f:
        tendons = json.load(f)

    # Convert tendons to string representation for IronPython execution
    tendons_json_escaped = json.dumps(tendons)

    code = f'''
import json
from System.Collections.Generic import List

tendons_data = json.loads({json.dumps(tendons_json_escaped)})

t = DB.Transaction(doc, "Generate 3D PT Tendons")
t.Start()

cat_id = DB.ElementId(DB.BuiltInCategory.OST_GenericModel)
created_ids = []

for idx, pts_raw in enumerate(tendons_data):
    if len(pts_raw) < 2:
        continue
    
    # Filter close points (> 20mm / 0.065 ft) to satisfy Revit minimum curve tolerance
    clean_pts = []
    for p in pts_raw:
        xyz = DB.XYZ(p[0], p[1], p[2])
        if not clean_pts or xyz.DistanceTo(clean_pts[-1]) > 0.065:
            clean_pts.append(xyz)
            
    if len(clean_pts) < 2:
        continue
        
    try:
        pt_list = List[DB.XYZ]()
        for pt in clean_pts:
            pt_list.Add(pt)
            
        curve = DB.HermiteSpline.Create(pt_list, False)
        
        ds = DB.DirectShape.CreateElement(doc, cat_id)
        ds.ApplicationId = "PT_Tendon_Generator"
        ds.ApplicationDataId = "Tendon_{}".format(idx + 1)
        
        geom_list = List[DB.GeometryObject]()
        geom_list.Add(curve)
        ds.SetShape(geom_list)
        
        # Set comments / mark if available
        param_comment = ds.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if param_comment and not param_comment.IsReadOnly:
            param_comment.Set("PT Tendon #{}".format(idx + 1))
            
        created_ids.append(ds.Id.IntegerValue)
    except Exception as ex:
        print("Error on tendon {}: {}".format(idx + 1, str(ex)))

t.Commit()
print("SUCCESS: Created {} 3D PT Tendons!".format(len(created_ids)))

# Setup dedicated 3D view
try:
    vft = None
    for ft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType).ToElements():
        if ft.ViewFamily == DB.ViewFamily.ThreeDimensional:
            vft = ft
            break
            
    view_name_target = "{view_name}"
    existing_view = None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D).ToElements():
        if v.Name == view_name_target:
            existing_view = v
            break
            
    t_view = DB.Transaction(doc, "Setup Dedicated 3D PT View")
    t_view.Start()
    
    if not existing_view:
        view3d = DB.View3D.CreateIsometric(doc, vft.Id)
        view3d.Name = view_name_target
    else:
        view3d = existing_view
        
    view3d.DisplayStyle = DB.DisplayStyle.Shading
    
    # Transparency 80% for concrete elements
    og_trans = DB.OverrideGraphicSettings()
    og_trans.SetSurfaceTransparency(80)
    for bic in [DB.BuiltInCategory.OST_Floors, DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_StructuralFraming, DB.BuiltInCategory.OST_StructuralColumns]:
        view3d.SetCategoryOverrides(DB.ElementId(bic), og_trans)
        
    # Highlight Generic Models (Magenta, weight 4)
    cat_gm = DB.ElementId(DB.BuiltInCategory.OST_GenericModel)
    view3d.SetCategoryHidden(cat_gm, False)
    og_gm = DB.OverrideGraphicSettings()
    og_gm.SetProjectionLineColor(DB.Color(255, 0, 128))
    og_gm.SetProjectionLineWeight(4)
    view3d.SetCategoryOverrides(cat_gm, og_gm)
    
    t_view.Commit()
    print("Dedicated 3D view configured: " + view3d.Name)
except Exception as ex:
    print("View setup warning: " + str(ex))
'''

    res = httpx.post(mcp_url, json={"code": code, "description": "Generate PT Tendons in Revit"}, timeout=120)
    return res.json()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_to_revit.py <tendons_3d_json> [view_name]")
        sys.exit(1)
    json_path = sys.argv[1]
    vname = sys.argv[2] if len(sys.argv) > 2 else "3D - PT TENDONS"
    resp = import_tendons(json_path, view_name=vname)
    print("Revit response:", resp.get("output", resp))
