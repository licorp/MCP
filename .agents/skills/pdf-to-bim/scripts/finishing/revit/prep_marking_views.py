# IronPython: chuan bi view marking plan theo mau Yarralumla: bat Floors trong template, view range theo level cua view (1500/1200/-1200/-1600), nong crop bao cau kien (+2 m).
# Chi ghi vao DOC_TITLE (neu co). VIEW_NAMES: danh sach view; mac dinh moi view MARKING PLAN theo level.
FT = 304.8
nm = lambda x: DB.Element.Name.__get__(x)
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc   # DOC_TITLE: chi ghi vao file nay (khi mo nhieu file)
VIEWS = globals().get("VIEW_NAMES", None)
views = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if not v.IsTemplate and "MARKING PLAN" in v.Name
         and v.GenLevel and ("LEVEL" in v.GenLevel.Name or "ROOF" in v.GenLevel.Name) and (VIEWS is None or v.Name in VIEWS)]
t = DB.Transaction(doc, "MCP: chuan bi view marking plan"); t.Start()
try:
    done_tpl = set(); out = []
    for v in views:
        tpl = doc.GetElement(v.ViewTemplateId)
        for src in [x for x in (tpl, v) if x is not None]:
            if src.Id.IntegerValue in done_tpl: continue
            try: src.SetCategoryHidden(DB.ElementId(DB.BuiltInCategory.OST_Floors), False)
            except Exception: pass
            try:
                vr = src.GetViewRange()
                for pl, off in ((DB.PlanViewPlane.TopClipPlane, 1500), (DB.PlanViewPlane.CutPlane, 1200),
                                (DB.PlanViewPlane.BottomClipPlane, -1200), (DB.PlanViewPlane.ViewDepthPlane, -1600)):
                    vr.SetLevelId(pl, DB.PlanViewRange.Current)      # theo level cua chinh view (nhu Yarralumla)
                    vr.SetOffset(pl, off / FT)
                src.SetViewRange(vr)
            except Exception as e:
                out.append(("view range", nm(src), str(e)[:60]))
            if src is tpl: done_tpl.add(src.Id.IntegerValue)
        # crop: bao cau kien cua level trong toa do view
        lv = v.GenLevel
        T = v.CropBox.Transform.Inverse
        xs, ys = [], []
        for bic in (DB.BuiltInCategory.OST_Floors, DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_StructuralColumns):
            for e in DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
                if e.LevelId != lv.Id: continue
                bb = e.get_BoundingBox(None)
                if bb is None: continue
                for x in (bb.Min.X, bb.Max.X):
                    for y in (bb.Min.Y, bb.Max.Y):
                        p = T.OfPoint(DB.XYZ(x, y, lv.Elevation)); xs.append(p.X); ys.append(p.Y)
        if xs:
            cb = v.CropBox; m = 2000 / FT
            cb.Min = DB.XYZ(min(xs) - m, min(ys) - m, cb.Min.Z); cb.Max = DB.XYZ(max(xs) + m, max(ys) + m, cb.Max.Z)
            v.CropBox = cb; v.CropBoxActive = True
            out.append((v.Name, "crop", round((max(xs) - min(xs)) * FT), round((max(ys) - min(ys)) * FT)))
    t.Commit()
    for o in out: print(o)
except Exception as e:
    t.RollBack(); print("ROLLED BACK: " + str(e))
