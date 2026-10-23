import System
# IronPython: export an isometric of the whole model (temp 3D view, no transaction leaks).
import os
FT = 304.8
out = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "iso")
vft = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType) if x.ViewFamily == DB.ViewFamily.ThreeDimensional][0]
t = DB.Transaction(doc, "MCP temp iso"); t.Start()
try:
    v = DB.View3D.CreateIsometric(doc, vft.Id)
    eye = DB.XYZ(60000 / FT, 180000 / FT, 60000 / FT)   # from south-west, above
    tgt = DB.XYZ(100000 / FT, 255000 / FT, 5000 / FT)
    fwd = (tgt - eye).Normalize()
    up = fwd.CrossProduct(DB.XYZ.BasisZ).CrossProduct(fwd).Normalize()
    v.SetOrientation(DB.ViewOrientation3D(eye, up, fwd))
    v.DisplayStyle = DB.DisplayStyle.ShadingWithEdges
    v.DetailLevel = DB.ViewDetailLevel.Medium
    for c in (DB.BuiltInCategory.OST_RvtLinks, DB.BuiltInCategory.OST_Levels, DB.BuiltInCategory.OST_Grids, DB.BuiltInCategory.OST_SectionBox):
        try: v.SetCategoryHidden(DB.ElementId(c), True)
        except: pass
    bb = DB.BoundingBoxXYZ(); bb.Min = DB.XYZ(55000/FT, 224000/FT, -1000/FT); bb.Max = DB.XYZ(146000/FT, 286000/FT, 16000/FT)
    v.SetSectionBox(bb)
    v.SetCategoryHidden(DB.ElementId(DB.BuiltInCategory.OST_SectionBox), True)
    doc.Regenerate()
    o = DB.ImageExportOptions()
    o.ExportRange = DB.ExportRange.SetOfViews
    o.SetViewsAndSheets(System.Collections.Generic.List[DB.ElementId]([v.Id]))
    o.FilePath = out
    o.HLRandWFViewsFileType = DB.ImageFileType.PNG
    o.ShadowViewsFileType = DB.ImageFileType.PNG
    o.ImageResolution = DB.ImageResolution.DPI_150
    o.ZoomType = DB.ZoomFitType.FitToPage
    o.PixelSize = 12000
    doc.ExportImage(o)
finally:
    t.RollBack()
print([f for f in os.listdir(os.path.dirname(out)) if f.startswith("iso")])
