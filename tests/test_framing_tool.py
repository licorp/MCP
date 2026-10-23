# -*- coding: utf-8 -*-
"""
Kiem thu batch_create_structural_framing_and_columns KHONG can Revit:
  - Code gui sang Revit khong bi "nuot" vao ham attach_failure_swallower (loi cu).
  - Preflight chan du lieu sai ti le.
  - Chay that doan code IronPython tren mot Revit API gia lap toi gian.
"""
import ast
import math
import asyncio
import json
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from test_structural_pipeline import FakeMCP  # noqa: E402
from tools.structural_tools import (  # noqa: E402
    register_structural_tools, preflight_structural_payload,
    FRAMING_CODE_TEMPLATE, FAILURE_SWALLOWER_CODE)


# ----------------------------------------------------------------------------- Revit API gia lap
class _NameEnum(type):
    def __getattr__(cls, name):
        return name


class BuiltInParameter(metaclass=_NameEnum):
    pass


class BuiltInCategory(metaclass=_NameEnum):
    pass


class StructuralType(metaclass=_NameEnum):
    pass


class FailureSeverity(metaclass=_NameEnum):
    pass


class FailureProcessingResult(metaclass=_NameEnum):
    pass


class IFailuresPreprocessor(object):
    pass


class ElementId(object):
    def __init__(self, v):
        self.Value = int(v)

    def __eq__(self, o):
        return isinstance(o, ElementId) and o.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z

    def __add__(self, o):
        return XYZ(self.X + o.X, self.Y + o.Y, self.Z + o.Z)


class Line(object):
    def __init__(self, a, b):
        self.a, self.b = a, b

    @staticmethod
    def CreateBound(a, b):
        return Line(a, b)


class Param(object):
    IsReadOnly = False

    def __init__(self):
        self.v = None

    def Set(self, v):
        self.v = v

    def AsString(self):
        return self.v

    def AsElementId(self):
        return self.v

    def AsDouble(self):
        return self.v


class Element(object):
    _next = [100]

    def __init__(self, doc, category=None):
        Element._next[0] += 1
        self.Id = ElementId(Element._next[0])
        self.Category = category
        self._params = {}
        self.doc = doc
        doc.elements.append(self)

    def get_Parameter(self, bip):
        return self._params.setdefault(bip, Param())


class Level(Element):
    def __init__(self, doc, name, elev_ft):
        Element.__init__(self, doc)
        self.Name, self.Elevation = name, elev_ft


class FamilySymbol(Element):
    def __init__(self, doc, category, family, name, params=("b", "h")):
        Element.__init__(self, doc, category)
        self.FamilyName, self.Name, self.IsActive = family, name, False
        self._params_names = params
        self._lp = dict((n, Param()) for n in params)

    def LookupParameter(self, n):
        return self._lp.get(n)

    def Activate(self):
        self.IsActive = True

    def Duplicate(self, name):
        return FamilySymbol(self.doc, self.Category, self.FamilyName, name, self._params_names)


class Instance(Element):
    is_instance = True

    def __init__(self, doc, sym, loc, level):
        Element.__init__(self, doc, sym.Category)
        self.Symbol, self.Location, self.Level = sym, loc, level


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.items = list(doc.elements)

    def OfCategory(self, c):
        self.items = [e for e in self.items if e.Category == c]
        return self

    def OfClass(self, cls):
        self.items = [e for e in self.items if isinstance(e, cls)]
        return self

    def WhereElementIsNotElementType(self):
        self.items = [e for e in self.items if getattr(e, "is_instance", False)]
        return self

    def __iter__(self):
        return iter(self.items)


class _Opts(object):
    def SetFailuresPreprocessor(self, p):
        pass

    def SetClearAfterRollback(self, v):
        pass


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.state = doc, "new"

    def GetFailureHandlingOptions(self):
        return _Opts()

    def SetFailureHandlingOptions(self, o):
        pass

    def Start(self):
        self.state = "started"
        self.doc.tx_snapshot = list(self.doc.elements)

    def Commit(self):
        self.state = "ended"

    def RollBack(self):
        self.doc.elements = self.doc.tx_snapshot
        self.state = "ended"

    def HasStarted(self):
        return self.state != "new"

    def HasEnded(self):
        return self.state == "ended"


class JoinGeometryUtils(object):
    @staticmethod
    def AreElementsJoined(doc, a, b):
        return False


class ElementTransformUtils(object):
    rotations = []

    @staticmethod
    def RotateElement(doc, i, axis, ang):
        ElementTransformUtils.rotations.append((i.Value, ang))


