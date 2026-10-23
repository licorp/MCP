# -*- coding: utf-8 -*-
"""Kiem thu: khop toa do qua TRANG TONG, do nhieu huong truc, trung lap theo duong tim, cot xoay tren trang."""
import math
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, ".agents", "skills", "pdf-to-bim", "scripts"))
import overall_calibration as ovc  # noqa: E402
import footing_wall_extractor as fwx  # noqa: E402
import duplicate_check as dc  # noqa: E402
from column_calibration import PT_TO_MM, _orient_rect  # noqa: E402
from pdf_struct_parser import AffineTransformer, column_to_revit  # noqa: E402


def _sim(p, deg, s, t):
    r = math.radians(deg)
    return (s * (p[0] * math.cos(r) - p[1] * math.sin(r)) + t[0], s * (p[0] * math.sin(r) + p[1] * math.cos(r)) + t[1])


def test_calibrate_via_overall_chain_and_outlier():
    random.seed(1)
    # Cot that trong Revit (mm): Zone A (da dung) + Zone B
    zone_a = [(60000 + 7000 * i, 230000 + 6000 * j) for i in range(5) for j in range(4)]
    zone_b = [(110000 + 7000 * i, 240000 + 6000 * j) for i in range(4) for j in range(3)]
    mm_o, mm_p = PT_TO_MM * 150, PT_TO_MM * 100

    # Trang tong 1:150 xoay 90 do: Revit -> overall mm -> point (Y xuong)
    def to_overall_pt(q):
        x, y = _sim(q, 90.0, 1.0, (500000.0, -100000.0))
        return (x / mm_o, -y / mm_o)
    overall = [to_overall_pt(q) for q in zone_a + zone_b]

    # Trang zone B 1:100 xoay -30.7 do so voi Revit
    def to_page_pt(q):
        x, y = _sim(q, -30.7, 1.0, (-20000.0, 900000.0))
        return (x / mm_p, -y / mm_p)
    feats = [dict(zip(("x", "y"), to_page_pt(q)), mark="CC4A", kind="rect", b_mm=800, h_mm=300) for q in zone_b]
    # 1 cot nhan nham (lech 70 mm) -> phai bi loai
    bad = to_page_pt((zone_b[0][0] + 70, zone_b[0][1]))
    feats.append({"x": bad[0], "y": bad[1], "mark": "CC5", "kind": "rect", "b_mm": 246, "h_mm": 152})
    cal = ovc.calibrate_via_overall(feats, 100, overall, 150, zone_a)
    assert cal["status"] == "success", cal
    assert cal["overall_to_revit"]["rms_mm"] < 1.0
    assert [c["mark"] for c in cal["columns_not_on_overall"]] == ["CC5"]
    tr = AffineTransformer(cal["pdf_grid_pt1"], cal["pdf_grid_pt2"], cal["revit_grid_pt1_mm"], cal["revit_grid_pt2_mm"])
    for q in zone_b:
        p = tr.to_revit_mm(*to_page_pt(q))
        assert math.hypot(p["x"] - q[0], p["y"] - q[1]) < 1.0


def test_dominant_orientations_two_frames():
    segs = []
    for i in range(20):
        segs.append((0, i * 1000.0, 8000, i * 1000.0))                      # 0 do
        a = math.radians(-30.7)
        segs.append((0, 0, 6000 * math.cos(a), 6000 * math.sin(a)))       # -30.7 do
    segs += [(0, 0, 3000 * math.cos(math.radians(59.3)), 3000 * math.sin(math.radians(59.3)))] * 5
    fr = fwx.dominant_orientations(segs)
    assert len(fr) == 2
    assert any(abs(f) < 0.3 for f in fr) and any(abs(f + 30.7) < 0.3 for f in fr)


def test_local_frame_rest_override_roundtrip():
    tr = AffineTransformer((0, 0), (1000, 0), (50000, 60000), (50000 + 1000 * math.cos(math.radians(-30.7)) * 35.28,
                                                                60000 + 1000 * math.sin(math.radians(-30.7)) * 35.28))
    ltr, rest, origin = fwx.local_frame(tr, 0.0)
    assert rest == 0.0 and origin is None
    ltr, rest, origin = fwx.local_frame(tr)
    assert abs(rest + 30.7) < 0.01
    p = ltr.to_revit_mm(300, 200)
    x, y = fwx.rotate_xy((p["x"], p["y"]), origin, rest)
    q = tr.to_revit_mm(300, 200)
    assert math.hypot(x - q["x"], y - q["y"]) < 0.5


