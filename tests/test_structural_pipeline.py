# -*- coding: utf-8 -*-
"""Kiem thu end-to-end parse_pdf_structural_plan voi Revit gia lap (khong can Revit that)."""
import asyncio
import json
import os
import sys
import tempfile

import fitz

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import test_grid_detector as g  # noqa: E402
from tools.structural_tools import register_structural_tools  # noqa: E402


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


async def fake_revit_post(endpoint, data, ctx=None, **kw):
    out = {"grids": g.revit_grids(), "doc_title": "test", "active_view": "GF", "active_level": "GF"}
    return {"status": "success", "output": json.dumps(out) + "\n"}


def make_structural_pdf(path):
    g.make_pdf(path)
    doc = fitz.open(path)
    page = doc[0]
    sh = page.new_shape()
    half_col = 300 / g.MM_PER_PT_1_100
    half_beam = 150 / g.MM_PER_PT_1_100
    for x in g.X_MM:
        for y in g.Y_MM:
            cx, cy = g.mm_to_pt(x, y)
            sh.draw_rect(fitz.Rect(cx - half_col, cy - half_col, cx + half_col, cy + half_col))
    # Dam ngang (theo truc so) va dam doc (theo truc chu), net doi cach nhau 300 mm
    for y in g.Y_MM:
        for x0, x1 in zip(g.X_MM[:-1], g.X_MM[1:]):
            a, b = g.mm_to_pt(x0 + 300, y), g.mm_to_pt(x1 - 300, y)
            sh.draw_line((a[0], a[1] - half_beam), (b[0], b[1] - half_beam))
            sh.draw_line((a[0], a[1] + half_beam), (b[0], b[1] + half_beam))
    for x in g.X_MM:
        for y0, y1 in zip(g.Y_MM[:-1], g.Y_MM[1:]):
            a, b = g.mm_to_pt(x, y0 + 300), g.mm_to_pt(x, y1 - 300)
            sh.draw_line((a[0] - half_beam, a[1]), (b[0] - half_beam, b[1]))
            sh.draw_line((a[0] + half_beam, a[1]), (b[0] + half_beam, b[1]))
    # Lo mo chu X 2000x2000 trong o A-B / 1-2
    p1, p2 = g.mm_to_pt(2000, 2500), g.mm_to_pt(4000, 4500)
    sh.draw_line(p1, p2)
    sh.draw_line((p1[0], p2[1]), (p2[0], p1[1]))
    sh.finish(color=(0, 0, 0), width=0.3)
    sh.commit()
    tx, ty = g.mm_to_pt(3000, 0)
    page.insert_text((tx - 20, ty - 12), "B1 300x600", fontsize=5)
    doc.saveIncr()


def test_pipeline():
    path = os.path.join(tempfile.mkdtemp(), "struct.pdf")
    make_structural_pdf(path)
    mcp = FakeMCP()
    register_structural_tools(mcp, None, fake_revit_post)
    assert "auto_calibrate_grids" in mcp.tools

    cal = asyncio.run(mcp.tools["auto_calibrate_grids"](page_number=1, pdf_path=path))
    assert "1:100" in cal and "S204" in cal, cal

    res = asyncio.run(mcp.tools["parse_pdf_structural_plan"](page_number=1, pdf_path=path))
    assert not res.startswith("Error"), res
    data = json.loads(res[res.index("{"):]) if res.lstrip().startswith("{") else None
    print(res[:1500])
    return data


if __name__ == "__main__":
    test_pipeline()