class _Create(object):
    def __init__(self, doc):
        self.doc = doc

    def NewFamilyInstance(self, loc, sym, level, stype):
        return Instance(self.doc, sym, loc, level)


class _View(object):
    GenLevel = None


class Doc(object):
    def __init__(self):
        self.elements = []
        self.Create = _Create(self)
        self.ActiveView = _View()

    def GetElement(self, i):
        return next((e for e in self.elements if e.Id == i), None)

    def Delete(self, ids):
        ids = set(i.Value for i in ids)
        self.elements = [e for e in self.elements if e.Id.Value not in ids]


class _GenericList(object):
    def __getitem__(self, t):
        return list


def install_fake_revit():
    db = types.ModuleType("Autodesk.Revit.DB")
    for obj in (BuiltInParameter, BuiltInCategory, FailureSeverity, FailureProcessingResult,
                IFailuresPreprocessor, ElementId, XYZ, Line, Element, Level, FamilySymbol,
                FilteredElementCollector, Transaction, JoinGeometryUtils, ElementTransformUtils):
        setattr(db, obj.__name__, obj)
    st = types.ModuleType("Autodesk.Revit.DB.Structure")
    st.StructuralType = StructuralType
    gen = types.ModuleType("System.Collections.Generic")
    gen.List = _GenericList()
    for name, mod in (("Autodesk", types.ModuleType("Autodesk")), ("Autodesk.Revit", types.ModuleType("Autodesk.Revit")),
                      ("Autodesk.Revit.DB", db), ("Autodesk.Revit.DB.Structure", st),
                      ("System", types.ModuleType("System")), ("System.Collections", types.ModuleType("System.Collections")),
                      ("System.Collections.Generic", gen)):
        sys.modules[name] = mod


def make_doc(with_concrete=True):
    doc = Doc()
    l1 = Level(doc, "L1", 0.0)
    Level(doc, "L2", 3500 / 304.8)
    doc.ActiveView.GenLevel = l1
    cat_c, cat_b = BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_StructuralFraming
    FamilySymbol(doc, cat_c, "W Shapes-Column", "W10x49")      # thep: phai bi loai
    FamilySymbol(doc, cat_b, "W Shapes", "W12x26")
    FamilySymbol(doc, cat_b, "M_Square Bars", "25")             # thep dac ten co 'square': phai bi loai
    if with_concrete:
        FamilySymbol(doc, cat_c, "M_Concrete-Rectangular-Column", "600x600")
        FamilySymbol(doc, cat_b, "M_Concrete-Rectangular Beam", "400x800")
    return doc


def run_in_fake_revit(doc, params):
    code = (FRAMING_CODE_TEMPLATE.replace("__PARAMS__", repr(json.dumps(params)))
            .replace("__SWALLOWER__", FAILURE_SWALLOWER_CODE))
    out = []

    class _UI(object):
        Document = doc

    class _Revit(object):
        ActiveUIDocument = _UI()

    exec(compile(code, "framing", "exec"), {"__revit__": _Revit(), "print": out.append, "__name__": "__main__"})
    return json.loads(out[-1])


COLS = [{"center": {"x": 0, "y": 0}, "b_mm": 600, "h_mm": 600, "mark": "C1"},
        {"center": {"x": 6000, "y": 0}, "b_mm": 600, "h_mm": 600, "mark": "C1", "rotation_deg": 90},
        {"center": {"x": 6010, "y": 5}, "b_mm": 600, "h_mm": 600, "mark": "C1-dup"}]
BEAMS = [{"start_mm": {"x": 0, "y": 0}, "end_mm": {"x": 6000, "y": 0}, "b_mm": 300, "h_mm": 600,
          "z_offset_mm": -50, "mark": "B1"},
         {"start_mm": {"x": 0, "y": 0}, "end_mm": {"x": 200, "y": 0}, "b_mm": 300, "h_mm": 600, "mark": "short"}]


def base_params(cols, beams, **kw):
    p = {"level_name": "L1", "top_level_name": "", "source_tag": "S204-p22", "dry_run": False,
         "replace_existing": False, "base_col_family": "", "base_beam_family": "", "base_round_col_family": "",
         "columns": cols, "beams": beams}
    p.update(kw)
    return p


