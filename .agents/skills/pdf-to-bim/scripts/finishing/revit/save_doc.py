# IronPython: save the active document (no transaction may be open).
import os, datetime
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc   # DOC_TITLE: luu dung file (khi mo nhieu file)
before = doc.IsModified
if doc.IsModified:
    doc.Save()
path = doc.PathName
print("saved" if before else "nothing to save", "| modified now:", doc.IsModified, "|", path,
      "| file time:", datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%H:%M:%S"))
