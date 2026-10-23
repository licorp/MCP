# -*- coding: utf-8 -*-
"""Kiem thu kiem tra TRUNG LAP: module thuan + tool dung chan ghi khi se trung (Revit gia lap)."""
import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, ".agents", "skills", "pdf-to-bim", "scripts"))
import duplicate_check as dc  # noqa: E402

PAD_NEW = {"id": 2, "cat": "Structural Foundations", "type": "PF3", "tag": "PDF2BIM|S201-p19|PAD|PF3",
           "bb": [0, 0, 4300, 4300, 300, 1050]}
PAD_OLD = {"id": 1, "cat": "Structural Foundations", "type": "PF3", "tag": "S201 - Zone A",
           "bb": [100, 0, 4400, 4300, 300, 1050]}            # lech 100 mm -> van la TRUNG
STRIP = {"id": 3, "cat": "Structural Foundations", "type": "SF1", "tag": "",
         "bb": [-5000, 2000, 15000, 4500, 550, 1050]}         # mong bang cat qua mong don -> CHONG LAN
COL_GF = {"id": 4, "cat": "Structural Columns", "type": "CC3", "tag": "", "bb": [0, 0, 300, 800, 1200, 4300]}
COL_L1 = {"id": 5, "cat": "Structural Columns", "type": "CC3", "tag": "", "bb": [0, 0, 300, 800, 4300, 7500]}


def test_duplicate_vs_overlap_vs_stacked():
    res = dc.find_duplicates([PAD_NEW, PAD_OLD, STRIP, COL_GF, COL_L1])
    assert [(d["a"]["id"], d["b"]["id"]) for d in res["duplicates"]] == [(2, 1)] or \
        [(d["b"]["id"], d["a"]["id"]) for d in res["duplicates"]] == [(2, 1)], res
    assert any({o["a"]["id"], o["b"]["id"]} == {3, 2} for o in res["overlaps"]), res
    # cot tang tren dung tren cot tang duoi: KHONG trung
    assert not any({d["a"]["id"], d["b"]["id"]} == {4, 5} for d in res["duplicates"]), res


def test_planned_vs_existing_ignores_replaced_tag():
    planned = [{"kind": "PAD", "index": 0, "mark": "PF3",
                "bb": dc.planned_bbox("PAD", {"center": {"x": 2150, "y": 2150}, "x_mm": 4300, "y_mm": 4300,
                                              "thickness_mm": 750}, 1200, 4300)}]
    hits = dc.planned_vs_existing(planned, [PAD_OLD, PAD_NEW])
    assert sorted(h["existing_id"] for h in hits) == [1, 2], hits
    hits = dc.planned_vs_existing(planned, [PAD_OLD, PAD_NEW], ignore_tag_prefix="PDF2BIM|S201-p19|")
    assert [h["existing_id"] for h in hits] == [1], hits


def test_build_tool_refuses_when_it_would_duplicate():
    from test_structural_pipeline import FakeMCP
    from tools.structural_tools import register_structural_tools
    calls = []

    async def fake_post(endpoint, data, ctx=None, **kw):
        calls.append(data["description"])
        if "duplicate" in data["description"]:
            out = {"elements": [PAD_OLD], "levels": [{"name": "GF", "elev": 1200.0}, {"name": "L01", "elev": 4300.0}],
                   "active_level": "GF"}
            return {"status": "success", "output": json.dumps(out)}
        return {"status": "success", "output": json.dumps({"status": "success"})}

    m = FakeMCP()
    register_structural_tools(m, None, fake_post)
    pad = {"mark": "PF3", "center": {"x": 2150, "y": 2150}, "x_mm": 4300, "y_mm": 4300, "thickness_mm": 750}
    res = asyncio.run(m.tools["batch_create_footings_and_walls"](level_name="GF", pad_footings=[pad], source_tag="T"))
    # Bi chan: bao TRUNG va KHONG gui lenh dung (khong co cuoc goi 'PDF2BIM footings/walls ...')
    assert "TRUNG" in res and all("footings/walls" not in c for c in calls), (res, calls)
    # dry_run: van chay (chi doc) va bao truoc
    res = asyncio.run(m.tools["batch_create_footings_and_walls"](level_name="GF", pad_footings=[pad], source_tag="T",
                                                                 dry_run=True))
    assert "would_duplicate_existing" in res, res


def test_revit_overlap_warning_counts_as_duplicate():
    """Canh bao 'Highlighted floors overlap' cua Revit phai duoc tinh la TRUNG (lan truoc bo sot)."""
    from tools.structural_tools import post_build_duplicate_check

    async def fake_post(endpoint, data, ctx=None, **kw):
        out = {"elements": [STRIP], "levels": [], "active_level": None,
               "warnings": [{"text": "Highlighted floors overlap.", "ids": [3, 99]}]}
        return {"status": "success", "output": json.dumps(out)}

    res = asyncio.run(post_build_duplicate_check(fake_post))
    assert res["duplicates_count"] == 1 and res["duplicates"][0]["kind"] == "revit_warning", res
    assert res["status"] == "warning", res


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
