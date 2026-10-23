# -*- coding: utf-8 -*-
"""
Kiem thu footing_wall_extractor bang du lieu hinh hoc gia lap (mm), tai hien cac tinh huong gap tren S201:
mong mat 1 canh / net dut, dai tuong "ma" tu net dut, tuong bi noi qua tay, nhan SF o goc.
"""
import ast
import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, ".agents", "skills", "pdf-to-bim", "scripts"))
import footing_wall_extractor as fx  # noqa: E402

SCHED = {"PF3": {"b_mm": 4300, "h_mm": 4300, "d_mm": 750}, "PF2": {"b_mm": 4800, "h_mm": 4300, "d_mm": 800},
         "SF1": {"b_mm": 2500, "h_mm": 500, "d_mm": None}}


def dashed(x0, y0, x1, y1, dash=200.0, gap=100.0):
    """Net dut ngang/doc thanh nhieu doan roi."""
    out, L = [], abs(x1 - x0) + abs(y1 - y0)
    t = 0.0
    while t < L:
        e = min(t + dash, L)
        if y0 == y1:
            out.append((x0 + t, y0, x0 + e, y1))
        else:
            out.append((x0, y0 + t, x1, y0 + e))
        t = e + gap
    return out


def rect_edges(cx, cy, w, h, skip=(), dashed_edges=()):
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    edges = {"bottom": (x0, y0, x1, y0), "top": (x0, y1, x1, y1), "left": (x0, y0, x0, y1), "right": (x1, y0, x1, y1)}
    segs = []
    for k, e in edges.items():
        if k in skip:
            continue
        segs += dashed(*e) if k in dashed_edges else [e]
    return segs


def test_bridge_counts_dashed_lines():
    idx = fx.SegIndex(dashed(0, 0, 4000, 0))
    assert idx.h_cov(0, 0, 4000) < 0.75
    assert idx.h_cov(0, 0, 4000, bridge=150) > 0.97


def test_pad_on_column_with_missing_and_dashed_edges():
    # Mong PF3 tam tai cot (10000, 10000): canh tren khong ve (nhap vao mong ben canh), canh phai net dut
    segs = rect_edges(10000, 10000, 4300, 4300, skip=("top",), dashed_edges=("right",))
    idx = fx.SegIndex(segs)
    cols = [{"center": {"x": 10000, "y": 10000}, "mark": "CC4A"},
            {"center": {"x": 30000, "y": 10000}, "mark": "CC3"}]  # cot khong co mong
    labels = [{"mark": "PF3", "x": 11500, "y": 9000}]
    pads = fx.extract_pad_footings_v2(idx, cols, labels, SCHED)
    assert len(pads) == 1, pads
    assert pads[0]["mark"] == "PF3" and pads[0]["center"] == {"x": 10000, "y": 10000}, pads


def test_label_only_explained_by_same_mark():
    # Nhan PF2 nam trong mong PF3 -> van phai di tim mong PF2 rieng (tam cot thu 2)
    segs = rect_edges(10000, 10000, 4300, 4300) + rect_edges(16000, 10000, 4300, 4800)
    idx = fx.SegIndex(segs)
    cols = [{"center": {"x": 10000, "y": 10000}, "mark": "C1"}, {"center": {"x": 16000, "y": 10000}, "mark": "C2"}]
    labels = [{"mark": "PF3", "x": 9000, "y": 9000}, {"mark": "PF2", "x": 15000, "y": 9000}]
    pads = fx.extract_pad_footings_v2(idx, cols, labels, SCHED)
    assert sorted(p["mark"] for p in pads) == ["PF2", "PF3"], pads


def test_no_tag_no_component():
    """Nguyen tac: cho nao co tag moi co cau kien."""
    # Cot A: net bao mong PF3 day du nhung KHONG co nhan -> khong dung
    # Cot B, C: 2 mong PF3 du net, chi CO 1 nhan (gan B) -> chi dung 1 mong (tai B)
    segs = rect_edges(10000, 10000, 4300, 4300) + rect_edges(30000, 10000, 4300, 4300) + \
        rect_edges(36000, 10000, 4300, 4300)
    idx = fx.SegIndex(segs)
    cols = [{"center": {"x": 10000, "y": 10000}, "mark": "A"}, {"center": {"x": 30000, "y": 10000}, "mark": "B"},
            {"center": {"x": 36000, "y": 10000}, "mark": "C"}]
    labels = [{"mark": "PF3", "x": 31000, "y": 9000}]
    pads = fx.extract_pad_footings_v2(idx, cols, labels, SCHED)
    assert [p["center"]["x"] for p in pads] == [30000], pads
    assert pads[0]["label_mm"] == {"x": 31000, "y": 9000}, pads


