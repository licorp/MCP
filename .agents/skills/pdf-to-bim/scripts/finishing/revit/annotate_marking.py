# IronPython: tag + dim marking plan (tang) TRANH VA CHAM: khong de len tuong/cot/mep san, cac tag khong chong nhau. VIEW_NAMES, DOC_TITLE chen boi run_code.py.
# Thu tu: tag tuong -> tag cot -> dim dai san -> tag san. Moi doi tuong thu nhieu vi tri, lay vi tri dau tien khong va cham.
import math
FT = 304.8
nm = lambda x: DB.Element.Name.__get__(x)
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc   # DOC_TITLE: chi ghi vao file nay (khi mo nhieu file)
VIEWS = globals().get("VIEW_NAMES", ["BUILDING B - LEVEL 02 - MARKING PLAN"])
RAIL = ("PBS1", "PC1", "UPSTAND")
GAP = 60 / FT                       # khe ho toi thieu giua chu va vat can
WMIN, WMAX, LMIN = 600 / FT, 2500 / FT, 1500 / FT


def tag_type(bic, fam, typ):
    for s in DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType():
        if s.FamilyName == fam and nm(s) == typ:
            return s
    raise Exception("khong co tag %s : %s" % (fam, typ))


class Swallow(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        for m in list(fa.GetFailureMessages()):
            if m.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(m)
        return DB.FailureProcessingResult.Continue


# ---------- hinh hoc 2D ----------
def seg_rect_dist(a, b, r):
    """khoang cach doan thang ab toi hinh chu nhat r=(x0,y0,x1,y1); 0 neu cat/nam trong."""
    x0, y0, x1, y1 = r
    def inside(p): return x0 <= p[0] <= x1 and y0 <= p[1] <= y1
    if inside(a) or inside(b): return 0.0
    cs = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    def inter(p, q, s, t):
        d = (q[0]-p[0])*(t[1]-s[1]) - (q[1]-p[1])*(t[0]-s[0])
        if abs(d) < 1e-12: return False
        u = ((s[0]-p[0])*(t[1]-s[1]) - (s[1]-p[1])*(t[0]-s[0])) / d
        w = ((s[0]-p[0])*(q[1]-p[1]) - (s[1]-p[1])*(q[0]-p[0])) / d
        return 0 <= u <= 1 and 0 <= w <= 1
    for i in range(4):
        if inter(a, b, cs[i], cs[(i+1) % 4]): return 0.0
    def pd(p, s, t):
        dx, dy = t[0]-s[0], t[1]-s[1]; L = dx*dx + dy*dy
        k = 0 if L == 0 else max(0, min(1, ((p[0]-s[0])*dx + (p[1]-s[1])*dy) / L))
        return math.hypot(p[0]-s[0]-k*dx, p[1]-s[1]-k*dy)
    m = min(pd(c, a, b) for c in cs)
    for p in (a, b):
        dx = max(x0 - p[0], 0, p[0] - x1); dy = max(y0 - p[1], 0, p[1] - y1)
        m = min(m, math.hypot(dx, dy))
    return m


def rect_hit(r, segs, rects):
    for a, b, rad in segs:
        if seg_rect_dist(a, b, r) < rad + GAP: return True
    for q in rects:
        if not (r[2] + GAP < q[0] or q[2] + GAP < r[0] or r[3] + GAP < q[1] or q[3] + GAP < r[1]): return True
    return False


def box_of(el, v):
    bb = el.get_BoundingBox(v)
    return (bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y) if bb else None


def tess(curve, n=12):
    if isinstance(curve, DB.Line): return [curve.GetEndPoint(0), curve.GetEndPoint(1)]
    return [curve.Evaluate(i / float(n), True) for i in range(n + 1)]


t = DB.Transaction(doc, "MCP: tag + dim tranh va cham")
fho = t.GetFailureHandlingOptions(); fho.SetFailuresPreprocessor(Swallow()); t.SetFailureHandlingOptions(fho)
t.Start()
try:
    WT = {k: tag_type(DB.BuiltInCategory.OST_WallTags, "HPCE_Wall+Cm_TypeMark Tag", v) for k, v in (("", "WALL MARK"), ("o", "WALL OVER"), ("u", "WALL MARK (u)"))}
    CT = {k: tag_type(DB.BuiltInCategory.OST_StructuralColumnTags, "HPCE_Column_Mark Tag", v) for k, v in (("", "COLUMN"), ("o", "COLUMN OVER"), ("u", "COLUMN UNDER"))}
    STg = {False: tag_type(DB.BuiltInCategory.OST_FloorTags, "Hpce_Slab Thick Tag", "Thick"), True: tag_type(DB.BuiltInCategory.OST_FloorTags, "Hpce_Slab Thick Tag", "Thick+MIN")}
    dt = [d for d in DB.FilteredElementCollector(doc).OfClass(DB.DimensionType) if nm(d) == "2.5 MS GOTHIC INLNE"][0]
    levels = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.Elevation)
    report = []
    for vname in VIEWS:
        v = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if x.Name == vname and not x.IsTemplate][0]
        lv = v.GenLevel; z = lv.Elevation
        bname = lv.Name.split("-")[0]
        below = [l for l in levels if l.Name.startswith(bname) and l.Elevation < lv.Elevation - 0.1]
        lb = below[-1] if below else None
        for e in list(DB.FilteredElementCollector(doc, v.Id).OfClass(DB.IndependentTag)): doc.Delete(e.Id)
        for d in list(DB.FilteredElementCollector(doc, v.Id).OfClass(DB.Dimension)):
            if d.GetTypeId() == dt.Id: doc.Delete(d.Id)
        walls = [w for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall) if isinstance(w.Location, DB.LocationCurve)]
        up = [w for w in walls if w.LevelId == lv.Id]
        dn = [w for w in walls if lb is not None and w.LevelId == lb.Id and not any(r in nm(w.WallType) for r in RAIL)]
        cols = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType())
        cu = [c for c in cols if c.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).AsElementId() == lv.Id]
        cd = [c for c in cols if lb is not None and c.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).AsElementId() == lb.Id]
        floors = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.Floor) if f.LevelId == lv.Id]
        # vat can: tuong (capsule), cot (hop), mep san (doan, ban kinh 0)
        segs, rects = [], []
        for w in up + dn:
            P = tess(w.Location.Curve); r = w.Width / 2.0
            for i in range(len(P) - 1): segs.append(((P[i].X, P[i].Y), (P[i+1].X, P[i+1].Y), r))
        for c in cu + cd:
            b = box_of(c, None)
            if b: rects.append(b)
        opt = DB.Options(); opt.ComputeReferences = True; opt.View = v
        fedges = {}
        for f in floors:
            E = []
            for g in f.get_Geometry(opt):
                sol = [g] if isinstance(g, DB.Solid) else ([x for x in g.GetInstanceGeometry() if isinstance(x, DB.Solid)] if isinstance(g, DB.GeometryInstance) else [])
                for so in sol:
                    if so.Volume <= 0: continue
                    for face in so.Faces:
                        if isinstance(face, DB.PlanarFace) and face.FaceNormal.Z > 0.99:
                            for loop in face.EdgeLoops:
                                for e in loop:
                                    c = e.AsCurve(); E.append((e.Reference, c))
                                    P = tess(c, 8)
                                    for i in range(len(P) - 1): segs.append(((P[i].X, P[i].Y), (P[i+1].X, P[i+1].Y), 0.0))
            fedges[f.Id.IntegerValue] = E
        n = {"tag": 0, "dim": 0, "skip": 0}

        def place(elem, ttype, cands):
            """tao tag, do kich thuoc chu 1 lan, roi thu cac vi tri; khong co cho trong -> xoa tag."""
            tg = DB.IndependentTag.Create(doc, ttype.Id, v.Id, DB.Reference(elem), False, DB.TagOrientation.Horizontal, cands[0])
            doc.Regenerate()
            b = box_of(tg, v); h = tg.TagHeadPosition
            if b is None: return None
            rel = (b[0] - h.X, b[1] - h.Y, b[2] - h.X, b[3] - h.Y)
            for p in cands:
                r = (p.X + rel[0], p.Y + rel[1], p.X + rel[2], p.Y + rel[3])
                if not rect_hit(r, segs, rects):
                    tg.TagHeadPosition = DB.XYZ(p.X, p.Y, h.Z)
                    rects.append(r); n["tag"] += 1
                    return tg
            doc.Delete(tg.Id); n["skip"] += 1
            return None

        def wall_cands(w):
            c = w.Location.Curve; out = []
            for tt in (0.5, 0.35, 0.65, 0.2, 0.8):
                p = c.Evaluate(tt, True); d = c.ComputeDerivatives(tt, True).BasisX.Normalize(); nn = DB.XYZ(-d.Y, d.X, 0)
                for off in (450, 700, 1000, 1400):
                    for s in (1, -1): out.append(DB.XYZ(p.X, p.Y, z) + nn * (s * off / FT))
            return out

        def same(a, b2):
            ca = a.Location.Curve; mb = b2.Location.Curve.Evaluate(0.5, True)
            return ca.Distance(DB.XYZ(mb.X, mb.Y, ca.GetEndPoint(0).Z)) < 0.5 and abs(ca.Length - b2.Location.Curve.Length) < 3.0
        # lan can: 1 tag / chuoi
        rails = [w for w in up if any(r in nm(w.WallType) for r in RAIL)]
        par = dict((w.Id.IntegerValue, w.Id.IntegerValue) for w in rails)
        def fnd(i):
            while par[i] != i: par[i] = par[par[i]]; i = par[i]
            return i
        for i1, a in enumerate(rails):
            ea = [a.Location.Curve.GetEndPoint(0), a.Location.Curve.GetEndPoint(1)]
            for b2 in rails[i1 + 1:]:
                if b2.WallType.Id != a.WallType.Id: continue
                eb = [b2.Location.Curve.GetEndPoint(0), b2.Location.Curve.GetEndPoint(1)]
                if min(p.DistanceTo(q) for p in ea for q in eb) < 1.0: par[fnd(a.Id.IntegerValue)] = fnd(b2.Id.IntegerValue)
        best = {}
        for w in rails:
            r0 = fnd(w.Id.IntegerValue)
            if r0 not in best or w.Location.Curve.Length > best[r0].Location.Curve.Length: best[r0] = w
        keep = set(w.Id.IntegerValue for w in best.values())
        for w in sorted(up, key=lambda x: -x.Location.Curve.Length):
            rail = any(r in nm(w.WallType) for r in RAIL)
            if rail and w.Id.IntegerValue not in keep: continue
            k = "o" if (rail or not any(same(w, d) for d in dn)) else ""
            place(w, WT[k], wall_cands(w))
        for d0 in dn:
            if not any(same(w, d0) for w in up): place(d0, WT["u"], wall_cands(d0))
        near = lambda a, b2: a.Location.Point.DistanceTo(DB.XYZ(b2.Location.Point.X, b2.Location.Point.Y, a.Location.Point.Z)) < 1.0
        def col_cands(c):
            p = c.Location.Point; out = []
            for r in (650, 900, 1200, 1600):
                for ang in (0, 180, 90, 270, 45, 135, 315, 225):
                    a = math.radians(ang); out.append(DB.XYZ(p.X + math.cos(a) * r / FT, p.Y + math.sin(a) * r / FT, z))
            return out
        for c in cu:
            place(c, CT["" if any(near(c, x) for x in cd) else "o"], col_cands(c))
        for c in cd:
            if not any(near(c, x) for x in cu): place(c, CT["u"], col_cands(c))
        # dim be rong dai san: truot doc dai toi cho trong
        for f in floors:
            E = [(r, c) for r, c in fedges[f.Id.IntegerValue] if isinstance(c, DB.Line) and c.Length > LMIN and r is not None]
            used = set(); pairs = []
            for i in range(len(E)):
                for j in range(i + 1, len(E)):
                    ca, cb = E[i][1], E[j][1]; da = ca.Direction
                    if abs(abs(da.DotProduct(cb.Direction)) - 1) > 1e-4: continue
                    nn = DB.XYZ(-da.Y, da.X, 0).Normalize(); p0 = ca.GetEndPoint(0)
                    sd = (cb.GetEndPoint(0) - p0).DotProduct(nn); w_ = abs(sd)
                    if not (WMIN <= w_ <= WMAX): continue
                    ta = sorted([0.0, (ca.GetEndPoint(1) - p0).DotProduct(da)])
                    tb = sorted([(cb.GetEndPoint(0) - p0).DotProduct(da), (cb.GetEndPoint(1) - p0).DotProduct(da)])
                    lo, hi = max(ta[0], tb[0]), min(ta[1], tb[1])
                    if hi - lo >= LMIN: pairs.append((hi - lo, i, j, lo, hi, p0, da, nn * (1 if sd > 0 else -1), w_))
            pairs.sort(key=lambda x: -x[0])
            for L, i, j, lo, hi, p0, da, nn, w_ in pairs:
                if i in used or j in used: continue
                done = False
                for fr in (0.5, 0.3, 0.7, 0.15, 0.85, 0.4, 0.6):
                    s = lo + (hi - lo) * fr
                    a = DB.XYZ(p0.X, p0.Y, z) + da * s; b = a + nn * w_
                    m = (a + b) * 0.5
                    hw = 450 / FT; hh = 180 / FT         # hop chu dim uoc luong (4 so, cao 2.5 mm @1:100)
                    # chu dim song song duong dim -> hop xoay; lay AABB bao
                    ux, uy = nn.X, nn.Y
                    xs = [m.X + sx * hw * ux - sy * hh * uy for sx in (-1, 1) for sy in (-1, 1)]
                    ys = [m.Y + sx * hw * uy + sy * hh * ux for sx in (-1, 1) for sy in (-1, 1)]
                    r = (min(xs), min(ys), max(xs), max(ys))
                    if rect_hit(r, [sg for sg in segs if sg[2] > 0], rects): continue
                    ra = DB.ReferenceArray(); ra.Append(E[i][0]); ra.Append(E[j][0])
                    try:
                        doc.Create.NewDimension(v, DB.Line.CreateBound(a, b), ra, dt)
                        rects.append(r); n["dim"] += 1; done = True; break
                    except Exception:
                        pass
                if done: used.add(i); used.add(j)
                else: n["skip"] += 1
        # tag san: diem trong san, uu tien gan tam, khong va cham
        for f in floors:
            top = DB.HostObjectUtils.GetTopFaces(f)
            face = f.GetGeometryObjectFromReference(top[0]) if top else None
            if face is None: continue
            bb = face.GetBoundingBox(); cands = []
            for fx in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9):
                for fy in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9):
                    uv = DB.UV(bb.Min.U + (bb.Max.U - bb.Min.U) * fx, bb.Min.V + (bb.Max.V - bb.Min.V) * fy)
                    if face.IsInside(uv):
                        p = face.Evaluate(uv); cands.append(DB.XYZ(p.X, p.Y, z))
            if not cands: continue
            mn = f.get_Parameter(DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).AsDouble() * FT < -50
            place(f, STg[mn], cands)
        report.append((vname, n))
    t.Commit()
    for r in report: print(r)
except Exception as e:
    import traceback
    t.RollBack(); print("ROLLED BACK: " + str(e)); traceback.print_exc()