def test_collinear_wall_containment_is_duplicate_but_crossing_is_not():
    big = {"id": 1, "cat": "Walls", "tag": "PDF2BIM|S201-p19|WALL|RW1", "bb": [90645, 235486, 97529, 235686, 1200, 4300],
           "line": [90745, 235586, 97429, 235586], "width": 200}
    short = {"id": 2, "cat": "Walls", "tag": "PDF2BIM|S202-p20|WALL|RW1", "bb": [94162, 235489, 97162, 235689, 1200, 4300],
             "line": [94162, 235589, 97162, 235589], "width": 200}
    res = dc.classify_pair(short, big)
    assert res and res["kind"] == "duplicate"
    # tuong xien cat ngang (hinh bao lon) -> KHONG trung
    diag = {"id": 3, "cat": "Walls", "tag": "", "bb": [90000, 230000, 98000, 240000, 1200, 4300],
            "line": [90000, 230000, 98000, 240000], "width": 200}
    assert dc.classify_pair(diag, big) is None
    # noi dau (khong chong) -> khong trung
    tail = dict(short, id=4, line=[97429, 235586, 99000, 235586])
    assert dc.classify_pair(tail, big) is None


def test_strip_inside_strip_is_duplicate_pad_in_strip_is_overlap():
    s_big = {"id": 1, "cat": "Structural Foundations", "type": "SF1 - 2500Wx500D", "tag": "PDF2BIM|S201-p19|STRIP|SF1",
             "bb": [89495, 232986, 97429, 236836, 550, 1050]}
    s_small = {"id": 2, "cat": "Structural Foundations", "type": "SF1 - 2500Wx500D", "tag": "PDF2BIM|S202-p20|STRIP|SF1",
               "bb": [94162, 234556, 97162, 236836, 550, 1050]}
    pad = {"id": 3, "cat": "Structural Foundations", "type": "PF3 - 4300x4300x750D", "tag": "PDF2BIM|S201-p19|PAD|PF3",
           "bb": [94000, 234400, 96000, 236500, 300, 1050]}
    assert dc.classify_pair(s_small, s_big)["kind"] == "duplicate"
    assert dc.classify_pair(pad, s_big)["kind"] == "overlap"


def test_orient_rect_rotated_column_and_revit_rotation():
    mm = PT_TO_MM * 100
    b, h, a = 800.0, 300.0, -30.7         # cot 800x300 ve xoay -30.7 do tren trang (Y xuong)
    cx, cy = 500.0, 500.0
    r = math.radians(a)
    corners = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = sx * b / 2 / mm, sy * h / 2 / mm
        corners.append((cx + x * math.cos(r) - y * math.sin(r), cy + x * math.sin(r) + y * math.cos(r)))
    cell = 20.0
    buckets = {}
    for i in range(4):
        p, q = corners[i], corners[(i + 1) % 4]
        buckets.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append((p[0], p[1], q[0], q[1]))
    bw = b * abs(math.cos(r)) + h * abs(math.sin(r))
    bh = b * abs(math.sin(r)) + h * abs(math.cos(r))
    u = {"x": cx, "y": cy, "kind": "rect", "b_mm": round(bw), "h_mm": round(bh), "mark": "CC4A"}
    _orient_rect(u, buckets, cell, mm, 190, 2500)
    assert (u["b_mm"], u["h_mm"]) == (800, 300) and abs(u["angle_deg"] - 149.3) < 0.1   # mod 180
    # trang -> Revit xoay -30.7 do (co lat Y): cot ve -30.7 tren trang -> THANG TRUC trong Revit
    tr = AffineTransformer((0, 0), (1000, 0), (0, 0), (1000 * mm * math.cos(math.radians(-30.7)),
                                                       1000 * mm * math.sin(math.radians(-30.7))))
    col = column_to_revit(u, tr)
    assert not col.get("rotation_deg")
    assert sorted((col["b_mm"], col["h_mm"])) == [300, 800]


