# IronPython: xuat anh PNG cac view trong VIEW_NAMES ra %LOCALAPPDATA%/RevitMCPPython/viewimg - <loai> - <ten>.png (cat vien bang crop_png.py).
import os, System
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc   # DOC_TITLE: chi ghi vao file nay (khi mo nhieu file)
VN = globals().get("VIEW_NAMES", ["BUILDING B - LEVEL 02 - MARKING PLAN"])
out = os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "viewimg")
ids = System.Collections.Generic.List[DB.ElementId]([v.Id for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if v.Name in VN and not v.IsTemplate])
o = DB.ImageExportOptions(); o.ExportRange = DB.ExportRange.SetOfViews; o.SetViewsAndSheets(ids); o.FilePath = out
o.HLRandWFViewsFileType = DB.ImageFileType.PNG; o.ShadowViewsFileType = DB.ImageFileType.PNG
o.ZoomType = DB.ZoomFitType.FitToPage; o.PixelSize = 5000; o.ImageResolution = DB.ImageResolution.DPI_150
doc.ExportImage(o)
print([f for f in os.listdir(os.path.dirname(out)) if f.startswith("viewimg")])
