# IronPython: mat bang mong (FOOTING MARKING PLAN, mau to S200) - tag + dim TRANH VA CHAM.
# 1) dim mep mong -> MAT cot (kieu S201): cum mong >= 2 cot: 2 dau; mong 1 cot khong vuong: 1 dim theo phuong dai cot
# 2) tag mong (Type Mark) trong goc mong, 3) tag tuong, 4) tag cot (tag thuong, khong o/u).
# Vat can: tuong, cot, mep mong, net chu cua nen CAD (link DWG tu PDF: chu da no thanh net ngan < 350 mm), chu dim da dat.
# Tag/dim nam ngoai crop cua view -> bo. VIEW_NAMES, DOC_TITLE chen boi run_code.py.
# TEXT_JSON (khuyen dung): hop chu cua to PDF da quy ve model (pdf_text_obstacles.py) - vi chu TEXT trong DWG
# Revit API khong doc duoc; khong co thi dung net ngan cua CAD (chi bat duoc chu da no thanh net).
import math, os, json
FT = 304.8
nm = lambda x: DB.Element.Name.__get__(x)
doc = [d for d in __revit__.Application.Documents if d.Title == DOC_TITLE][0] if globals().get("DOC_TITLE") else doc   # DOC_TITLE: chi ghi vao file nay (khi mo nhieu file)
VIEWS = globals().get("VIEW_NAMES", ["BUILDING A - FOOTING MARKING PLAN"])
GAP = 60 / FT                       # khe ho toi thieu giua chu va vat can
DIMTYPE = "2.5 MS GOTHIC INLNE"
CAD_STROKE = 350 / FT               # net CAD ngan hon -> net chu
CROP_IN = 100 / FT                  # le trong crop


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



def top_faces(el, v):
    opt = DB.Options(); opt.ComputeReferences = True; opt.View = v
    out = []
    for g in el.get_Geometry(opt):
        sol = [g] if isinstance(g, DB.Solid) else ([x for x in g.GetInstanceGeometry() if isinstance(x, DB.Solid)] if isinstance(g, DB.GeometryInstance) else [])
        for so in sol:
            if so.Volume <= 0: continue
            for face in so.Faces:
                if isinstance(face, DB.PlanarFace) and face.FaceNormal.Z > 0.99: out.append(face)
    return out


def cad_text_rects(v):
    """chu cua nen CAD (ImportInstance trong view): DWG chuyen tu PDF -> chu da no thanh net ngan; tra ve hop tung net."""
    opt = DB.Options(); opt.View = v
    items = []
    def walk(geo):
        for g in geo:
            if isinstance(g, DB.GeometryInstance):
                walk(g.GetInstanceGeometry()); continue
            try:
                if isinstance(g, DB.PolyLine): pts = list(g.GetCoordinates())
                elif isinstance(g, DB.Line): pts = [g.GetEndPoint(0), g.GetEndPoint(1)]
                elif isinstance(g, DB.Curve): pts = list(g.Tessellate())
                else: continue
            except Exception:
                continue
            xs = [p.X for p in pts]; ys = [p.Y for p in pts]
            if max(xs) - min(xs) < CAD_STROKE and max(ys) - min(ys) < CAD_STROKE:
                items.append((min(xs), min(ys), max(xs), max(ys)))
    for ii in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.ImportInstance):
        walk(ii.get_Geometry(opt))
    # moi net ngan la 1 vat can (gom cum de bo sot cum dinh vao net dut / hatch)
    return items, len(items)


class Grid(object):
    """chi muc luoi cho nhieu hop chu nhat (chu CAD)."""
    def __init__(self, rects, cs=1000 / FT):
        self.cs = cs; self.g = {}
        for r in rects: self.add(r)
    def keys(self, r):
        cs = self.cs
        for gx in range(int(math.floor(r[0] / cs)), int(math.floor(r[2] / cs)) + 1):
            for gy in range(int(math.floor(r[1] / cs)), int(math.floor(r[3] / cs)) + 1):
                yield (gx, gy)
    def add(self, r):
        for k in self.keys(r): self.g.setdefault(k, []).append(r)
    def hit(self, r):
        e = (r[0] - GAP, r[1] - GAP, r[2] + GAP, r[3] + GAP)
        for k in self.keys(e):
            for q in self.g.get(k, ()):
                if not (e[2] < q[0] or q[2] < e[0] or e[3] < q[1] or q[3] < e[1]): return True
        return False


