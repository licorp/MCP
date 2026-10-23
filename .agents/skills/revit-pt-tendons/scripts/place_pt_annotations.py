"""
Place 2D PT Tendon Lines, CGS Height TextNotes, and Tick Mark Indicator Lines on Revit Floor Plan Views.
Strictly adheres to AutoCAD DWG drafting conventions:
- Horizontal cables (CABLES): Green DetailCurve, Yellow Text (Horizontal along cable), Yellow Tick marks (200mm)
- Vertical cables (CABLES1): Red DetailCurve, Blue Text (Vertical along cable), Blue Tick marks (200mm)
- Text and curves are perfectly aligned with the view's active Scope Box.
"""
import httpx
import json
import sys
import os

def annotate_pt_plan(anno_json_path, cables_2d_json_path=None, view_name="BUILDING 1 - GROUND POST TENSIONING", clear_existing=True, mcp_url="http://localhost:48884/revit_mcp/execute_code/"):
    with open(anno_json_path, "r", encoding="utf-8") as f:
        anno_data = json.load(f)

    cables_data = []
    if cables_2d_json_path and os.path.exists(cables_2d_json_path):
        with open(cables_2d_json_path, "r", encoding="utf-8") as f:
            cables_data = json.load(f)

    code = f'''
import json
import math

view_name_target = "{view_name}"
target_view = None
for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan).ToElements():
    if v.Name == view_name_target:
        target_view = v
        break

if not target_view:
    print("Error: View not found: " + view_name_target)
else:
    t = DB.Transaction(doc, "Draw PT Cables and Matched Annotations")
    t.Start()

    # 1. Clean existing PT elements in view if requested
    if {str(clear_existing)}:
        collector_curves = DB.FilteredElementCollector(doc, target_view.Id).OfClass(DB.CurveElement).ToElements()
        for c in collector_curves:
            try:
                ls_name = c.LineStyle.Name
                if "PT Tendon" in ls_name or "PT Tick" in ls_name:
                    doc.Delete(c.Id)
            except:
                pass

        collector_tns = DB.FilteredElementCollector(doc, target_view.Id).OfClass(DB.TextNote).ToElements()
        for tn in collector_tns:
            try:
                tnt_name = doc.GetElement(tn.GetTypeId()).get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                if "PT - CGS Elevation" in tnt_name:
                    doc.Delete(tn.Id)
            except:
                pass

    # 2. Setup Line Styles for Cables & Ticks
    lines_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    style_red = None
    style_green = None
    style_tick_blue = None
    style_tick_yellow = None

    for sc in lines_cat.SubCategories:
        if sc.Name == "PT Tendon - Red": style_red = sc
        elif sc.Name == "PT Tendon - Green": style_green = sc
        elif sc.Name == "PT Tick - Blue": style_tick_blue = sc
        elif sc.Name == "PT Tick - Yellow": style_tick_yellow = sc

    if not style_red:
        style_red = doc.Settings.Categories.NewSubcategory(lines_cat, "PT Tendon - Red")
        style_red.LineColor = DB.Color(230, 20, 20)
        style_red.SetLineWeight(4, DB.GraphicsStyleType.Projection)

    if not style_green:
        style_green = doc.Settings.Categories.NewSubcategory(lines_cat, "PT Tendon - Green")
        style_green.LineColor = DB.Color(0, 175, 0)
        style_green.SetLineWeight(4, DB.GraphicsStyleType.Projection)

    if not style_tick_blue:
        style_tick_blue = doc.Settings.Categories.NewSubcategory(lines_cat, "PT Tick - Blue")
        style_tick_blue.LineColor = DB.Color(0, 0, 230)
        style_tick_blue.SetLineWeight(3, DB.GraphicsStyleType.Projection)

    if not style_tick_yellow:
        style_tick_yellow = doc.Settings.Categories.NewSubcategory(lines_cat, "PT Tick - Yellow")
        style_tick_yellow.LineColor = DB.Color(215, 145, 0)
        style_tick_yellow.SetLineWeight(3, DB.GraphicsStyleType.Projection)

    gs_red = style_red.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    gs_green = style_green.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    gs_tick_blue = style_tick_blue.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    gs_tick_yellow = style_tick_yellow.GetGraphicsStyle(DB.GraphicsStyleType.Projection)

    # 3. Draw 2D Cables: Horizontal (CABLES) = GREEN, Vertical (CABLES1) = RED
    cables_raw = json.loads({json.dumps(json.dumps(cables_data))})
    curves_count = 0
    for c in cables_raw:
        lay = c.get("layer", "")
        cstyle = gs_green if lay == "CABLES" else gs_red
        pts = c.get("pts", [])
        for i in range(len(pts) - 1):
            p1 = DB.XYZ(pts[i][0], pts[i][1], 0.0)
            p2 = DB.XYZ(pts[i+1][0], pts[i+1][1], 0.0)
            if p1.DistanceTo(p2) > 0.033:
                try:
                    line = DB.Line.CreateBound(p1, p2)
                    dc = doc.Create.NewDetailCurve(target_view, line)
                    dc.LineStyle = cstyle
                    curves_count += 1
                except:
                    pass

    # 4. Setup Text Note Types: Blue and Yellow (2.5mm text size)
    type_blue = None
    type_yellow = None
    for tnt in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements():
        name = tnt.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        if name == "PT - CGS Elevation 2.5mm BLUE": type_blue = tnt
        elif name == "PT - CGS Elevation 2.5mm YELLOW": type_yellow = tnt

    base_type = None
    for tnt in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements():
        base_type = tnt
        break

    if not type_blue:
        type_blue = base_type.Duplicate("PT - CGS Elevation 2.5mm BLUE")
        type_blue.get_Parameter(DB.BuiltInParameter.LINE_COLOR).Set(16711680)

    if not type_yellow:
        type_yellow = base_type.Duplicate("PT - CGS Elevation 2.5mm YELLOW")
        type_yellow.get_Parameter(DB.BuiltInParameter.LINE_COLOR).Set(37335)

    # 5. Draw 2D Tick Lines (perpendicular to cables, 200mm length)
    anno_raw = json.loads({json.dumps(json.dumps(anno_data))})
    lines_list = anno_raw.get("lines", [])
    texts_list = anno_raw.get("texts", [])
    ticks_count = 0

    for l in lines_list:
        p1 = DB.XYZ(l["p1_ft"][0], l["p1_ft"][1], 0.0)
        p2 = DB.XYZ(l["p2_ft"][0], l["p2_ft"][1], 0.0)
        if p1.DistanceTo(p2) > 0.033:
            try:
                line_geom = DB.Line.CreateBound(p1, p2)
                dc = doc.Create.NewDetailCurve(target_view, line_geom)
                dc.LineStyle = gs_tick_blue if l.get("group") == "blue" else gs_tick_yellow
                ticks_count += 1
            except:
                pass

    # 6. Place CGS Text Notes matching cable directions:
    # Yellow text along Horizontal Green cables -> View.RightDirection (Horizontal on screen)
    # Blue text along Vertical Red cables -> View.UpDirection (Vertical on screen)
    v_right = target_view.RightDirection
    v_up = target_view.UpDirection
    texts_count = 0

    for item in texts_list:
        txt = item["text"]
        grp = item.get("group", "blue")
        is_yellow = (grp == "yellow")
        ttype = type_yellow if is_yellow else type_blue
        target_v = v_right if is_yellow else v_up # Yellow=Horizontal, Blue=Vertical
        
        origin = DB.XYZ(item["pt_ft"][0], item["pt_ft"][1], 0.0)
        try:
            tn = DB.TextNote.Create(doc, target_view.Id, origin, txt, ttype.Id)
            diff = abs(tn.BaseDirection.X - target_v.X) + abs(tn.BaseDirection.Y - target_v.Y)
            if diff > 0.05:
                current_ang = math.atan2(tn.BaseDirection.Y, tn.BaseDirection.X)
                target_ang = math.atan2(target_v.Y, target_v.X)
                correct_ang = target_ang - current_ang
                axis = DB.Line.CreateBound(origin, DB.XYZ(origin.X, origin.Y, origin.Z + 1.0))
                DB.ElementTransformUtils.RotateElement(doc, tn.Id, axis, correct_ang)
            texts_count += 1
        except:
            pass

    t.Commit()
    print("SUCCESS: Placed " + str(curves_count) + " cables, " + str(ticks_count) + " ticks, and " + str(texts_count) + " texts on " + target_view.Name)
'''

    res = httpx.post(mcp_url, json={"code": code, "description": "Draw PT Cables and Matched Annotations"}, timeout=60)
    return res.json()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python place_pt_annotations.py <anno_json> [cables_2d_json] [view_name]")
        sys.exit(1)
    janno = sys.argv[1]
    jcables = sys.argv[2] if len(sys.argv) > 2 else None
    vname = sys.argv[3] if len(sys.argv) > 3 else "BUILDING 1 - GROUND POST TENSIONING"
    resp = annotate_pt_plan(janno, cables_2d_json_path=jcables, view_name=vname)
    print("Response:", resp.get("output", resp))