# ----------------------------------------------------------------------------- tests
def test_no_logic_swallowed_into_failure_handler():
    """Hoi quy: Transaction KHONG duoc nam trong than ham attach_failure_swallower."""
    sent = {}

    async def cap(endpoint, data, ctx=None, **kw):
        sent["code"] = data["code"]
        return {"status": "success", "output": "{}"}

    m = FakeMCP()
    register_structural_tools(m, None, cap)
    calls = {
        "batch_create_structural_framing_and_columns": dict(level_name="L1", columns=COLS, beams=BEAMS),
        "batch_create_structural_slabs": dict(level_name="L1", slabs=[]),
        "batch_create_structural_walls_and_foundations": dict(level_name="L1", shear_walls=[], pile_caps=[]),
        "modify_or_delete_elements": dict(delete_ids=[1]),
        "finalize_and_join_structure": dict(level_name="L1"),
    }
    for name, kw in calls.items():
        sent.clear()
        asyncio.run(m.tools[name](**kw))
        tree = ast.parse(sent["code"])
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "attach_failure_swallower")
        assert "Transaction(" not in ast.unparse(fn), name
        assert len(fn.body) == 4, (name, len(fn.body))


def test_preflight():
    cols, beams, pre = preflight_structural_payload(COLS, BEAMS)
    assert len(cols) == 2 and len(beams) == 1, pre
    assert pre["unit_sanity"] == "ok", pre
    # Sai ti le x0.1 -> tiet dien 60x60 mm -> phai 'check'
    tiny = [dict(c, b_mm=60, h_mm=60) for c in COLS[:2]]
    _, _, pre2 = preflight_structural_payload(tiny, [])
    assert pre2["unit_sanity"] == "check", pre2


def test_tool_blocks_bad_scale_and_replace_without_tag():
    called = []

    async def cap(endpoint, data, ctx=None, **kw):
        called.append(1)
        return {"status": "success", "output": "{}"}

    m = FakeMCP()
    register_structural_tools(m, None, cap)
    tool = m.tools["batch_create_structural_framing_and_columns"]
    tiny = [dict(c, b_mm=60, h_mm=60) for c in COLS[:2]]
    res = asyncio.run(tool(level_name="L1", columns=tiny, beams=[]))
    assert "Preflight" in res and not called, res
    res = asyncio.run(tool(level_name="L1", columns=COLS, beams=[], replace_existing=True))
    assert res.startswith("Error") and not called, res


def test_fake_revit_dry_run_apply_rerun():
    install_fake_revit()
    doc = make_doc()
    cols, beams, _ = preflight_structural_payload(COLS, BEAMS)
    n0 = len(doc.elements)

    dry = run_in_fake_revit(doc, base_params(cols, beams, dry_run=True))
    assert dry["status"] == "dry_run", dry
    assert dry["column_family"] == "M_Concrete-Rectangular-Column", dry
    assert dry["beam_family"] == "M_Concrete-Rectangular Beam", dry
    assert dry["top_level"] == "L2", dry
    # co ma cot -> chi dung loai dung ma ("C1 - 600x600"), khong lay loai chung "600x600" (mat ma trong thong ke)
    assert sorted(dry["types_to_create"]) == ["M_Concrete-Rectangular Beam : B1 - 300x600",
                                              "M_Concrete-Rectangular-Column : C1 - 600x600"], dry
    assert dry["types_existing"] == [], dry
    assert len(doc.elements) == n0, "dry_run khong duoc sua model"

    res = run_in_fake_revit(doc, base_params(cols, beams))
    assert res["status"] == "success", res
    assert res["verify"]["columns_with_top_level"] == 2, res
    assert res["verify"]["tagged_in_model"] == 3, res
    beam = doc.GetElement(ElementId(res["beam_ids"][0]))
    assert beam.get_Parameter("Y_JUSTIFICATION").v == 1
    assert beam.get_Parameter("Z_JUSTIFICATION").v == 0
    assert abs(beam.get_Parameter("Z_OFFSET_VALUE").v - (-50 / 304.8)) < 1e-9
    assert beam.get_Parameter("ALL_MODEL_INSTANCE_COMMENTS").v == "PDF2BIM|S204-p22|BEAM|B1"
    assert len(ElementTransformUtils.rotations) == 1

    again = run_in_fake_revit(doc, base_params(cols, beams))
    assert again["status"] == "error" and "replace_existing" in again["message"], again

    rep = run_in_fake_revit(doc, base_params(cols, beams, replace_existing=True))
    assert rep["status"] == "success" and rep["deleted_existing"] == 3, rep
    assert rep["verify"]["tagged_in_model"] == 3, rep


