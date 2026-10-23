import collections
c = collections.Counter(w.GetDescriptionText()[:70] for w in doc.GetWarnings())
for k, v in c.most_common(): print(v, k)
