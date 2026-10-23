# IronPython: save the active document (no transaction may be open).
import os, datetime
before = doc.IsModified
if doc.IsModified:
    doc.Save()
path = doc.PathName
print("saved" if before else "nothing to save", "| modified now:", doc.IsModified, "|", path,
      "| file time:", datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%H:%M:%S"))
