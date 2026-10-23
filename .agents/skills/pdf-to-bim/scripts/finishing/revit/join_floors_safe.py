class _Swallow(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        for m in list(fa.GetFailureMessages()):
            if m.GetSeverity() == DB.FailureSeverity.Warning: fa.DeleteWarning(m)
            elif m.HasResolutions(): fa.ResolveFailure(m)
        return DB.FailureProcessingResult.ProceedWithCommit
pairs = []
for w in doc.GetWarnings():
    if "floors overlap" in w.GetDescriptionText():
        ids = list(w.GetFailingElements()) + list(w.GetAdditionalElements())
        if len(ids) == 2: pairs.append(ids)
t = DB.Transaction(doc, "MCP: join overlapping floors (safe)")
fho = t.GetFailureHandlingOptions(); fho.SetFailuresPreprocessor(_Swallow()); t.SetFailureHandlingOptions(fho); t.Start()
res = []
for a, b in pairs:
    A, B = doc.GetElement(a), doc.GetElement(b)
    try:
        if not DB.JoinGeometryUtils.AreElementsJoined(doc, A, B): DB.JoinGeometryUtils.JoinGeometry(doc, A, B)
        res.append("ok")
    except Exception as e:
        res.append(str(e)[:60])
t.Commit()
print(res, [DB.JoinGeometryUtils.AreElementsJoined(doc, doc.GetElement(a), doc.GetElement(b)) for a, b in pairs])