def _wall_case():
    segs, hatch = [], []
    # Tuong that: 2 mat lien (y=99900 / 100100), hatch day dac doc theo chieu dai 0..20000
    segs += [(0, 99900, 20000, 99900), (0, 100100, 20000, 100100)]
    hatch += [(x, 100000) for x in range(0, 20000, 60)]
    # Net dut (bien mong duoi san) cach mat duoi 200 mm -> cap net "ma" 99700/99900
    segs += dashed(0, 99700, 20000, 99700, dash=400, gap=300)
    # Tuong ngan o xa 30000..31500, cung tim; giua 2 tuong co 1 net dai lam "cau noi"
    segs += [(30000, 99900, 31500, 99900), (30000, 100100, 31500, 100100), (20000, 99900, 30000, 99900),
             (20000, 100100, 30000, 100100)]
    hatch += [(x, 100000) for x in range(30000, 31500, 60)]
    labels = [{"mark": "RW1", "x": 5000, "y": 100600}, {"mark": "W1", "x": 30700, "y": 100600}]
    return segs, labels, fx._PointGrid(hatch)


def test_walls_drop_ghost_band_and_split_overmerged():
    segs, labels, hatch = _wall_case()
    walls = fx.extract_walls_v2(segs, labels, hatch)
    got = sorted((w["mark"], round(w["start_mm"]["x"], -2), round(w["end_mm"]["x"], -2), w["start_mm"]["y"]) for w in walls)
    # Dung 2 tuong, tim y=100000; khong co dai "ma" y=99800; khong noi 0..31500 thanh 1 tuong
    assert len(walls) == 2, got
    assert all(abs(g[3] - 100000) < 1 for g in got), got
    assert got[0][1] == 0 and got[0][2] == 20000 and got[1][1] == 30000 and got[1][2] == 31500, got


def test_strip_label_owned_by_nearest_band():
    # Tuong RW1 ngang (bac) va RW2 doc (tay) gap nhau o goc; SF1 chay duoi RW1 (tam tai tim tuong).
    walls = [{"mark": "RW1", "start_mm": {"x": 0, "y": 100000}, "end_mm": {"x": 30000, "y": 100000}},
             {"mark": "RW2", "start_mm": {"x": 0, "y": 80000}, "end_mm": {"x": 0, "y": 100000}}]
    segs = [(0, 98750, 30000, 98750), (0, 101250, 30000, 101250)]
    # Canh mong don thang hang doc theo tuong tay tao "cap net cach 2500" gia
    for y0 in range(80000, 100000, 5000):
        segs += [(1150, y0, 1150, y0 + 4300), (3650, y0, 3650, y0 + 4300)]
    idx = fx.SegIndex(segs)
    labels = [{"mark": "SF1", "x": 2500, "y": 99300}]  # nhan o goc, gan dai bac nhat
    strips = fx.extract_strips_along_walls(idx, walls, labels, SCHED)
    assert [s["wall_mark"] for s in strips] == ["RW1"], strips
    assert abs(strips[0]["start_mm"]["y"] - 100000) < 1, strips


def test_footing_tool_logic_not_swallowed():
    from test_structural_pipeline import FakeMCP
    from tools.structural_tools import register_structural_tools
    sent = {}

    async def cap(endpoint, data, ctx=None, **kw):
        sent["code"] = data["code"]
        return {"status": "success", "output": "{}"}

    m = FakeMCP()
    register_structural_tools(m, None, cap)
    asyncio.run(m.tools["batch_create_footings_and_walls"](level_name="L1", pad_footings=[], dry_run=True))
    tree = ast.parse(sent["code"])
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "attach_failure_swallower")
    assert "Transaction(" not in ast.unparse(fn) and len(fn.body) == 4


def test_union_strips_no_overlap_no_corner_gap():
    """2 dai SF1 chu L (ngang + doc) chong nhau o goc -> 1 tam, khong chong, phu kin goc ngoai."""
    from shapely.geometry import Polygon, box
    strips = [{"mark": "SF1", "width_mm": 2500, "thickness_mm": 500, "length_mm": 10000,
               "start_mm": {"x": 0, "y": 0}, "end_mm": {"x": 10000, "y": 0}},
              {"mark": "SF1", "width_mm": 2500, "thickness_mm": 500, "length_mm": 8000,
               "start_mm": {"x": 0, "y": 0}, "end_mm": {"x": 0, "y": 8000}}]
    u = fx.union_strip_footings(strips)
    assert len(u) == 1 and u[0]["source_strips"] == 2, u
    poly = Polygon([(q["x"], q["y"]) for q in u[0]["outer_loop_mm"]])
    expect = box(-1250, -1250, 10000, 1250).union(box(-1250, -1250, 1250, 8000))
    assert abs(poly.area - expect.area) < 1 and poly.symmetric_difference(expect).area < 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