def test_fake_revit_real_project_conventions():
    """Tinh huong model that 'du an thu 2': Level nhieu toa nha, loai '<ma> - bxh', 2 Family be tong."""
    install_fake_revit()
    doc = Doc()
    gf = Level(doc, "BUILDING A-GROUND FLOOR", 1200 / 304.8)
    Level(doc, "BUILDING B-GROUND FLOOR", 1200 / 304.8)
    Level(doc, "L2", 3600 / 304.8)
    Level(doc, "BUILDING A-LEVEL 01", 4300 / 304.8)
    doc.ActiveView.GenLevel = gf
    cat = BuiltInCategory.OST_StructuralColumns
    FamilySymbol(doc, cat, "M_Concrete-Rectangular-Column", "450x450")
    hp = FamilySymbol(doc, cat, "HPCE - Concrete-Rectangular-Column", "CC3 - 800x300")
    hp._lp["b"].Set(800 / 304.8)
    hp._lp["h"].Set(300 / 304.8)
    Instance(doc, hp, None, gf)  # cot da dat -> quy uoc du an

    cols = [{"center": {"x": 0, "y": 0}, "b_mm": 300, "h_mm": 800, "mark": "CC3"},
            {"center": {"x": 5000, "y": 0}, "b_mm": 300, "h_mm": 800, "mark": "CC4A"}]
    dry = run_in_fake_revit(doc, base_params(cols, [], level_name="BUILDING A-GROUND FLOOR", dry_run=True))
    assert dry["top_level"] == "BUILDING A-LEVEL 01", dry
    assert dry["column_family"] == "HPCE - Concrete-Rectangular-Column", dry
    assert dry["types_existing"] == ["HPCE - Concrete-Rectangular-Column : CC3 - 800x300"], dry
    # quy uoc du an: canh lon truoc -> tao "CC4A - 800x300" va xoay cot 90 do
    assert dry["types_to_create"] == ["HPCE - Concrete-Rectangular-Column : CC4A - 800x300"], dry


def test_fake_revit_round_columns_and_rotation_reuse():
    """Cot tron -> Family tron, loai '<ma> - <d>DIA'; cot 300x800 dung lai loai '800x300' + xoay 90 do."""
    install_fake_revit()
    ElementTransformUtils.rotations[:] = []
    doc = Doc()
    gf = Level(doc, "BUILDING A-GROUND FLOOR", 1200 / 304.8)
    Level(doc, "BUILDING A-LEVEL 01", 4300 / 304.8)
    doc.ActiveView.GenLevel = gf
    cat = BuiltInCategory.OST_StructuralColumns
    rect = FamilySymbol(doc, cat, "HPCE - Concrete-Rectangular-Column", "CC4A - 800x300")
    rect._lp["b"].Set(800 / 304.8)
    rect._lp["h"].Set(300 / 304.8)
    rnd = FamilySymbol(doc, cat, "HPCE - Concrete-Round-Column", "CC5 - 300DIA", params=("Diameter",))
    rnd._lp["Diameter"].Set(300 / 304.8)

    cols = [{"center": {"x": 0, "y": 0}, "b_mm": 300, "h_mm": 800, "mark": "CC4A", "shape": "rect"},
            {"center": {"x": 5000, "y": 0}, "b_mm": 800, "h_mm": 300, "mark": "CC4A", "shape": "rect"},
            {"center": {"x": 9000, "y": 0}, "b_mm": 300, "h_mm": 300, "diameter_mm": 300, "mark": "CC5", "shape": "round"},
            {"center": {"x": 12000, "y": 0}, "b_mm": 400, "h_mm": 400, "diameter_mm": 400, "mark": "CC1A", "shape": "round"}]
    dry = run_in_fake_revit(doc, base_params(cols, [], level_name="BUILDING A-GROUND FLOOR", dry_run=True))
    assert dry["column_family"] == "HPCE - Concrete-Rectangular-Column", dry
    assert dry["round_column_family"] == "HPCE - Concrete-Round-Column", dry
    assert dry["columns_rotated_90_to_reuse_type"] == 1, dry
    assert dry["types_existing"] == ["HPCE - Concrete-Rectangular-Column : CC4A - 800x300",
                                     "HPCE - Concrete-Round-Column : CC5 - 300DIA"], dry
    assert dry["types_to_create"] == ["HPCE - Concrete-Round-Column : CC1A - 400DIA"], dry

    res = run_in_fake_revit(doc, base_params(cols, [], level_name="BUILDING A-GROUND FLOOR"))
    assert res["status"] == "success", res
    assert len(ElementTransformUtils.rotations) == 1 and abs(ElementTransformUtils.rotations[0][1] - math.pi / 2) < 1e-9
    new_round = next(e for e in doc.elements if isinstance(e, FamilySymbol) and e.Name == "CC1A - 400DIA")
    assert abs(new_round._lp["Diameter"].v - 400 / 304.8) < 1e-9


def test_fake_revit_refuses_steel_only():
    install_fake_revit()
    doc = make_doc(with_concrete=False)
    res = run_in_fake_revit(doc, base_params(COLS[:1], []))
    assert res["status"] == "error" and "be tong" in res["message"], res


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