t = DB.Transaction(doc, "MCP: tag + dim mat bang mong tranh va cham")
fho = t.GetFailureHandlingOptions(); fho.SetFailuresPreprocessor(Swallow()); t.SetFailureHandlingOptions(fho)
t.Start()
try:
    WT = tag_type(DB.BuiltInCategory.OST_WallTags, "HPCE_Wall+Cm_TypeMark Tag", "WALL MARK")
    CT = tag_type(DB.BuiltInCategory.OST_StructuralColumnTags, "HPCE_Column_Mark Tag", "COLUMN")
    FT_ = tag_type(DB.BuiltInCategory.OST_StructuralFoundationTags, "HPCE_Footing  Mark", "HPCE_Footing  Mark")
    dt = [d for d in DB.FilteredElementCollector(doc).OfClass(DB.DimensionType) if nm(d) == DIMTYPE][0]
    report = []
    for vname in VIEWS:
        v = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if x.Name == vname and not x.IsTemplate][0]
        lv = v.GenLevel; z = lv.Elevation
        for e in list(DB.FilteredElementCollector(doc, v.Id).OfClass(DB.IndependentTag)): doc.Delete(e.Id)
        for d in list(DB.FilteredElementCollector(doc, v.Id).OfClass(DB.Dimension)):
            if d.GetTypeId() == dt.Id: doc.Delete(d.Id)
        walls = [w for w in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.Wall) if isinstance(w.Location, DB.LocationCurve) and w.LevelId == lv.Id]
        cols = [c for c in DB.FilteredElementCollector(doc, v.Id).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType()
                if c.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).AsElementId() == lv.Id]
        fnds = list(DB.FilteredElementCollector(doc, v.Id).OfCategory(DB.BuiltInCategory.OST_StructuralFoundation).WhereElementIsNotElementType())
        # ---- crop ----
        cb = v.CropBox; Tinv = cb.Transform.Inverse; use_crop = v.CropBoxActive
        def in_crop_pt(x, y):
            if not use_crop: return True
            p = Tinv.OfPoint(DB.XYZ(x, y, z))
            return cb.Min.X + CROP_IN <= p.X <= cb.Max.X - CROP_IN and cb.Min.Y + CROP_IN <= p.Y <= cb.Max.Y - CROP_IN
        def in_crop(r):
            return all(in_crop_pt(x, y) for x in (r[0], r[2]) for y in (r[1], r[3]))
        # ---- vat can ----
        segs, rects = [], []
        for w in walls:
            P = tess(w.Location.Curve); r = w.Width / 2.0
            for i in range(len(P) - 1): segs.append(((P[i].X, P[i].Y), (P[i+1].X, P[i+1].Y), r))
        for c in cols:
            b = box_of(c, None)
            if b: rects.append(b)
        ffaces = {}
        for f in fnds:
            F = top_faces(f, v); ffaces[f.Id.IntegerValue] = F
            for face in F:
                for loop in face.EdgeLoops:
                    for e in loop:
                        P = tess(e.AsCurve(), 8)
                        for i in range(len(P) - 1): segs.append(((P[i].X, P[i].Y), (P[i+1].X, P[i+1].Y), 0.0))
        tj = globals().get("TEXT_JSON")
        if tj and os.path.exists(tj):
            with open(tj) as fh: ctext = [tuple(r) for r in json.loads(fh.read())["rects"]]
            nstroke = "pdf"
        else:
            ctext, nstroke = cad_text_rects(v)
        cad = Grid(ctext)
        n = {"tag": 0, "dim": 0, "dim_loi": 0, "skip": 0, "ngoai_crop": 0, "chu_vat_can": len(ctext)}
        def blocked(r):
            return (not in_crop(r)) or rect_hit(r, segs, rects) or cad.hit(r)

        def text_box(m, u, nn):
            hw, hh = 400 / FT, 330 / FT          # hop chu dim uoc luong 4 so (bao ca 2 phia duong dim)
            xs = [m.X + sx * hw * u.X + sy * hh * nn.X for sx in (-1, 1) for sy in (-1, 1)]
            ys = [m.Y + sx * hw * u.Y + sy * hh * nn.Y for sx in (-1, 1) for sy in (-1, 1)]
            return (min(xs), min(ys), max(xs), max(ys))
        # ================= 1) DIM mep mong -> MAT cot (kieu S201: 1750 = 2150 - 400) =================
        # Cum mong (mong chong nhau / ghep) co >= 2 cot: dim 2 dau, mep ngoai cum -> mat cot gan nhat.
        # Mong 1 cot, mong khong vuong (PF2, PF4...): 1 dim theo phuong dai cua cot. Mong vuong 1 cot dung tam: khong dim.
        def side_faces(el):
            """mat ben thang dung (normal, cac dinh, reference): Solid truc tiep (da join/cat) hoac GetSymbolGeometry + Transform.
            KHONG dung reference canh tu GetInstanceGeometry (Revit dat dim sai cho)."""
            out = []
            opt_ = DB.Options(); opt_.ComputeReferences = True
            for g in el.get_Geometry(opt_):
                if isinstance(g, DB.Solid):
                    T, src = DB.Transform.Identity, [g]
                elif isinstance(g, DB.GeometryInstance):
                    T, src = g.Transform, g.GetSymbolGeometry()
                else:
                    continue
                for so in src:
                    if not isinstance(so, DB.Solid) or so.Volume <= 0: continue
                    for fc in so.Faces:
                        if isinstance(fc, DB.PlanarFace) and abs(fc.FaceNormal.Z) < 0.01 and fc.Reference is not None:
                            P = [T.OfPoint(p) for lp in fc.EdgeLoops for e in lp for p in (e.AsCurve().GetEndPoint(0),)]
                            out.append((T.OfVector(fc.FaceNormal), P, fc.Reference))
            return out
        pads = [f for f in fnds if isinstance(f, DB.FamilyInstance) and ffaces[f.Id.IntegerValue]]
        pin = {}
        for f in pads:
            face = ffaces[f.Id.IntegerValue][0]; lst = []
            for c in cols:
                p = c.Location.Point
                pr = face.Project(DB.XYZ(p.X, p.Y, face.Origin.Z))
                if pr is not None and pr.Distance < 0.01: lst.append(c)
            pin[f.Id.IntegerValue] = lst
        pads = [f for f in pads if pin[f.Id.IntegerValue]]
        # cum mong: hop bao chong nhau > 50 mm
        par = dict((f.Id.IntegerValue, f.Id.IntegerValue) for f in pads)
        def fnd(i):
            while par[i] != i: par[i] = par[par[i]]; i = par[i]
            return i
        bbs = dict((f.Id.IntegerValue, f.get_BoundingBox(None)) for f in pads)
        for i1, a in enumerate(pads):
            A_ = bbs[a.Id.IntegerValue]
            for b in pads[i1 + 1:]:
                B_ = bbs[b.Id.IntegerValue]; ov = 50 / FT
                if min(A_.Max.X, B_.Max.X) - max(A_.Min.X, B_.Min.X) > ov and min(A_.Max.Y, B_.Max.Y) - max(A_.Min.Y, B_.Min.Y) > ov:
                    par[fnd(a.Id.IntegerValue)] = fnd(b.Id.IntegerValue)
        groups = {}
        for f in pads: groups.setdefault(fnd(f.Id.IntegerValue), []).append(f)
        sf_cache = {}
        def sfaces(el):
            k = el.Id.IntegerValue
            if k not in sf_cache: sf_cache[k] = side_faces(el)
            return sf_cache[k]
        for gp in groups.values():
            gcols = {}
            for f in gp:
                for c in pin[f.Id.IntegerValue]: gcols[c.Id.IntegerValue] = c
            gcols = list(gcols.values())
            f0 = gp[0]; o = f0.Location.Point
            axes = [DB.XYZ(f0.HandOrientation.X, f0.HandOrientation.Y, 0).Normalize(), DB.XYZ(f0.FacingOrientation.X, f0.FacingOrientation.Y, 0).Normalize()]
            def span(pts, u):
                s = [(p - o).DotProduct(u) for p in pts]; return min(s), max(s)
            if len(gcols) >= 2:
                d_ = gcols[-1].Location.Point - gcols[0].Location.Point
                u = max(axes, key=lambda a: abs(a.DotProduct(DB.XYZ(d_.X, d_.Y, 0))))
                ends = ("neg", "pos")
            else:
                c = gcols[0]
                cf = sfaces(c)
                ext = []
                for a in axes:
                    P = [p for nv, pts, rf in cf for p in pts]
                    lo, hi = span(P, a) if P else (0, 0); ext.append(hi - lo)
                u = axes[0] if ext[0] >= ext[1] else axes[1]                       # phuong dai cua cot
                gP = [p for f in gp for nv, pts, rf in sfaces(f) for p in pts]
                lo_u, hi_u = span(gP, u); lo_v, hi_v = span(gP, DB.XYZ(-u.Y, u.X, 0))
                if abs((hi_u - lo_u) - (hi_v - lo_v)) < 200 / FT and len(gp) == 1: continue   # mong vuong 1 cot dung tam
                ends = ("pos", "neg")                                              # 1 dim, thu phia + truoc
            nn = DB.XYZ(-u.Y, u.X, 0)
            pu = lambda p: (p - o).DotProduct(u)
            pv = lambda p: (p - o).DotProduct(nn)
            cs = sorted(gcols, key=lambda c: pu(c.Location.Point))
            placed_one = False
            for end in ends:
                if placed_one and len(gcols) == 1: break
                ce = cs[0] if end == "neg" else cs[-1]
                cv = pv(ce.Location.Point)
                # mep mong: mat ben vuong goc u, phu qua duong tim cot, cuc tri ve phia end
                cand = []
                for f in gp:
                    for nv, pts, rf in sfaces(f):
                        if abs(nv.DotProduct(u)) < 0.999: continue
                        vs = [pv(p) for p in pts]
                        if min(vs) - 0.03 <= cv <= max(vs) + 0.03: cand.append((sum(pu(p) for p in pts) / len(pts), rf))
                cfs = [(sum(pu(p) for p in pts) / len(pts), rf) for nv, pts, rf in sfaces(ce) if abs(nv.DotProduct(u)) > 0.999]
                if not cand or len(cfs) < 2: n["skip"] += 1; continue
                if end == "neg":
                    edge = min(cand, key=lambda x: x[0]); cface = min(cfs, key=lambda x: x[0])
                    chain = [edge, cface]
                else:
                    edge = max(cand, key=lambda x: x[0]); cface = max(cfs, key=lambda x: x[0])
                    chain = [cface, edge]
                want = chain[1][0] - chain[0][0]
                if want < 100 / FT: continue
                done = False
                for off in (0, 450, -450, 900, -900, 1300, -1300):
                    base = o + nn * (cv + off / FT)
                    A = base + u * chain[0][0]; B = base + u * chain[1][0]
                    A = DB.XYZ(A.X, A.Y, z); B = DB.XYZ(B.X, B.Y, z)
                    m = (A + B) * 0.5
                    box = text_box(m, u, nn)
                    if blocked(box): continue
                    ra = DB.ReferenceArray(); ra.Append(chain[0][1]); ra.Append(chain[1][1])
                    try:
                        dm = doc.Create.NewDimension(v, DB.Line.CreateBound(A, B), ra, dt)
                    except Exception:
                        n["dim_loi"] += 1; break
                    if dm.Value is None or abs(dm.Value - want) > 20 / FT:
                        doc.Delete(dm.Id); n["dim_loi"] += 1; break          # dim khong khop hinh hoc -> bo
                    rects.append(box); segs.append(((A.X, A.Y), (B.X, B.Y), 0.0))
                    n["dim"] += 1; done = True; placed_one = True
                    break
                if not done and len(gcols) >= 2: n["skip"] += 1
            if len(gcols) == 1 and not placed_one: n["skip"] += 1

        def place(elem, ttype, cands):
            cands = [p for p in cands if in_crop_pt(p.X, p.Y)]
            if not cands:
                n["ngoai_crop"] += 1; return None
            tg = DB.IndependentTag.Create(doc, ttype.Id, v.Id, DB.Reference(elem), False, DB.TagOrientation.Horizontal, cands[0])
            doc.Regenerate()
            b = box_of(tg, v); h = tg.TagHeadPosition
            if b is None:
                doc.Delete(tg.Id); n["skip"] += 1; return None
            rel = (b[0] - h.X, b[1] - h.Y, b[2] - h.X, b[3] - h.Y)
            for p in cands:
                r = (p.X + rel[0], p.Y + rel[1], p.X + rel[2], p.Y + rel[3])
                if not blocked(r):
                    tg.TagHeadPosition = DB.XYZ(p.X, p.Y, h.Z)
                    rects.append(r); n["tag"] += 1
                    return tg
            doc.Delete(tg.Id); n["skip"] += 1
            return None

        # ================= 2) tag mong: trong mat tren, uu tien sat goc =================
        for f in fnds:
            cands = []
            for face in ffaces[f.Id.IntegerValue]:
                bb = face.GetBoundingBox()
                fr = [(0.85, 0.12), (0.85, 0.88), (0.15, 0.12), (0.15, 0.88), (0.75, 0.2), (0.75, 0.8), (0.25, 0.2), (0.25, 0.8),
                      (0.5, 0.15), (0.5, 0.85), (0.15, 0.5), (0.85, 0.5), (0.65, 0.35), (0.35, 0.65), (0.65, 0.65), (0.35, 0.35), (0.5, 0.5)]
                if isinstance(f, DB.Floor):          # mong bang: doc theo dai
                    fr = [(a / 20.0, b / 10.0) for a in range(1, 20) for b in (5, 3, 7)]
                for fx, fy in fr:
                    uv = DB.UV(bb.Min.U + (bb.Max.U - bb.Min.U) * fx, bb.Min.V + (bb.Max.V - bb.Min.V) * fy)
                    if face.IsInside(uv):
                        p = face.Evaluate(uv); cands.append(DB.XYZ(p.X, p.Y, z))
            if cands: place(f, FT_, cands)
            else: n["skip"] += 1
        # ================= 3) tag tuong =================
        for w in sorted(walls, key=lambda x: -x.Location.Curve.Length):
            c = w.Location.Curve; cands = []
            for tt in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9):
                p = c.Evaluate(tt, True); d = c.ComputeDerivatives(tt, True).BasisX.Normalize(); nn = DB.XYZ(-d.Y, d.X, 0)
                for off in (350, 500, 700, 1000, 1400):
                    for s in (1, -1): cands.append(DB.XYZ(p.X, p.Y, z) + nn * (s * off / FT))
            place(w, WT, cands)
        # ================= 4) tag cot =================
        for c in cols:
            p = c.Location.Point; cands = []
            for r in (550, 750, 1000, 1300, 1600):
                for ang in (0, 180, 90, 270, 45, 135, 315, 225):
                    a = math.radians(ang); cands.append(DB.XYZ(p.X + math.cos(a) * r / FT, p.Y + math.sin(a) * r / FT, z))
            place(c, CT, cands)
        report.append((vname, "mong", len(fnds), "tuong", len(walls), "cot", len(cols), "nguon chu", nstroke, n))
    t.Commit()
    for r in report: print(r)
except Exception as e:
    import traceback
    t.RollBack(); print("ROLLED BACK: " + str(e)); traceback.print_exc()
