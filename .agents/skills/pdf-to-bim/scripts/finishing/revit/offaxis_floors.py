import json, os
line2floor = {}
for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor):
    sk = doc.GetElement(f.SketchId)
    if sk is None: continue
    for i in sk.GetAllElements(): line2floor[i.IntegerValue] = f.Id.IntegerValue
ids = set()
for w in doc.GetWarnings():
    if "off axis" not in w.GetDescriptionText(): continue
    for i in w.GetFailingElements():
        if i.IntegerValue in line2floor: ids.add(line2floor[i.IntegerValue])
with open(os.path.join(os.environ["LOCALAPPDATA"], "RevitMCPPython", "offaxis_ids.json"), "w") as fh: fh.write(json.dumps(sorted(ids)))
print(len(ids), sorted(ids))