def _arc_segs(cx, cy, r, a0, a1, n):
    pts = [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
    return [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(n)]


def test_curved_wall_guided_by_cad_radius_and_tangent_join():
    cx, cy = 98810.0, 262190.0
    a0, a1 = math.radians(-90), math.radians(-30)
    segs = _arc_segs(cx, cy, 3700, a0, a1, 30) + _arc_segs(cx, cy, 3900, a0, a1, 30)
    # tuong thang RW1 noi tiep tuyen o dau cung (y = cy - 3800), dung som 380 mm
    straight = [{"mark": "RW1", "start_mm": {"x": 92060.0, "y": cy - 3800}, "end_mm": {"x": cx - 380, "y": cy - 3800},
                 "thickness_mm": 200}]
    # hatch be tong trong vanh khan
    random.seed(3)
    hp = []
    for i in range(400):
        a = a0 + (a1 - a0) * random.random()
        rr = 3720 + 160 * random.random()
        hp.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    hatch = fwx._PointGrid(hp)
    # tam CAD kien truc lech +100 mm theo Y; mot cung PDF lam moc do lech
    cad = [(cx, cy - 102, 3700.0), (cx, cy - 102, 3900.0)]
    pdf_h = [(cx, cy, 3900.0)]
    cad2, off, n = fwx.align_cad_hints(cad, pdf_h)
    assert n == 1 and abs(off[1] - 102) < 1
    ws = fwx.extract_curved_walls_guided(segs, [], hatch, pdf_h, straight_walls=straight, cad_hints=cad2)
    assert len(ws) == 1
    w = ws[0]
    assert w["mark"] == "RW1" and w["mark_from"].startswith("tangent_to")      # khong co nhan rieng -> theo tuong thang
    assert abs(w["radius_mm"] - 3800) < 1 and w["faces_mm"] == [3700, 3900]
    joins = fwx.tangent_joins(ws, straight)
    assert joins and joins[0][2] >= 300
    assert abs(straight[0]["end_mm"]["x"] - cx) < 1                            # tuong thang keo toi diem tiep tuyen
    s = w["start_mm"] if abs(w["start_mm"]["y"] - (cy - 3800)) < 5 else w["end_mm"]
    assert abs(s["x"] - cx) < 1 and abs(s["y"] - (cy - 3800)) < 1


def test_curved_wall_rejected_without_hatch_or_tag():
    cx, cy = 0.0, 0.0
    segs = _arc_segs(cx, cy, 1500, 0, math.pi / 2, 20) + _arc_segs(cx, cy, 1700, 0, math.pi / 2, 20)
    empty = fwx._PointGrid([])
    assert fwx.extract_curved_walls_guided(segs, [{"mark": "RW1", "x": 1600, "y": 300}], empty, [(0, 0, 1700)]) == []


class _FakeRect(object):
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.width, self.height = x1 - x0, y1 - y0


class _P(object):
    def __init__(self, x, y):
        self.x, self.y = x, y


def _fake_rc(grey_boxes, hatch_pts):
    import legend_reader as lr
    rc = lr.RegionClassifier.__new__(lr.RegionClassifier)
    rc.cell = 20.0
    rc.grey = [(_FakeRect(*b), [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]) for b in grey_boxes]
    rc.hatch = {}
    for x, y in hatch_pts:
        rc.hatch.setdefault((int(x // 20), int(y // 20)), []).append((x, y))
    return rc


def test_legend_meaning_and_region_classes():
    import legend_reader as lr
    assert lr._meaning("DENOTES CONCRETE WALL/COLUMN UNDER AND OVER") == "UNDER_AND_OVER"
    assert lr._meaning("DENOTES CONCRETE WALL/COLUMN OVER") == "OVER"
    assert lr._meaning("DENOTES WALL/COLUMN UNDER") == "UNDER"
    assert lr._meaning("DENOTES PRECAST UNDER AND OVER") == "PRECAST_UNDER_AND_OVER"
    assert lr._meaning("DENOTES SLAB ON GROUND") == "SOG"
    line = [(100 + i * 5, 100.0) for i in range(20)]
    dots = [(100 + i * 2.5, 100.5) for i in range(40)]
    assert _fake_rc([], dots).classify_samples(line, 3)["meaning"] == "OVER"
    assert _fake_rc([(95, 97, 205, 103)], dots).classify_samples(line, 3)["meaning"] == "UNDER_AND_OVER"
    assert _fake_rc([(95, 97, 205, 103)], []).classify_samples(line, 3)["meaning"] == "UNDER"
    assert _fake_rc([], []).classify_samples(line, 3)["meaning"] == "NONE"
