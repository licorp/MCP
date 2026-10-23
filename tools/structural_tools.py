# -*- coding: utf-8 -*-
"""
structural_tools.py - FastMCP Structural Tools for Revit
Cung cấp các công cụ MCP cho AI Agent:
  1. parse_pdf_structural_plan: Bóc tách Cột, Dầm, Vách từ PDF Vector qua PyMuPDF & AffineTransformer.
  2. batch_create_structural_framing_and_columns: Dựng Cột & Dầm hàng loạt trong Revit (tự động Duplicate b x h).
"""

import os
import sys
import json
import math
from typing import List, Dict, Any, Optional, Union
from mcp.server.fastmcp import Context, Image as MCPImage
from .utils import format_response

# Import parser if available in skills/scripts
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".agents", "skills", "pdf-to-bim", "scripts")))
try:
    from pdf_struct_parser import AffineTransformer, extract_structural_pdf, parse_schedule_tables
    from visual_qa_overlay import generate_qa_overlay_image
except ImportError:
    AffineTransformer = None
    extract_structural_pdf = None
    parse_schedule_tables = None
    generate_qa_overlay_image = None

try:
    import fitz  # PyMuPDF
    from wall_and_foundation_parser import extract_shear_walls_and_foundations
except ImportError:
    fitz = None
    extract_shear_walls_and_foundations = None

try:
    from grid_detector import detect_pdf_grids, calibrate_from_grids, get_title_block_info
except ImportError:
    detect_pdf_grids = None
    calibrate_from_grids = None
    get_title_block_info = None

try:
    from column_calibration import (calibrate_from_columns, drawing_scale_from_text,
                                    extract_pdf_column_features, revit_column_mark)
except ImportError:
    calibrate_from_columns = None

try:
    import overall_calibration as ovc
except ImportError:
    ovc = None

try:
    import legend_reader as lgd
except ImportError:
    lgd = None

try:
    import duplicate_check as dupc
except ImportError:
    dupc = None

try:
    import footing_wall_extractor as fwx
    from pdf_struct_parser import column_to_revit
except ImportError:
    fwx = None
    column_to_revit = None


# Ten file PDF mac dinh cua du an & cac thu muc se tu dong quet khi khong truyen pdf_path
DEFAULT_PDF_NAMES = ["Combined set_1.pdf"]
_EXT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def work_path(*parts: str) -> str:
    """
    File SINH RA (anh QA, cache...) luon nam trong thu muc lam viec cua extension
    (<extension>/.agents/cache, doi bang bien moi truong PDF2BIM_WORK_DIR) - KHONG ghi ra Desktop
    hay thu muc dang chay server MCP.
    """
    base = os.environ.get("PDF2BIM_WORK_DIR") or os.path.join(_EXT_ROOT, ".agents", "cache")
    path = os.path.join(base, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def find_project_pdf(pdf_path: Optional[str] = None) -> Optional[str]:
    """Tra ve pdf_path neu ton tai, nguoc lai tu tim file PDF du an trong cac thu muc quen thuoc."""
    if pdf_path and os.path.isfile(pdf_path):
        return os.path.abspath(pdf_path)
    names = [os.path.basename(pdf_path)] if pdf_path else []
    names += DEFAULT_PDF_NAMES
    home = os.path.expanduser("~")
    dirs = [os.getcwd(), _EXT_ROOT]
    for sub in ("Desktop", "Documents", "Downloads", os.path.join("OneDrive", "Desktop"),
                os.path.join("OneDrive", "Documents")):
        dirs.append(os.path.join(home, sub))
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    # Thu muc con (toi da 3 cap) cua Desktop/Documents - vd Desktop\HPEC\New folder\Combined set_1.pdf
    lower = set(n.lower() for n in names)
    for d in dirs[2:]:
        if not os.path.isdir(d):
            continue
        base_depth = d.rstrip(os.sep).count(os.sep)
        for root, subdirs, files in os.walk(d):
            if root.count(os.sep) - base_depth >= 3:
                subdirs[:] = []
            subdirs[:] = [s for s in subdirs if not s.startswith(".")]
            for f in files:
                if f.lower() in lower:
                    return os.path.join(root, f)
    return None


CALIB_QUERY_CODE = r'''
import json
from Autodesk.Revit.DB import *
P = json.loads(__PARAMS__)

def nm(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)

def pval(e, bip, kind):
    p = e.get_Parameter(bip)
    if p is None:
        return None
    return p.AsElementId() if kind == "id" else p.AsDouble()

grids = []
for g in FilteredElementCollector(doc).OfClass(Grid).ToElements():
    c = g.Curve
    if not isinstance(c, Line):
        continue
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    grids.append({"name": g.Name,
                  "start_mm": {"x": p0.X * 304.8, "y": p0.Y * 304.8},
                  "end_mm": {"x": p1.X * 304.8, "y": p1.Y * 304.8}})

av = doc.ActiveView
levels = list(FilteredElementCollector(doc).OfClass(Level))
lvl = next((l for l in levels if l.Name == P["level_name"]), None) if P["level_name"] else None
lvl = lvl or getattr(av, "GenLevel", None)

# Hinh cot (chu nhat / tron khep kin 150-2500 mm) tren file CAD link/import trong view dang mo
cad_shapes, cad_links = [], []
opt = Options()
opt.View = av

def layer_of(g):
    try:
        st = doc.GetElement(g.GraphicsStyleId)
        return st.GraphicsStyleCategory.Name if st and st.GraphicsStyleCategory else ""
    except Exception:
        return ""

def walk_cad(geo):
    for g in geo:
        if isinstance(g, GeometryInstance):
            walk_cad(g.GetInstanceGeometry())
        elif isinstance(g, PolyLine):
            pts = g.GetCoordinates()
            n = pts.Count
            if n in (4, 5) and (n == 4 or pts[0].DistanceTo(pts[n - 1]) < 0.003):
                xs = [p.X for p in pts]
                ys = [p.Y for p in pts]
                w, h = (max(xs) - min(xs)) * 304.8, (max(ys) - min(ys)) * 304.8
                if 150 <= w <= 2500 and 150 <= h <= 2500:
                    cad_shapes.append(["rect", (max(xs) + min(xs)) / 2 * 304.8, (max(ys) + min(ys)) / 2 * 304.8, w, h, layer_of(g)])
        elif isinstance(g, Arc) and not g.IsBound:
            d = g.Radius * 2 * 304.8
            if 150 <= d <= 2500:
                cad_shapes.append(["circle", g.Center.X * 304.8, g.Center.Y * 304.8, d, d, layer_of(g)])

for imp in FilteredElementCollector(doc, av.Id).OfClass(ImportInstance):
    try:
        cad_links.append(imp.Category.Name if imp.Category else "?")
        walk_cad(imp.get_Geometry(opt))
    except Exception:
        pass

# Cot di qua cao do tang dang dung (ke ca cot tu tang duoi len)
columns = []
if lvl is not None:
    z = lvl.Elevation
    for e in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType():
        loc = e.Location
        if not isinstance(loc, LocationPoint):
            continue
        bl = doc.GetElement(pval(e, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM, "id") or ElementId.InvalidElementId)
        tl = doc.GetElement(pval(e, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM, "id") or ElementId.InvalidElementId)
        if bl is None:
            continue
        zb = bl.Elevation + (pval(e, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM, "d") or 0.0)
        zt = (tl.Elevation + (pval(e, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM, "d") or 0.0)) if tl else zb + 1.0
        if zb - 0.01 <= z <= zt + 0.01:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            columns.append({"type": nm(e.Symbol), "family": e.Symbol.FamilyName,
                            "mark_param": (mk.AsString() if mk else "") or "",
                            "tag": ((cm.AsString() if cm else "") or "")[:60],
                            "x": loc.Point.X * 304.8, "y": loc.Point.Y * 304.8})

print(json.dumps({"grids": grids, "columns": columns, "cad_shapes": cad_shapes, "cad_links": cad_links,
                  "doc_title": doc.Title, "active_view": av.Name,
                  "level": lvl.Name if lvl else None,
                  "active_level": getattr(getattr(av, "GenLevel", None), "Name", None)}))
'''


async def run_revit_json(revit_post, code: str, description: str, ctx=None, timeout: float = 60.0):
    """Chay IronPython qua /execute_code/ va doc dong JSON cuoi cung duoc print ra."""
    resp = await revit_post("/execute_code/", {"code": code, "description": description}, ctx, timeout=timeout)
    if isinstance(resp, str):
        raise RuntimeError(resp)
    if resp.get("status") != "success":
        raise RuntimeError(resp.get("error") or json.dumps(resp)[:500])
    output = resp.get("output", "") or ""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            return json.loads(line)
    raise RuntimeError("Revit khong tra ve JSON: " + output[:500])


def cad_shapes_as_columns(shapes: List[List[Any]], dedupe_mm: float = 30.0) -> List[Dict[str, Any]]:
    """Hinh cot tren file CAD link -> dang 'cot Revit' ({type, x, y}) de ghep theo tiet dien."""
    out = []
    for sh in shapes:
        kind, x, y, w, h = sh[:5]
        if any(math.hypot(x - o["x"], y - o["y"]) < dedupe_mm for o in out):
            continue
        typ = "{}DIA".format(int(round(w))) if kind == "circle" else "{}x{}".format(int(round(w)), int(round(h)))
        out.append({"type": typ, "mark": "", "x": x, "y": y})
    return out


async def auto_calibrate(revit_post, pdf_path: str, page_number: int, ctx=None,
                         max_residual_mm: float = 50.0, method: str = "auto",
                         level_name: str = "", cad_tol_mm: float = 60.0,
                         overall_page: int = 0) -> Dict[str, Any]:
    """
    Khop he toa do PDF <-> Revit tu dong, tu du lieu vector (khong uoc luong bang mat):
      - 'grids'  : do luoi truc tren PDF, ghep giao diem trung ten voi Grid Revit.
      - 'cad'    : ghep cot tren PDF voi hinh cot tren file CAD link/import trong view dang mo
                   (thuong la chinh ban ve da chuyen sang DWG) - chinh xac nhat khi khong co luoi truc.
      - 'columns': ghep cot co ma tren PDF voi cot DA CO trong Revit di qua cao do tang - chi dung
                   khi khong co file link; sai theo neu cot hien co dung lech.
      - 'overall': trang zone -> TRANG TONG (S200, S203...) -> cot da dung theo ban ve ket cau; moi zone
                   chung 1 he toa do (khong lech theo link kien truc). overall_page=0 -> tu tim.
      - 'auto'   : thu lan luot 'grids' -> 'cad' -> 'overall' -> 'cad_position' -> 'columns'.
    """
    if detect_pdf_grids is None or fitz is None:
        raise RuntimeError("Thieu module grid_detector hoac PyMuPDF.")
    code = CALIB_QUERY_CODE.replace("__PARAMS__", repr(json.dumps({"level_name": level_name or ""})))
    revit_info = await run_revit_json(revit_post, code, "Query Grids & Columns", ctx, timeout=120.0)

    with fitz.open(pdf_path) as fdoc:
        page = fdoc[page_number - 1]
        title = get_title_block_info(page)
        attempts = []
        cal = None
        if method in ("auto", "grids"):
            pdf_grids = detect_pdf_grids(page)
            cal = calibrate_from_grids(pdf_grids, revit_info.get("grids", []))
            cal["method"] = "grids"
            cal["pdf_grids_detected"] = len(pdf_grids)
            cal["revit_grids_found"] = len(revit_info.get("grids", []))
            if cal.get("status") == "success" and cal["residual_max_mm"] > max_residual_mm:
                cal["status"] = "error"
                cal["message"] = (
                    "Sai so kiem tra tai giao diem truc vuot {} mm (max {} mm). Ten truc PDF va Revit "
                    "co the khong khop nhau, hoac ban ve chi la 1 Zone dung truc trung ten.".format(
                        max_residual_mm, cal["residual_max_mm"]))
            attempts.append({k: cal.get(k) for k in ("method", "status", "message", "pdf_grids_detected",
                                                     "revit_grids_found", "common_intersections")})
        scale = drawing_scale_from_text(page) or 100
        feats = None
        # 'cad': file CAD link/import trong view (thuong chinh la ban ve PDF da chuyen sang DWG) la
        # chuan vi tri -> uu tien hon cot da co trong model (co the da dung lech).
        cad_cols = cad_shapes_as_columns(revit_info.get("cad_shapes", []))
        if (cal is None or cal.get("status") != "success") and method in ("auto", "cad") \
                and calibrate_from_columns is not None and cad_cols:
            feats = extract_pdf_column_features(page, scale)
            cal = calibrate_from_columns(feats, cad_cols, scale, tol_mm=cad_tol_mm)
            cal["method"] = "cad"
            cal["cad_links"] = revit_info.get("cad_links", [])
            cal["nominal_scale"] = "1:{}".format(scale)
            if cal.get("status") == "success" and cal["residual_max_mm"] > cad_tol_mm:
                cal["status"] = "error"
            attempts.append({k: cal.get(k) for k in ("method", "status", "message", "matched_columns",
                                                     "pdf_columns_with_common_mark", "revit_columns",
                                                     "residual_rms_mm")})
        if (cal is None or cal.get("status") != "success") and method in ("auto", "overall") \
                and ovc is not None and calibrate_from_columns is not None:
            # Qua TRANG TONG (S200/S203...): trang zone -> trang tong -> cot DA DUNG theo ban ve ket cau.
            # Moi zone di qua cung 1 phep trang tong -> Revit nen khop nhau o cho noi.
            ov_no = overall_page or ovc.find_overall_page(fdoc, (title or {}).get("sheet_number", ""),
                                                          get_title_block_info)
            all_cols = revit_info.get("columns", [])
            ref = [c for c in all_cols if (c.get("tag") or "").startswith("PDF2BIM|")]
            ref = ref if len(ref) >= 4 else all_cols
            if ov_no and ov_no != page_number and len(ref) >= 4:
                ov_page = fdoc[ov_no - 1]
                ov_scale = drawing_scale_from_text(ov_page) or 150
                feats = feats if feats is not None else extract_pdf_column_features(page, scale)
                cal = ovc.calibrate_via_overall(feats, scale, ovc.rect_centres(ov_page, ov_scale), ov_scale,
                                                [(float(c["x"]), float(c["y"])) for c in ref])
                cal.update({"overall_page": ov_no, "overall_sheet": (get_title_block_info(ov_page) or {}).get(
                    "sheet_number"), "overall_scale": "1:{}".format(ov_scale), "nominal_scale": "1:{}".format(scale),
                    "reference_columns": "PDF2BIM" if ref is not all_cols else "all"})
                if cal.get("status") == "success" and cal["residual_max_mm"] > max_residual_mm:
                    cal["status"] = "error"
                    cal["message"] = "Sai so qua trang tong vuot {} mm.".format(max_residual_mm)
                attempts.append({k: cal.get(k) for k in ("method", "status", "message", "matched_columns",
                                                         "overall_page", "page_to_overall", "overall_to_revit",
                                                         "residual_rms_mm")})
        if (cal is None or cal.get("status") != "success") and method in ("auto", "cad", "cad_position") \
                and calibrate_from_columns is not None and revit_info.get("cad_shapes"):
            # File link khong phai chinh ban ve (vd ban KIEN TRUC: cot ve 1000 thay vi 800) -> ghep theo VI TRI
            # tam cot tren layer co 'COL', ti le co dinh theo ban ve, goc xoay tu do.
            col_layer = [sh for sh in revit_info["cad_shapes"] if len(sh) > 5 and "COL" in (sh[5] or "").upper()]
            # type="" -> ghep theo VI TRI (khong theo tiet dien: kien truc ve 1000x300, ket cau 800x300)
            pos_cols = [dict(c, mark="C", type="") for c in cad_shapes_as_columns(col_layer)]
            if len(pos_cols) >= 4:
                feats = feats if feats is not None else extract_pdf_column_features(page, scale)
                cal = calibrate_from_columns([dict(f, mark="C") for f in feats], pos_cols, scale,
                                             tol_mm=150.0, max_pairs=1500)
                cal["method"] = "cad_position"
                cal["cad_links"] = revit_info.get("cad_links", [])
                cal["nominal_scale"] = "1:{}".format(scale)
                if cal.get("status") == "success":
                    cal["warning"] = ("Moc la file link KIEN TRUC (layer cot), khong phai chinh ban ve ket cau: tung cot "
                                      "co the lech ~100 mm do tiet dien kien truc/ket cau khac nhau; sai so toan cuc "
                                      "nho hon. Bao nguoi dung truoc khi dung.")
                attempts.append({k: cal.get(k) for k in ("method", "status", "message", "matched_columns",
                                                         "pdf_columns_with_common_mark", "revit_columns",
                                                         "residual_rms_mm")})
        if (cal is None or cal.get("status") != "success") and method in ("auto", "columns") \
                and calibrate_from_columns is not None:
            revit_cols = [dict(c, mark=revit_column_mark(c.get("type", ""), c.get("mark_param", "")))
                          for c in revit_info.get("columns", [])]
            feats = feats if feats is not None else extract_pdf_column_features(page, scale)
            cal = calibrate_from_columns(feats, revit_cols, scale)
            cal["nominal_scale"] = "1:{}".format(scale)
            attempts.append({k: cal.get(k) for k in ("method", "status", "message", "matched_columns",
                                                     "pdf_columns_with_common_mark", "revit_columns",
                                                     "residual_rms_mm")})
            if cal.get("status") == "success":
                cal["warning"] = ("Khop theo cot DA CO trong model: neu cac cot nay dung lech so voi ban ve "
                                  "thi ket qua lech theo. Nen link file CAD/PDF cua ban ve vao view de dung "
                                  "method='cad'.")

    cal["attempts"] = attempts
    cal["title_block"] = title
    cal["revit"] = {k: revit_info.get(k) for k in ("doc_title", "active_view", "level", "active_level")}
    return cal


async def resolve_calibration(revit_post, pdf_path, page_number, pts, ctx=None, level_name: str = ""):
    """
    pts = (pdf_grid_pt1, pdf_grid_pt2, revit_grid_pt1_mm, revit_grid_pt2_mm).
    Neu da du 4 diem -> dung luon; neu thieu -> tu dong khop (luoi truc, roi den cot).
    Tra ve (pts, calibration_info) hoac raise RuntimeError.
    """
    if all(pts):
        info = {"status": "manual", "method": "manual"}
        try:
            with fitz.open(pdf_path) as fdoc:
                info["title_block"] = get_title_block_info(fdoc[page_number - 1])
        except Exception:
            pass
        return pts, info
    cal = await auto_calibrate(revit_post, pdf_path, page_number, ctx, level_name=level_name)
    if cal.get("status") != "success":
        raise RuntimeError("Tu dong khop toa do that bai: " + json.dumps(cal, ensure_ascii=False)[:1500])
    if ctx:
        await ctx.info("Khop toa do ({}) {} | ti le {} | sai so RMS {} mm".format(
            cal.get("method"), cal.get("anchors"), cal.get("drawing_scale"), cal.get("residual_rms_mm")))
    return (cal["pdf_grid_pt1"], cal["pdf_grid_pt2"], cal["revit_grid_pt1_mm"], cal["revit_grid_pt2_mm"]), cal


FAILURE_SWALLOWER_CODE = """
class MCPAutoFailureSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        fail_list = failuresAccessor.GetFailureMessages()
        for f in fail_list:
            severity = f.GetSeverity()
            if severity == FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(f)
            elif severity == FailureSeverity.Error and f.HasResolutions():
                failuresAccessor.ResolveFailure(f)
                return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue

def attach_failure_swallower(transaction):
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(MCPAutoFailureSwallower())
    options.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(options)
"""


def preflight_structural_payload(columns: List[Dict], beams: List[Dict],
                                 dedupe_mm: float = 50.0, min_beam_mm: float = 300.0):
    """
    Kiem tra truoc khi ghi (khong can Revit): loc cot trung vi tri, dam qua ngan, thong ke tiet
    dien & pham vi toa do. unit_sanity = 'check' khi >20% cau kien co tiet dien bat thuong hoac
    pham vi mat bang vo ly -> dau hieu sai ti le / khop truc.
    """
    warnings, xs, ys = [], [], []
    col_sizes, beam_sizes = {}, {}
    bad = 0

    cols_clean, dup = [], 0
    for c in columns or []:
        cx, cy = float(c["center"]["x"]), float(c["center"]["y"])
        if any(math.hypot(cx - k["center"]["x"], cy - k["center"]["y"]) < dedupe_mm for k in cols_clean):
            dup += 1
            continue
        b, h = float(c.get("b_mm") or 0), float(c.get("h_mm") or 0)
        if not (100 <= b <= 3000 and 100 <= h <= 3000):
            bad += 1
        key = "{}x{}".format(int(round(b)), int(round(h)))
        col_sizes[key] = col_sizes.get(key, 0) + 1
        xs.append(cx)
        ys.append(cy)
        cols_clean.append(c)
    if dup:
        warnings.append("Bo {} cot trung vi tri (< {} mm).".format(dup, int(dedupe_mm)))

    beams_clean, short = [], 0
    for bm in beams or []:
        s, e = bm["start_mm"], bm["end_mm"]
        if math.hypot(e["x"] - s["x"], e["y"] - s["y"]) <= min_beam_mm:
            short += 1
            continue
        b, h = float(bm.get("b_mm") or 0), float(bm.get("h_mm") or 0)
        if not (100 <= b <= 2500 and 150 <= h <= 3000):
            bad += 1
        key = "{}x{}".format(int(round(b)), int(round(h)))
        beam_sizes[key] = beam_sizes.get(key, 0) + 1
        xs += [s["x"], e["x"]]
        ys += [s["y"], e["y"]]
        beams_clean.append(bm)
    if short:
        warnings.append("Bo {} dam ngan hon {} mm.".format(short, int(min_beam_mm)))

    total = len(cols_clean) + len(beams_clean)
    extent = None
    sanity = "ok"
    if total == 0:
        sanity = "check"
        warnings.append("Khong co cau kien nao de dung.")
    else:
        extent = {"x_min": round(min(xs), 1), "x_max": round(max(xs), 1),
                  "y_min": round(min(ys), 1), "y_max": round(max(ys), 1)}
        span = max(extent["x_max"] - extent["x_min"], extent["y_max"] - extent["y_min"])
        if bad > 0.2 * total:
            sanity = "check"
            warnings.append("{} / {} cau kien co tiet dien ngoai khoang hop ly (cot 100-3000, dam b 100-2500 / "
                            "h 150-3000 mm) -> nghi sai ti le.".format(bad, total))
        elif bad:
            warnings.append("{} cau kien co tiet dien bat thuong, nen xem lai.".format(bad))
        if total > 1 and not (1000 <= span <= 2000000):
            sanity = "check"
            warnings.append("Pham vi mat bang {:.0f} mm la vo ly -> nghi sai ti le/khop truc.".format(span))

    return cols_clean, beams_clean, {
        "unit_sanity": sanity,
        "columns_in": len(columns or []), "columns_out": len(cols_clean),
        "beams_in": len(beams or []), "beams_out": len(beams_clean),
        "column_sizes": col_sizes, "beam_sizes": beam_sizes,
        "extent_mm": extent, "warnings": warnings,
    }


# Code IronPython chay trong Revit. Dung template thuong (khong f-string) + tham so JSON de tranh
# loi long/thut dong khi ghep chuoi. __SWALLOWER__ duoc chen o cap module.
FRAMING_CODE_TEMPLATE = r'''
import json, math, re
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from System.Collections.Generic import List as CList

doc = __revit__.ActiveUIDocument.Document
P = json.loads(__PARAMS__)
__SWALLOWER__

def ft(mm):
    return mm / 304.8

def eid(x):
    i = x.Id if hasattr(x, "Id") else x
    return int(i.Value) if hasattr(i, "Value") else int(i.IntegerValue)

def nm(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)

TAG = "PDF2BIM|" + P["source_tag"] + "|"
B_NAMES = ["b", "Width", "bf", "Width (b)", "B"]
H_NAMES = ["h", "Depth", "Height", "d", "Depth (h)", "H"]
D_NAMES = ["Diameter", "D", "Dia", "d", "b"]
GOOD = set(["concrete", "rc", "beton", "btct"])
RECT = set(["rectangular", "rectangle", "rect", "square"])
ROUND = set(["round", "circular", "circle"])
BAD = set(["steel", "thep", "w", "hss", "ub", "uc", "pipe", "angle", "channel", "timber", "wood",
           "glulam", "lvl", "tee", "i", "c", "z", "joist", "truss"])

def tokens(name):
    return set(t for t in re.split(r"[^0-9a-z]+", name.lower()) if t)

def find_param(sym, names):
    for n in names:
        p = sym.LookupParameter(n)
        if p and not p.IsReadOnly:
            return p
    return None

def has_dims(sym, shape):
    if shape == "round":
        return find_param(sym, D_NAMES) is not None
    return find_param(sym, B_NAMES) is not None and find_param(sym, H_NAMES) is not None

def pick_family(bic, wanted, shape="rect"):
    fams = {}
    for s in FilteredElementCollector(doc).OfCategory(bic).OfClass(FamilySymbol):
        fams.setdefault(s.FamilyName, []).append(s)
    used = {}
    for e in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
        try:
            fn = e.Symbol.FamilyName
        except Exception:
            continue
        used[fn] = used.get(fn, 0) + 1
    best, best_score, seen = None, None, []
    for fname, syms in fams.items():
        if not any(has_dims(s, shape) for s in syms):
            continue
        tk = tokens(fname)
        score = 0
        if wanted and fname == wanted:
            score += 1000
        elif wanted and wanted.lower() in fname.lower():
            score += 500
        want_tk, other_tk = (ROUND, RECT) if shape == "round" else (RECT, ROUND)
        if tk & GOOD:
            score += 10
            if tk & want_tk:
                score += 5
            if tk & other_tk:
                score -= 20  # Family tron cho cot chu nhat (hoac nguoc lai)
        elif score < 500:
            score -= 100  # khong phai Family be tong va khong duoc chi dinh -> loai
        if tk & BAD:
            score -= 100
        if score > 0 and used.get(fname):
            score += 3  # quy uoc cua du an: Family da dung cho cau kien da dat
        seen.append({"family": fname, "score": score})
        if best_score is None or score > best_score:
            best, best_score = fname, score
    if best is None or best_score <= 0:
        raise Exception("Khong tim thay Family be tong {} co tham so kich thuoc cho {} (ung vien: {}). "
                        "Hay nap Family hoac truyen base_*_family.".format(
                            "tron" if shape == "round" else "chu nhat", bic, json.dumps(seen)))
    return best, fams[best]

MARK_RE = re.compile(r"^[A-Z]{1,4}\d{0,3}[A-Z]?$")

def clean_mark(mark):
    m = (mark or "").strip().split(" ")[0].upper()
    return m if MARK_RE.match(m) and any(ch.isdigit() for ch in m) else ""

def size_match(s, b_mm, h_mm, shape):
    """(khop kich thuoc?, can xoay 90 do?) - b/h cua loai so voi kich thuoc theo phuong X/Y can dat."""
    if shape == "round":
        p = find_param(s, D_NAMES)
        return (p is not None and p.AsDouble() is not None and abs(p.AsDouble() * 304.8 - b_mm) < 5), False
    pb, ph = find_param(s, B_NAMES), find_param(s, H_NAMES)
    if not (pb and ph) or pb.AsDouble() is None or ph.AsDouble() is None:
        return False, False
    b, h = pb.AsDouble() * 304.8, ph.AsDouble() * 304.8
    if abs(b - b_mm) < 5 and abs(h - h_mm) < 5:
        return True, False
    if abs(b - h_mm) < 5 and abs(h - b_mm) < 5:
        return True, True
    return False, False

TYPE_CACHE = {}
def resolve_type(fam, syms, b_mm, h_mm, plan, mark="", shape="rect"):
    """
    Tra ve (FamilySymbol, swapped). swapped=True: dung lai loai b x h co san cho cot can dat h x b
    -> caller xoay cot 90 do thay vi tao loai moi trung lap.
    """
    b, h = int(round(b_mm)), int(round(h_mm))
    if shape == "round":
        sizes = ["{}DIA".format(b)]
    else:
        sizes = ["{}x{}".format(b, h), "{}x{}".format(h, b)]
    mk = clean_mark(mark)
    name = (mk + " - " + sizes[0]) if mk else sizes[0]  # quy uoc ten loai: '<ma> - <b>x<h>' / '<ma> - <d>DIA'
    key = (fam, shape, mk, b, h)
    if key in TYPE_CACHE:
        return TYPE_CACHE[key]
    names = [(nm(s), s) for s in syms]
    cands = [n for z in sizes for n in ((mk + " - " + z) if mk else z, z)]
    sym = None
    for want in cands:
        sym = next((s for n, s in names if n == want), None)
        if sym is not None:
            break
    if sym is None and mk:
        # Loai co san bat dau bang ma hieu (CC3 - ..., CC3_...) va cung kich thuoc
        sym = next((s for n, s in names if (n == mk or n.startswith(mk + " ") or n.startswith(mk + "-")
                                            or n.startswith(mk + "_")) and size_match(s, b, h, shape)[0]), None)
    swapped = False
    if sym is not None:
        name = nm(sym)
        ok, swapped = size_match(sym, b, h, shape)
        if not ok and shape != "round":
            swapped = name.endswith(sizes[1]) and sizes[0] != sizes[1]
        plan["types_existing"].add(fam + " : " + name)
    else:
        plan["types_to_create"].add(fam + " : " + name)
        if not P["dry_run"]:
            sym = syms[0].Duplicate(name)
            if shape == "round":
                find_param(sym, D_NAMES).Set(ft(b))
            else:
                find_param(sym, B_NAMES).Set(ft(b))
                find_param(sym, H_NAMES).Set(ft(h))
            syms.append(sym)
    if sym is not None and not sym.IsActive:
        sym.Activate()
    TYPE_CACHE[key] = (sym, swapped)
    return sym, swapped

def set_param(el, bip, value):
    p = el.get_Parameter(bip)
    if p and not p.IsReadOnly:
        p.Set(value)
        return True
    return False

def tagged(bics):
    out = []
    for bic in bics:
        for e in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
            p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            v = p.AsString() if p else None
            if v and v.startswith(TAG):
                out.append(e)
    return out

CATS = [BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_StructuralFraming]

def main():
    levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)
    lvl = next((l for l in levels if l.Name == P["level_name"]), None) or doc.ActiveView.GenLevel
    if lvl is None:
        return {"status": "error", "message": "Khong tim thay Level " + P["level_name"]}
    if P["top_level_name"]:
        top = next((l for l in levels if l.Name == P["top_level_name"]), None)
    else:
        above = [l for l in levels if l.Elevation > lvl.Elevation + ft(1)]
        prefix = lvl.Name.rsplit("-", 1)[0].strip().upper() if "-" in lvl.Name else ""
        same = [l for l in above if prefix and l.Name.upper().startswith(prefix)]
        top = (same or above or [None])[0]

    plan = {"types_existing": set(), "types_to_create": set()}
    cols, beams = P["columns"], P["beams"]
    col_fam = beam_fam = rcol_fam = None
    col_syms = rcol_syms = beam_syms = None
    if any(c.get("shape", "rect") != "round" for c in cols):
        col_fam, col_syms = pick_family(BuiltInCategory.OST_StructuralColumns, P["base_col_family"])
    if any(c.get("shape") == "round" for c in cols):
        rcol_fam, rcol_syms = pick_family(BuiltInCategory.OST_StructuralColumns, P["base_round_col_family"], "round")
    if beams:
        beam_fam, beam_syms = pick_family(BuiltInCategory.OST_StructuralFraming, P["base_beam_family"])
    existing = tagged(CATS)

    def col_type(c):
        if c.get("shape") == "round":
            d = c.get("diameter_mm") or c.get("b_mm", 300)
            return resolve_type(rcol_fam, rcol_syms, d, d, plan, c.get("mark", ""), "round")
        return resolve_type(col_fam, col_syms, c.get("b_mm", 500), c.get("h_mm", 500), plan, c.get("mark", ""))

    report = {
        "level": lvl.Name, "top_level": top.Name if top else None,
        "column_family": col_fam, "round_column_family": rcol_fam, "beam_family": beam_fam,
        "source_tag": P["source_tag"], "existing_with_same_tag": len(existing),
    }
    warnings = []
    if cols and top is None:
        warnings.append("Khong co Level nao tren " + lvl.Name + ": cot giu chieu cao mac dinh cua Family.")

    if P["dry_run"]:
        rotated = 0
        for c in cols:
            rotated += 1 if col_type(c)[1] else 0
        for b in beams:
            resolve_type(beam_fam, beam_syms, b.get("b_mm", 300), b.get("h_mm", 600), plan, b.get("mark", ""))
        report.update({"status": "dry_run", "columns_rotated_90_to_reuse_type": rotated, "would_create_columns": len(cols), "would_create_beams": len(beams),
                       "would_delete_existing": len(existing) if P["replace_existing"] else 0,
                       "types_existing": sorted(plan["types_existing"]),
                       "types_to_create": sorted(plan["types_to_create"]), "warnings": warnings})
        return report

    if existing and not P["replace_existing"]:
        report.update({"status": "error", "message": "Da co {} cau kien mang tag '{}'. Dung replace_existing=True "
                       "de xoa ban cu va dung lai, hoac doi source_tag.".format(len(existing), P["source_tag"])})
        return report

    created_cols, created_beams, deleted = [], [], 0
    t = Transaction(doc, "MCP: PDF2BIM Columns & Beams " + P["source_tag"])
    attach_failure_swallower(t)
    t.Start()
    try:
        if existing and P["replace_existing"]:
            doc.Delete(CList[ElementId]([e.Id for e in existing]))
            deleted = len(existing)

        for c in cols:
            sym, swapped = col_type(c)
            pt = XYZ(ft(c["center"]["x"]), ft(c["center"]["y"]), lvl.Elevation)
            inst = doc.Create.NewFamilyInstance(pt, sym, lvl, StructuralType.Column)
            set_param(inst, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM, 0.0)
            if top is not None:
                set_param(inst, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM, top.Id)
                set_param(inst, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM, 0.0)
            rot = float(c.get("rotation_deg") or 0.0) + (90.0 if swapped else 0.0)
            if abs(rot) > 1e-6:
                ElementTransformUtils.RotateElement(doc, inst.Id, Line.CreateBound(pt, pt + XYZ(0, 0, 1)), math.radians(rot))
            set_param(inst, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, TAG + "COL|" + str(c.get("mark", "")))
            created_cols.append(inst)

        for b in beams:
            sym, _sw = resolve_type(beam_fam, beam_syms, b.get("b_mm", 300), b.get("h_mm", 600), plan, b.get("mark", ""))
            p1 = XYZ(ft(b["start_mm"]["x"]), ft(b["start_mm"]["y"]), lvl.Elevation)
            p2 = XYZ(ft(b["end_mm"]["x"]), ft(b["end_mm"]["y"]), lvl.Elevation)
            inst = doc.Create.NewFamilyInstance(Line.CreateBound(p1, p2), sym, lvl, StructuralType.Beam)
            # Reset can le de khong ke thua gia tri cua lan ve truoc: Uniform / giua / dinh
            set_param(inst, BuiltInParameter.YZ_JUSTIFICATION, 0)
            set_param(inst, BuiltInParameter.Y_JUSTIFICATION, 1)
            set_param(inst, BuiltInParameter.Z_JUSTIFICATION, 0)
            set_param(inst, BuiltInParameter.Y_OFFSET_VALUE, 0.0)
            set_param(inst, BuiltInParameter.Z_OFFSET_VALUE, ft(float(b.get("z_offset_mm") or 0.0)))
            set_param(inst, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, TAG + "BEAM|" + str(b.get("mark", "")))
            created_beams.append(inst)

        # Cot cat Dam
        for ce in created_cols:
            for be in created_beams:
                try:
                    if JoinGeometryUtils.AreElementsJoined(doc, ce, be) and \
                            not JoinGeometryUtils.IsCuttingElementInJoin(doc, ce, be):
                        JoinGeometryUtils.SwitchJoinOrder(doc, ce, be)
                except Exception:
                    pass
        col_ids = [eid(e) for e in created_cols]
        beam_ids = [eid(e) for e in created_beams]
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        report.update({"status": "error", "message": str(ex)})
        return report

    # Doc lai sau khi ghi (verified write)
    alive_cols = [doc.GetElement(ElementId(i)) for i in col_ids]
    alive_cols = [e for e in alive_cols if e is not None]
    alive_beams = [e for e in (doc.GetElement(ElementId(i)) for i in beam_ids) if e is not None]
    top_ok = 0
    if top is not None:
        for e in alive_cols:
            p = e.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
            if p and p.AsElementId() == top.Id:
                top_ok += 1
    verify = {
        "columns_alive": len(alive_cols), "columns_expected": len(cols),
        "beams_alive": len(alive_beams), "beams_expected": len(beams),
        "columns_with_top_level": top_ok,
        "tagged_in_model": len(tagged(CATS)),
    }
    ok = verify["columns_alive"] == len(cols) and verify["beams_alive"] == len(beams) and \
        (top is None or top_ok == len(alive_cols))
    if not ok:
        warnings.append("So cau kien doc lai khong khop so da gui (Revit co the da xoa cau kien loi qua failure handler).")
    report.update({
        "status": "success" if ok else "warning",
        "deleted_existing": deleted,
        "created_columns_count": len(col_ids), "created_beams_count": len(beam_ids),
        "column_ids": col_ids, "beam_ids": beam_ids,
        "types_created": sorted(plan["types_to_create"]),
        "verify": verify, "warnings": warnings,
    })
    return report

try:
    print(json.dumps(main()))
except Exception as ex:
    print(json.dumps({"status": "error", "message": str(ex)}))
'''


# Code IronPython dung Mong don (FamilyInstance), Tuong (Wall.Create) va Mong bang (Floor mong)
# theo dung loai co san cua du an; tham so qua JSON, __SWALLOWER__ chen o cap module.
FOOTING_WALL_CODE_TEMPLATE = r'''
import json, math, re
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from System.Collections.Generic import List as CList

doc = __revit__.ActiveUIDocument.Document
P = json.loads(__PARAMS__)
__SWALLOWER__

def ft(mm):
    return mm / 304.8

def eid(x):
    i = x.Id if hasattr(x, "Id") else x
    return int(i.Value) if hasattr(i, "Value") else int(i.IntegerValue)

def nm(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)

TAG = "PDF2BIM|" + P["source_tag"] + "|"
CATS = [BuiltInCategory.OST_Walls, BuiltInCategory.OST_StructuralFoundation, BuiltInCategory.OST_Floors]

def set_param(el, bip, value):
    p = el.get_Parameter(bip)
    if p and not p.IsReadOnly:
        p.Set(value)
        return True
    return False

def lookup_mm(sym, names):
    for n in names:
        p = sym.LookupParameter(n)
        if p and p.StorageType == StorageType.Double:
            return p.AsDouble() * 304.8
    return None

def tagged():
    out = []
    for bic in CATS:
        for e in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
            p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            v = p.AsString() if p else None
            if v and v.startswith(TAG):
                out.append(e)
    return out

# ---- Loai tuong theo ma: ten ket thuc bang ' - <MA>' (HPCE - Dincel Wall - 200mm INSITU - W1) ----
WALL_TYPES = [wt for wt in FilteredElementCollector(doc).OfClass(WallType) if wt.Kind == WallKind.Basic]
def _exact_wall_type(mk, thick_mm):
    cands = [wt for wt in WALL_TYPES if abs(wt.Width * 304.8 - thick_mm) < 1]
    exact = [wt for wt in cands if nm(wt).upper().endswith(" - " + mk) or nm(wt).upper().endswith(" " + mk)]
    return exact[0] if exact else None

CREATED_WT = {}
def wall_type_for(mark, thick_mm):
    """
    Loai tuong theo MA (ten ket thuc ' - <MA>'). Khong co -> chi nhan ban khi nguoi dung chi dinh
    wall_type_from {MA: MA_goc} (vd SW2 <- SW1, ten moi thay hau to). KHONG tu chon loai thay the.
    """
    mk = (mark or "").upper()
    wt = _exact_wall_type(mk, thick_mm)
    if wt is not None:
        return wt, "mark"
    base_mk = (P.get("wall_type_from") or {}).get(mk) or (P.get("wall_type_from") or {}).get(mark)
    if base_mk:
        if mk in CREATED_WT:
            return CREATED_WT[mk], "created"
        base = _exact_wall_type(base_mk.upper(), thick_mm)
        if base is None:
            return None, None
        new_name = nm(base)[:len(nm(base)) - len(base_mk)] + mk
        if P["dry_run"]:
            CREATED_WT[mk] = base
            return base, "will_create:" + new_name
        nt = base.Duplicate(new_name)
        WALL_TYPES.append(nt)
        CREATED_WT[mk] = nt
        return nt, "created:" + new_name
    return None, None

# ---- Loai mong don: '<MA> - LxWxDD' trong Family co Length/Width ----
PAD_SYMS = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFoundation).OfClass(FamilySymbol))
def pad_type_for(mark, x_mm, y_mm):
    """Tra ve (symbol, can_xoay_90). Family: Width theo X, Length theo Y khi chua xoay."""
    mk = (mark or "").upper()
    best = None
    for s in PAD_SYMS:
        w, l = lookup_mm(s, ["Width", "b"]), lookup_mm(s, ["Length", "h"])
        if w is None or l is None:
            continue
        name_ok = nm(s).upper().startswith(mk + " ")
        if abs(w - x_mm) < 5 and abs(l - y_mm) < 5:
            key = (name_ok, 1)
            rot = False
        elif abs(w - y_mm) < 5 and abs(l - x_mm) < 5:
            key = (name_ok, 0)
            rot = True
        else:
            continue
        if best is None or key > best[0]:
            best = (key, s, rot)
    return (best[1], best[2]) if best else (None, False)

FLOOR_TYPES = list(FilteredElementCollector(doc).OfClass(FloorType))
def strip_type_for(mark, width_mm, thick_mm):
    mk = (mark or "").upper()
    for ft_ in FLOOR_TYPES:
        if ft_.IsFoundationSlab and nm(ft_).upper().startswith(mk + " "):
            return ft_
    want = "{}WX{}D".format(int(width_mm), int(thick_mm or 0))
    for ft_ in FLOOR_TYPES:
        if ft_.IsFoundationSlab and want in nm(ft_).upper().replace(" ", ""):
            return ft_
    return None

def rect_loop(s, e, width):
    sx, sy, ex, ey = ft(s["x"]), ft(s["y"]), ft(e["x"]), ft(e["y"])
    L = math.hypot(ex - sx, ey - sy)
    nx, ny = -(ey - sy) / L * ft(width) / 2.0, (ex - sx) / L * ft(width) / 2.0
    pts = [XYZ(sx + nx, sy + ny, 0), XYZ(ex + nx, ey + ny, 0), XYZ(ex - nx, ey - ny, 0), XYZ(sx - nx, sy - ny, 0)]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    return loop

def poly_loop(pts):
    xyz = [XYZ(ft(q["x"]), ft(q["y"]), 0) for q in pts]
    loop = CurveLoop()
    for i in range(len(xyz)):
        loop.Append(Line.CreateBound(xyz[i], xyz[(i + 1) % len(xyz)]))
    return loop

def bb_overlap(a, b):
    ba, bb_ = a.get_BoundingBox(None), b.get_BoundingBox(None)
    if ba is None or bb_ is None:
        return False
    return (min(ba.Max.X, bb_.Max.X) - max(ba.Min.X, bb_.Min.X) > 0.01 and
            min(ba.Max.Y, bb_.Max.Y) - max(ba.Min.Y, bb_.Min.Y) > 0.01 and
            min(ba.Max.Z, bb_.Max.Z) - max(ba.Min.Z, bb_.Min.Z) > 0.01)

def main():
    levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)
    lvl = next((l for l in levels if l.Name == P["level_name"]), None) or doc.ActiveView.GenLevel
    if lvl is None:
        return {"status": "error", "message": "Khong tim thay Level " + P["level_name"]}
    if P["wall_top_level_name"]:
        top = next((l for l in levels if l.Name == P["wall_top_level_name"]), None)
    else:
        above = [l for l in levels if l.Elevation > lvl.Elevation + ft(1)]
        prefix = lvl.Name.rsplit("-", 1)[0].strip().upper() if "-" in lvl.Name else ""
        same = [l for l in above if prefix and l.Name.upper().startswith(prefix)]
        top = (same or above or [None])[0]

    plan, problems = [], []
    for p in P["pads"]:
        sym, rot = pad_type_for(p["mark"], p["x_mm"], p["y_mm"])
        if sym is None:
            problems.append("PAD {} {}x{}: khong co loai phu hop".format(p["mark"], p["x_mm"], p["y_mm"]))
        plan.append(("PAD", p, sym, rot))
    for w in P["walls"]:
        if not P["dry_run"] and (P.get("wall_type_from") or {}).get(w["mark"]) and w["mark"].upper() not in CREATED_WT:
            wt, how = None, "defer"   # nhan ban trong Transaction
        else:
            wt, how = wall_type_for(w["mark"], w.get("thickness_mm", 200))
        if wt is None and how != "defer":
            problems.append("WALL {}: du an chua co loai tuong ' - {}' {} mm (truyen wall_type_from de nhan ban)".format(
                w["mark"], w["mark"], w.get("thickness_mm")))
        plan.append(("WALL", w, wt, how))
    for s in P["strips"]:
        st = strip_type_for(s["mark"], s["width_mm"], s.get("thickness_mm"))
        if st is None:
            problems.append("STRIP {}: khong co loai san mong".format(s["mark"]))
        plan.append(("STRIP", s, st, None))

    existing = tagged()
    types_used = {}
    for kind, item, typ, extra in plan:
        if typ is not None:
            k = kind + " : " + nm(typ)
            types_used[k] = types_used.get(k, 0) + 1
    report = {"level": lvl.Name, "wall_top_level": top.Name if top else None,
              "source_tag": P["source_tag"], "existing_with_same_tag": len(existing),
              "types_used": types_used, "problems": problems,
              "pads_rotated_90": sum(1 for k, i, t, r in plan if k == "PAD" and r),
              "wall_types_to_create": sorted(set(h.split(":", 1)[1] for k, i, t, h in plan
                                                 if k == "WALL" and h and h.startswith("will_create:")))}
    if P["dry_run"]:
        report.update({"status": "dry_run", "would_create": {"pads": len(P["pads"]), "walls": len(P["walls"]),
                       "strips": len(P["strips"])}, "would_delete_existing": len(existing) if P["replace_existing"] else 0})
        return report
    if problems:
        report.update({"status": "error", "message": "Thieu loai cho mot so cau kien - xem 'problems'. Khong dung gi."})
        return report
    if existing and not P["replace_existing"] and not P.get("append_to_existing"):
        report.update({"status": "error", "message": "Da co {} cau kien mang tag '{}'. Dung replace_existing=True (dung lai ca trang) hoac append_to_existing=True (chi bo sung).".format(
            len(existing), P["source_tag"])})
        return report

    created = {"PAD": [], "WALL": [], "STRIP": []}
    t = Transaction(doc, "MCP: PDF2BIM Footings & Walls " + P["source_tag"])
    attach_failure_swallower(t)
    t.Start()
    try:
        deleted = 0
        if existing and P["replace_existing"]:
            doc.Delete(CList[ElementId]([e.Id for e in existing]))
            deleted = len(existing)
        off = ft(P["footing_top_offset_mm"])
        for kind, item, typ, extra in plan:
            if kind == "PAD":
                if not typ.IsActive:
                    typ.Activate()
                pt = XYZ(ft(item["center"]["x"]), ft(item["center"]["y"]), lvl.Elevation)
                inst = doc.Create.NewFamilyInstance(pt, typ, lvl, StructuralType.Footing)
                set_param(inst, BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM, off)
                rot = float(item.get("rotation_deg") or 0.0) + (90.0 if extra else 0.0)
                if abs(rot) > 1e-6:
                    ElementTransformUtils.RotateElement(doc, inst.Id, Line.CreateBound(pt, pt + XYZ(0, 0, 1)), math.radians(rot))
                set_param(inst, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, TAG + "PAD|" + item["mark"])
                created["PAD"].append(eid(inst))
            elif kind == "WALL":
                if typ is None:
                    typ, extra = wall_type_for(item["mark"], item.get("thickness_mm", 200))
                s, e = item["start_mm"], item["end_mm"]
                if item.get("mid_mm"):
                    # Tuong CONG: cung tron qua dau - giua - cuoi (tim tuong)
                    m_ = item["mid_mm"]
                    line = Arc.Create(XYZ(ft(s["x"]), ft(s["y"]), lvl.Elevation), XYZ(ft(e["x"]), ft(e["y"]), lvl.Elevation),
                                      XYZ(ft(m_["x"]), ft(m_["y"]), lvl.Elevation))
                else:
                    line = Line.CreateBound(XYZ(ft(s["x"]), ft(s["y"]), lvl.Elevation), XYZ(ft(e["x"]), ft(e["y"]), lvl.Elevation))
                h = (top.Elevation - lvl.Elevation) if top else ft(3000)
                w = Wall.Create(doc, line, typ.Id, lvl.Id, h, 0.0, False, True)
                set_param(w, BuiltInParameter.WALL_KEY_REF_PARAM, 0)   # tim tuong
                w.Location.Curve = line                                # dat lai dung tim
                if top:
                    set_param(w, BuiltInParameter.WALL_HEIGHT_TYPE, top.Id)
                    set_param(w, BuiltInParameter.WALL_TOP_OFFSET, 0.0)
                set_param(w, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, TAG + "WALL|" + item["mark"])
                created["WALL"].append(eid(w))
            else:
                if item.get("outer_loop_mm"):
                    loops = [poly_loop(item["outer_loop_mm"])] + [poly_loop(h) for h in item.get("opening_loops_mm", [])]
                else:
                    loops = [rect_loop(item["start_mm"], item["end_mm"], item["width_mm"])]
                fl = Floor.Create(doc, CList[CurveLoop](loops), typ.Id, lvl.Id)
                set_param(fl, BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM, off)
                set_param(fl, BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL, 1)
                set_param(fl, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, TAG + "STRIP|" + item["mark"])
                created["STRIP"].append(eid(fl))
        # Mong don / mong bang chong nhau (mong gop ve chung 1 duong bao) -> Join Geometry de Revit cat
        # phan giao: KHONG tinh trung khoi luong be tong, khong canh bao chong.
        doc.Regenerate()
        found = [doc.GetElement(ElementId(i)) for i in created["PAD"] + created["STRIP"]]
        joined = 0
        for i in range(len(found)):
            for j in range(i + 1, len(found)):
                a, b = found[i], found[j]
                if a is None or b is None or not bb_overlap(a, b):
                    continue
                # Hinh bao chong chua du (vd tam mong bang chu U trum len mong don) -> chi Join khi khoi
                # hinh hoc THUC SU giao nhau, tranh canh bao 'joined but do not intersect'.
                if FilteredElementCollector(doc, CList[ElementId]([b.Id])).WherePasses(
                        ElementIntersectsElementFilter(a)).GetElementCount() == 0:
                    continue
                try:
                    if not JoinGeometryUtils.AreElementsJoined(doc, a, b):
                        JoinGeometryUtils.JoinGeometry(doc, a, b)
                        joined += 1
                except Exception:
                    pass
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        report.update({"status": "error", "message": str(ex)})
        return report

    alive = dict((k, len([i for i in v if doc.GetElement(ElementId(i)) is not None])) for k, v in created.items())
    ok = alive["PAD"] == len(P["pads"]) and alive["WALL"] == len(P["walls"]) and alive["STRIP"] == len(P["strips"])
    report.update({"status": "success" if ok else "warning", "deleted_existing": deleted,
                   "joined_overlapping_footings": joined,
                   "created_ids": created, "verify": {"alive": alive, "expected": {"PAD": len(P["pads"]),
                   "WALL": len(P["walls"]), "STRIP": len(P["strips"])}, "tagged_in_model": len(tagged())}})
    return report

try:
    print(json.dumps(main()))
except Exception as ex:
    print(json.dumps({"status": "error", "message": str(ex)}))
'''


# Doc hinh bao moi cau kien ket cau (chi doc) de kiem tra TRUNG LAP truoc/sau khi dung.
ELEMENTS_QUERY_CODE = r"""
import json
from Autodesk.Revit.DB import *
CATS = [BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_StructuralFraming, BuiltInCategory.OST_Walls,
        BuiltInCategory.OST_StructuralFoundation, BuiltInCategory.OST_Floors]
def nm(e):
    try:
        return e.Name
    except Exception:
        return Element.Name.__get__(e)
els = []
for bic in CATS:
    for e in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        t = doc.GetElement(e.GetTypeId())
        d = {"id": int(e.Id.Value) if hasattr(e.Id, "Value") else e.Id.IntegerValue,
             "cat": e.Category.Name, "type": nm(t) if t else None,
             "tag": ((p.AsString() if p else "") or "")[:80],
             "bb": [bb.Min.X * 304.8, bb.Min.Y * 304.8, bb.Max.X * 304.8, bb.Max.Y * 304.8,
                    bb.Min.Z * 304.8, bb.Max.Z * 304.8]}
        # Tuong / dam thang: duong tim de so trung theo tuyen (hinh bao cau kien xien qua lon)
        loc = e.Location
        if bic in (BuiltInCategory.OST_Walls, BuiltInCategory.OST_StructuralFraming) and isinstance(loc, LocationCurve) \
                and isinstance(loc.Curve, Line):
            c0, c1 = loc.Curve.GetEndPoint(0), loc.Curve.GetEndPoint(1)
            d["line"] = [c0.X * 304.8, c0.Y * 304.8, c1.X * 304.8, c1.Y * 304.8]
            try:
                d["width"] = e.Width * 304.8
            except Exception:
                d["width"] = 300.0
        els.append(d)
lv = [{"name": l.Name, "elev": l.Elevation * 304.8} for l in FilteredElementCollector(doc).OfClass(Level)]
av = doc.ActiveView
KEYS = ("overlap", "identical", "same place", "duplicate instance")
warns = []
for w in doc.GetWarnings():
    txt = w.GetDescriptionText()
    if any(k in txt.lower() for k in KEYS):
        ids = [x for x in w.GetFailingElements()] + [x for x in w.GetAdditionalElements()]
        warns.append({"text": txt, "ids": [int(x.Value) if hasattr(x, "Value") else x.IntegerValue for x in ids]})
print(json.dumps({"elements": els, "levels": lv, "warnings": warns,
                  "active_level": getattr(getattr(av, "GenLevel", None), "Name", None)}))
"""


CAD_ARCS_QUERY_CODE = r"""
import json
from Autodesk.Revit.DB import *
# Cung tron tren layer TUONG (ten layer co WALL) cua cac file CAD link/import -> [cx, cy, r] mm
av = doc.ActiveView
opt = Options()
opt.View = av
arcs = []
def lay(g):
    try:
        st = doc.GetElement(g.GraphicsStyleId)
        return st.GraphicsStyleCategory.Name if st and st.GraphicsStyleCategory else ""
    except Exception:
        return ""
def walk(geo):
    for g in geo:
        if isinstance(g, GeometryInstance):
            walk(g.GetInstanceGeometry())
        elif isinstance(g, Arc) and "WALL" in lay(g).upper():
            r = g.Radius * 304.8
            if 500.0 <= r <= 20000.0:
                arcs.append([round(g.Center.X * 304.8, 1), round(g.Center.Y * 304.8, 1), round(r, 1)])
# Moi file CAD link/import trong DU AN (khong phu thuoc view dang mo - vd dang o view 3D): link gan voi
# 1 view (OwnerViewId) thi doc hinh hoc theo chinh view do.
for imp in FilteredElementCollector(doc).OfClass(ImportInstance):
    try:
        o = Options()
        ov = imp.OwnerViewId
        if ov is not None and ov != ElementId.InvalidElementId and doc.GetElement(ov) is not None:
            o.View = doc.GetElement(ov)
        walk(imp.get_Geometry(o))
    except Exception:
        pass
uniq = sorted(set(tuple(a) for a in arcs))
print(json.dumps({"arcs": [list(a) for a in uniq]}))
"""


async def query_model_elements(revit_post, ctx=None):
    return await run_revit_json(revit_post, ELEMENTS_QUERY_CODE, "Query elements for duplicate check", ctx, timeout=180.0)


def resolve_level_range(levels, level_name, active_level, top_level_name=""):
    """(cao do level mm, cao do level dinh mm) - cung quy tac voi code dung trong Revit."""
    lv = sorted(levels, key=lambda l: l["elev"])
    lvl = next((l for l in lv if l["name"] == level_name), None) or next((l for l in lv if l["name"] == active_level), None)
    if lvl is None:
        return None, None
    if top_level_name:
        top = next((l for l in lv if l["name"] == top_level_name), None)
    else:
        above = [l for l in lv if l["elev"] > lvl["elev"] + 304.8]
        prefix = lvl["name"].rsplit("-", 1)[0].strip().upper() if "-" in lvl["name"] else ""
        same = [l for l in above if prefix and l["name"].upper().startswith(prefix)]
        top = (same or above or [None])[0]
    return lvl["elev"], (top["elev"] if top else None)


async def duplicate_guard(revit_post, planned, level_name, top_level_name="", ignore_tag_prefix="",
                          footing_top_offset_mm=-150.0, ctx=None):
    """
    planned: [(kind, item)] kind in COL|BEAM|WALL|PAD|STRIP. Tra (danh sach se trung voi phan tu dang co,
    model_info). Phan tu mang ignore_tag_prefix (se bi replace_existing xoa) duoc bo qua.
    """
    if dupc is None:
        return [], None
    info = await query_model_elements(revit_post, ctx)
    lvl, top = resolve_level_range(info.get("levels", []), level_name, info.get("active_level"), top_level_name)
    if lvl is None:
        return [], info
    items = []
    for i, (kind, it) in enumerate(planned):
        bb = dupc.planned_bbox(kind, it, lvl, top, footing_top_offset_mm)
        if bb:
            item = {"kind": kind, "index": i, "mark": it.get("mark"), "bb": bb}
            if kind in ("WALL", "BEAM") and it.get("start_mm") and it.get("end_mm") and not it.get("mid_mm"):
                item["line"] = [it["start_mm"]["x"], it["start_mm"]["y"], it["end_mm"]["x"], it["end_mm"]["y"]]
                item["width"] = it.get("thickness_mm") or it.get("b_mm") or 200
            items.append(item)
    return dupc.planned_vs_existing(items, info.get("elements", []), ignore_tag_prefix), info


async def post_build_duplicate_check(revit_post, ctx=None):
    """BAT BUOC sau khi dung: quet trung lap toan model (cung category, cung cho, cung cao do)."""
    if dupc is None:
        return {"status": "skipped", "message": "Thieu module duplicate_check"}
    info = await query_model_elements(revit_post, ctx)
    res = dupc.find_duplicates(info.get("elements", []))
    # Canh bao chong/trung cua chinh Revit (vd 'Highlighted floors overlap') cung tinh la TRUNG
    byid = dict((e["id"], e) for e in info.get("elements", []))
    for w in info.get("warnings", []):
        res["duplicates"].append({"kind": "revit_warning", "overlap": None, "text": w["text"],
                                  "elements": [{"id": i, "cat": byid.get(i, {}).get("cat"),
                                                "type": byid.get(i, {}).get("type"),
                                                "tag": byid.get(i, {}).get("tag")} for i in w["ids"]]})
    n = len(res["duplicates"])
    return {"status": "ok" if not n else "warning",
            "message": ("Khong co cau kien trung, khong co canh bao chong/trung cua Revit." if not n else
                        "Co {} truong hop TRUNG (cap cau kien cung category cung cho/cao do, hoac canh bao "
                        "chong/trung cua Revit) - phai xu ly (uu tien giu phan tu co tag PDF2BIM).".format(n)),
            "duplicates_count": n, "duplicates": res["duplicates"][:100],
            "overlaps_count": len(res["overlaps"]), "overlaps": res["overlaps"][:50]}


def _attach_dup_report(result, guard, post):
    """Gan ket qua kiem tra trung vao bao cao tool dung; co trung -> status 'warning'."""
    if not isinstance(result, dict):
        return result
    if guard is not None:
        result["would_duplicate_existing"] = guard
    if post is not None:
        result["duplicate_check"] = post
        if post.get("duplicates_count") and result.get("status") == "success":
            result["status"] = "warning"
            result["message"] = ("Sau khi dung con {} cap cau kien TRUNG (xem duplicate_check.duplicates) - "
                                 "phai xu ly truoc khi ket thuc.".format(post["duplicates_count"]))
    return result


def register_structural_tools(mcp, revit_get, revit_post):
    """Đăng ký các công cụ kết cấu vào FastMCP Server."""

    @mcp.tool()
    async def auto_calibrate_grids(
        page_number: int,
        pdf_path: str = "",
        method: str = "auto",
        level_name: str = "",
        overall_page: int = 0,
        ctx: Context = None
    ) -> str:
        """
        Phase 1 tu dong: khop he toa do PDF <-> Revit tu du lieu vector, tra ve pdf_grid_pt1/pt2
        (point), revit_grid_pt1/pt2_mm, ti le ban ve, sai so kiem tra, Title Block, Level.
        method:
          'grids'   - do vong tron dau truc + net truc tren PDF, ghep giao diem trung ten voi Grid Revit.
          'columns' - ban ve KHONG co luoi truc: ghep cot co ma tren PDF (CC3, CC4A...) voi cot da
                      co trong Revit di qua cao do level_name (mac dinh Level cua view dang mo),
                      theo tiet dien; goc/ti le duoc lam tron ve boi so 90 do / ti le ghi tren ban ve.
          'overall' - qua TRANG TONG (S200/S203...): trang zone -> trang tong -> cot da dung theo ban ve
                      ket cau. Dung khi dung zone thu 2 (vd Zone B) de 2 zone chung 1 he toa do.
                      overall_page=0 -> tu tim theo so hieu sheet.
          'auto'    - grids -> cad -> overall -> cad_position -> columns (mac dinh).
        pdf_path de trong -> tu tim 'Combined set_1.pdf' (thu muc lam viec, Desktop, Documents...).
        """
        path = find_project_pdf(pdf_path)
        if not path:
            return f"Error: Khong tim thay file PDF ('{pdf_path or DEFAULT_PDF_NAMES[0]}'). Hay cho biet duong dan."
        try:
            cal = await auto_calibrate(revit_post, path, page_number, ctx, method=method, level_name=level_name,
                                       overall_page=overall_page)
            cal["pdf_path"] = path
            cal["page"] = page_number
            return format_response(cal)
        except Exception as e:
            return f"Error khi tu dong khop luoi truc: {str(e)}"

    @mcp.tool()
    async def parse_pdf_structural_plan(
        page_number: int,
        pdf_path: str = "",
        pdf_grid_pt1: Optional[List[float]] = None,
        pdf_grid_pt2: Optional[List[float]] = None,
        revit_grid_pt1_mm: Optional[List[float]] = None,
        revit_grid_pt2_mm: Optional[List[float]] = None,
        include_slabs: bool = True,
        default_slab_thickness_mm: int = 150,
        drawing_area_bbox_mm: Optional[List[float]] = None,
        level_name: str = "",
        drawing_area_pt: Optional[List[float]] = None,
        require_beam_tag: bool = True,
        ctx: Context = None
    ) -> str:
        """
        Trich xuat Cot, Dam (Phase 2-3) va San + Lo mo chu X (Phase 4) tu mat bang ket cau PDF
        Vector, quy doi sang he toa do thuc te (mm) cua Revit.
        4 toa do Grid moc la TUY CHON: neu bo trong, tool tu dong khop luoi truc PDF <-> Revit
        (auto_calibrate_grids) tu du lieu vector - khong uoc luong bang mat.
        pdf_path de trong -> tu tim 'Combined set_1.pdf'.
        Ket qua 'slabs' dung truc tiep cho batch_create_structural_slabs.
        Chi quet trong khung mat bang (drawing_area_pt, tu lay tu buoc khop toa do) - bo chu thich,
        bang thong ke, khung ten. Cot: chi nhan hinh CO ma cot gan do (co cot tron 'shape=round');
        b_mm/h_mm theo phuong X/Y cua Revit. Dam: chi nhan khi co ghi chu dam (require_beam_tag) -
        trang san tren nen dat (slab_on_ground=true) thuong ra 0 dam la DUNG.
        """
        if extract_structural_pdf is None:
            return "Error: Thu vien pdf_struct_parser chua duoc nap."

        path = find_project_pdf(pdf_path)
        if not path:
            return f"Error: Khong tim thay file PDF ('{pdf_path or DEFAULT_PDF_NAMES[0]}'). Hay cho biet duong dan."

        try:
            (p_pt1, p_pt2, r_pt1, r_pt2), cal = await resolve_calibration(
                revit_post, path, page_number,
                (pdf_grid_pt1, pdf_grid_pt2, revit_grid_pt1_mm, revit_grid_pt2_mm), ctx, level_name=level_name)

            if ctx:
                await ctx.info(f"Đang bóc tách hình học kết cấu vector từ trang {page_number}...")

            transformer = AffineTransformer(
                tuple(p_pt1), tuple(p_pt2),
                tuple(r_pt1), tuple(r_pt2)
            )
            area_pt = drawing_area_pt or cal.get("drawing_area_pt")
            data = extract_structural_pdf(
                path, page_number - 1, transformer,
                include_slabs=include_slabs,
                default_slab_thickness_mm=default_slab_thickness_mm,
                drawing_area_bbox=tuple(drawing_area_bbox_mm) if drawing_area_bbox_mm else None,
                drawing_area_pt=tuple(area_pt) if area_pt else None,
                require_beam_tag=require_beam_tag
            )
            # LEGEND cua trang: cot chi la UNDER (nen xam, khong hatch) thuoc tang DUOI -> khong dung tu tang nay
            legend = {"legend_found": False}
            if lgd is not None and fitz is not None:
                try:
                    with fitz.open(path) as _ld:
                        legend = lgd.classify_by_legend(_ld[page_number - 1], transformer,
                                                        columns=data.get("columns", []),
                                                        scale=transformer.scale / 0.35277777777777775)
                    data["columns"] = legend.pop("keep_columns")
                    legend.pop("keep_walls", None)
                except Exception as ex:
                    legend = {"legend_found": False, "error": str(ex)}
            return format_response({
                "status": "success",
                "pdf_path": path,
                "legend": legend,
                "page": page_number,
                "calibration": {
                    "mode": cal.get("status"),
                    "method": cal.get("method"),
                    "matched_columns": cal.get("matched_columns"),
                    "warning": cal.get("warning"),
                    "anchors": cal.get("anchors"),
                    "drawing_scale": cal.get("drawing_scale"),
                    "residual_rms_mm": cal.get("residual_rms_mm"),
                    "title_block": cal.get("title_block"),
                    "revit": cal.get("revit"),
                    "pdf_grid_pt1": list(p_pt1), "pdf_grid_pt2": list(p_pt2),
                    "revit_grid_pt1_mm": list(r_pt1), "revit_grid_pt2_mm": list(r_pt2),
                },
                "drawing_area_pt": area_pt,
                "slab_on_ground": data.get("slab_on_ground"),
                "columns_count": len(data.get("columns", [])),
                "round_columns_count": data.get("round_columns", 0),
                "beams_count": len(data.get("beams", [])),
                "untagged_line_pairs_skipped": data.get("untagged_line_pairs_skipped", 0),
                "slabs_count": len(data.get("slabs", [])),
                "openings_count": len(data.get("openings", [])),
                "columns": data.get("columns", []),
                "beams": data.get("beams", []),
                "slabs": data.get("slabs", []),
                "openings": data.get("openings", []),
                "schedule_catalog": data.get("schedule_catalog", {})
            })
        except Exception as e:
            return f"Error khi trích xuất PDF: {str(e)}"

    @mcp.tool()
    async def parse_pdf_foundation_plan(
        page_number: int,
        pdf_path: str = "",
        pdf_grid_pt1: Optional[List[float]] = None,
        pdf_grid_pt2: Optional[List[float]] = None,
        revit_grid_pt1_mm: Optional[List[float]] = None,
        revit_grid_pt2_mm: Optional[List[float]] = None,
        default_pile_cap_thick_mm: int = 1200,
        default_pad_footing_thick_mm: int = 450,
        drawing_area_bbox_mm: Optional[List[float]] = None,
        level_name: str = "",
        ctx: Context = None
    ) -> str:
        """
        Trich xuat Vach cung (Shear Walls), Dai mong (Pile Caps), Coc (Piles), va Mong don/
        Mong dai khong coc (Pad/Strip Footings) tu mat bang mong PDF Vector, dong thoi quy doi
        sang he toa do thuc te (mm) cua Revit thong qua 2 diem giao truc Grid. Dung cho cac
        trang Footing/Pile Cap Marking Plan (vd: S201, S202) theo dung Phase 2B cua skill
        pdf-to-bim, khac voi parse_pdf_structural_plan (Cot/Dam tang dien hinh).
        4 toa do Grid moc la TUY CHON: bo trong -> tu dong khop luoi truc PDF <-> Revit tu du lieu
        vector (auto_calibrate_grids). pdf_path de trong -> tu tim 'Combined set_1.pdf'.
        drawing_area_bbox_mm (tuy chon): [x_min, y_min, x_max, y_max] theo mm Revit, dung de
        loai bo khung ten/bang thong ke ngoai vung mat bang khi can.
        """
        if extract_shear_walls_and_foundations is None or fitz is None:
            return "Error: Thu vien wall_and_foundation_parser hoac PyMuPDF (fitz) chua duoc nap."

        if AffineTransformer is None:
            return "Error: Thu vien pdf_struct_parser (AffineTransformer) chua duoc nap."

        path = find_project_pdf(pdf_path)
        if not path:
            return f"Error: Khong tim thay file PDF ('{pdf_path or DEFAULT_PDF_NAMES[0]}'). Hay cho biet duong dan."
        pdf_path = path

        try:
            (p_pt1, p_pt2, r_pt1, r_pt2), cal = await resolve_calibration(
                revit_post, pdf_path, page_number,
                (pdf_grid_pt1, pdf_grid_pt2, revit_grid_pt1_mm, revit_grid_pt2_mm), ctx, level_name=level_name)
        except Exception as e:
            return f"Error: {str(e)}"
        bbox = tuple(drawing_area_bbox_mm) if drawing_area_bbox_mm else None
        if bbox is None and cal.get("drawing_area_pt"):
            a = cal["drawing_area_pt"]
            _tr = AffineTransformer(tuple(p_pt1), tuple(p_pt2), tuple(r_pt1), tuple(r_pt2))
            _cs = [_tr.to_revit_mm(x, y) for x in (a[0], a[2]) for y in (a[1], a[3])]
            bbox = (min(c["x"] for c in _cs), min(c["y"] for c in _cs),
                    max(c["x"] for c in _cs), max(c["y"] for c in _cs))

        try:
            if ctx:
                await ctx.info(f"Dang boc tach Vach cung, Dai mong & Mong don/dai tu trang {page_number}...")

            transformer = AffineTransformer(
                tuple(p_pt1), tuple(p_pt2),
                tuple(r_pt1), tuple(r_pt2)
            )

            fitz_doc = fitz.open(pdf_path)
            page = fitz_doc[page_number - 1]

            # Trich xuat Text & Toa do tam Text (cung dinh dang voi pdf_struct_parser.extract_structural_pdf)
            texts = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span["text"].strip()
                        if not txt:
                            continue
                        bbox_span = span["bbox"]
                        cx, cy = (bbox_span[0] + bbox_span[2]) / 2, (bbox_span[1] + bbox_span[3]) / 2
                        rvt_pt = transformer.to_revit_mm(cx, cy)
                        texts.append({
                            "text": txt,
                            "x": rvt_pt["x"],
                            "y": rvt_pt["y"]
                        })

            # Boc tach Bang thong ke (Schedule) tren cung trang de lam fallback tra chieu day
            # cho Pad/Strip Footing khi ghi chu tren Plan chi co ma hieu (PF1, SF2...).
            schedule_catalog = parse_schedule_tables(page) if parse_schedule_tables else {}

            # Coc & dai coc: van dung parser cu (hinh tron coc trong da giac)
            legacy = extract_shear_walls_and_foundations(
                page, transformer, texts,
                default_pile_cap_thick_mm=default_pile_cap_thick_mm,
                default_pad_footing_thick_mm=default_pad_footing_thick_mm,
                drawing_area_bbox=bbox,
                schedule_catalog=schedule_catalog
            )
            # Mong don / tuong / mong bang: bo trich xuat the he 2 (footing_wall_extractor) - mong dat
            # theo tim cot + bang thong ke, tuong co hatch lien tuc, mong bang theo tuong chan dat.
            area_pt = cal.get("drawing_area_pt")
            # Trich xuat trong TUNG HUONG TRUC chinh cua trang (toa nha xoay -30.7 do, canh noi song song
            # Zone A...) roi xoay ve Revit va gop; moi nhan PF chi sinh 1 mong tren toan trang.
            mf = fwx.extract_foundation_multi_frame(
                page, transformer, area_pt, schedule_catalog, transformer.scale / 0.35277777777777775,
                extract_pdf_column_features, column_to_revit)
            pads, walls, strips, strip_polys = mf["pads"], mf["walls"], mf["strips"], mf["strip_polys"]
            unmatched = mf["unmatched"]
            rot_deg = mf["frames"][0]
            # TUONG CONG: tam/ban kinh goi y tu cung tuong cua file CAD (kien truc) link trong view + chuoi net
            # PDF khop tron; do tren PDF ket cau (2 mat cach 200 mm, hatch trong vanh khan, co ma/noi tiep tuyen).
            curved_info = {"cad_arcs": 0, "cad_offset_mm": None}
            try:
                cad_arcs = []
                try:
                    cad_arcs = (await run_revit_json(revit_post, CAD_ARCS_QUERY_CODE, "Query CAD wall arcs", ctx,
                                                     timeout=120.0)).get("arcs", [])
                except Exception:
                    cad_arcs = []
                c_segs = fwx.collect_segments(page, transformer, area_pt, min_len_mm=10.0)
                pdf_h = fwx.pdf_circle_hints(c_segs)
                cad_h, off, npair = fwx.align_cad_hints([tuple(a) for a in cad_arcs], pdf_h)
                curved = fwx.extract_curved_walls_guided(
                    c_segs, fwx.collect_labels(page, transformer, fwx.WALL_RE, area_pt),
                    fwx.hatch_points(page, transformer, area_pt=area_pt), pdf_h,
                    straight_walls=walls, cad_hints=cad_h if npair else [])
                joins = fwx.tangent_joins(curved, walls)       # noi kin tuong cong <-> tuong thang tai diem tiep tuyen
                walls = walls + curved
                curved_info = {"cad_arcs": len(cad_arcs), "cad_offset_mm": off if npair else None,
                               "cad_offset_pairs": npair, "curved_walls": len(curved), "tangent_joins": joins}
                if curved and not npair:
                    curved_info["warning"] = ("Khong co cung CAD kien truc de doi chieu ban kinh/tam -> tuong cong chi do tu "
                                              "PDF, de nhan nham cung kien truc chay sat tuong thang. Link file CAD kien "
                                              "truc vao du an hoac kiem tra tay truoc khi dung.")
            except Exception as ex:
                curved_info["error"] = str(ex)
            # LEGEND: tuong/cot chi la UNDER thuoc tang duoi -> khong dung tu trang nay
            legend = {"legend_found": False}
            if lgd is not None:
                try:
                    legend = lgd.classify_by_legend(page, transformer, walls=walls,
                                                    scale=transformer.scale / 0.35277777777777775)
                    walls = legend.pop("keep_walls")
                    legend.pop("keep_columns", None)
                except Exception as ex:
                    legend = {"legend_found": False, "error": str(ex)}
            fitz_doc.close()

            return format_response({
                "status": "success",
                "pdf_path": pdf_path,
                "page": page_number,
                "calibration": {
                    "mode": cal.get("status"),
                    "method": cal.get("method"),
                    "matched_columns": cal.get("matched_columns"),
                    "warning": cal.get("warning"),
                    "anchors": cal.get("anchors"),
                    "drawing_scale": cal.get("drawing_scale"),
                    "residual_rms_mm": cal.get("residual_rms_mm"),
                    "title_block": cal.get("title_block"),
                    "revit": cal.get("revit"),
                    "pdf_grid_pt1": list(p_pt1), "pdf_grid_pt2": list(p_pt2),
                    "revit_grid_pt1_mm": list(r_pt1), "revit_grid_pt2_mm": list(r_pt2),
                    "drawing_area_pt": area_pt,
                },
                "schedule": {k: v for k, v in schedule_catalog.items() if k.startswith(("PF", "SF"))},
                "pad_footings_count": len(pads),
                "walls_count": len(walls),
                "strip_footings_count": len(strips),
                "strip_footing_polygons_count": len(strip_polys),
                "pile_caps_count": len(legacy.get("pile_caps", [])),
                "unmatched_pf_labels": unmatched,
                "building_rotation_deg": round(rot_deg, 3),
                "orientation_frames_deg": mf["frames"],
                "curved_walls": curved_info,
                "legend": legend,
                "pad_footings": pads,
                "walls": walls,
                "strip_footings": strips,
                "strip_footing_polygons": strip_polys,
                "pile_caps": legacy.get("pile_caps", []),
                "standalone_piles": legacy.get("standalone_piles", []),
                "next_step": "Dua pad_footings / walls / strip_footing_polygons (KHONG dung strip_footings "
                             "tung dai - se chong nhau o goc) vao batch_create_footings_and_walls (dry_run truoc)."
            })
        except Exception as e:
            return f"Error khi trich xuat Vach cung/Dai mong/Mong don-dai tu PDF: {str(e)}"

    @mcp.tool()
    async def batch_create_structural_framing_and_columns(
        level_name: str,
        columns: List[Dict[str, Any]],
        beams: List[Dict[str, Any]],
        source_tag: str = "",
        dry_run: bool = False,
        replace_existing: bool = False,
        top_level_name: str = "",
        base_col_family: str = "",
        base_beam_family: str = "",
        base_round_col_family: str = "",
        force: bool = False,
        allow_duplicates: bool = False,
        ctx: Context = None
    ) -> str:
        """
        Dung Cot (truoc) va Dam (sau) hang loat trong 1 Transaction, theo quy trinh ghi co kiem chung:
          1. Preflight (khong can Revit): loc cot trung (<50 mm), dam qua ngan (<300 mm), kiem tra
             tiet dien 100-3000 mm & pham vi toa do -> unit_sanity 'ok'/'check'. 'check' -> DUNG,
             khong dung (tru khi force=True) vi thuong la sai ti le/khop truc.
          2. dry_run=True: chi doc Revit - bao Level dat/Level dinh cot, Family duoc chon, loai
             tiet dien co san/se tao, so cau kien cu cung source_tag. KHONG sua model.
          3. Ghi: dinh cot = Level ngay tren (hoac top_level_name); dam reset can le
             (giua/dinh, offset = z_offset_mm); moi cau kien ghi Comments 'PDF2BIM|<source_tag>|...'.
          4. Doc lai sau khi ghi: dem cau kien con ton tai, cot co dung Level dinh.
        source_tag: nhan nguon, vd 'S204-p22' (lay tu title_block). Neu da co cau kien cung tag
          -> bao loi chong dung trung; replace_existing=True de xoa ban cu va dung lai.
        base_col_family/base_beam_family/base_round_col_family: de trong -> tu chon Family be tong
          chu nhat / tron (loai tru Family thep/go); khong tim thay thi bao loi, KHONG lay bua.
        Cot: b_mm/h_mm theo phuong X/Y cua Revit; shape='round' + diameter_mm cho cot tron (loai
          '<ma> - <d>DIA'). Dung lai loai co san '<ma> - 800x300' cho cot 300x800 bang cach xoay 90 do.
        KIEM TRA TRUNG (bat buoc): truoc khi ghi so tung cau kien sap dung voi phan tu dang co (cung
          category, chong >= 90%, cung cao do) -> co trung thi KHONG ghi (tra 'would_duplicate_existing'),
          tru khi allow_duplicates=True. Sau khi ghi tu quet trung toan model ('duplicate_check').
        """
        tag = (source_tag or "manual").strip().replace("|", "-")
        if replace_existing and not source_tag:
            return "Error: replace_existing=True can source_tag cu the (vd 'S204-p22') de chi xoa dung phan da dung tu nguon do."

        cols_clean, beams_clean, pre = preflight_structural_payload(columns, beams)
        if pre["unit_sanity"] != "ok" and not dry_run and not force:
            return format_response({
                "status": "error",
                "message": "Preflight phat hien kich thuoc/pham vi bat thuong (co the sai ti le hoac khop truc). "
                           "Kiem tra lai calibration; chi dung force=True khi chac chan du lieu dung.",
                "preflight": pre,
            })

        planned = [("COL", c) for c in cols_clean] + [("BEAM", b) for b in beams_clean]
        try:
            guard, _ = await duplicate_guard(revit_post, planned, level_name, top_level_name,
                                             "PDF2BIM|" + tag + "|" if replace_existing else "", ctx=ctx)
        except Exception as e:
            return format_response({"status": "error", "message": "Kiem tra trung that bai: " + str(e)})
        if guard and not dry_run and not allow_duplicates:
            return format_response({
                "status": "error",
                "message": "{} cau kien sap dung se TRUNG voi phan tu dang co -> khong ghi. Xoa/xu ly phan tu cu "
                           "(existing_id) truoc, hoac dung replace_existing neu cung source_tag.".format(len(guard)),
                "would_duplicate_existing": guard, "preflight": pre})

        params = {
            "level_name": level_name,
            "top_level_name": top_level_name,
            "source_tag": tag,
            "dry_run": bool(dry_run),
            "replace_existing": bool(replace_existing),
            "base_col_family": base_col_family,
            "base_beam_family": base_beam_family,
            "base_round_col_family": base_round_col_family,
            "columns": cols_clean,
            "beams": beams_clean,
        }
        code = (FRAMING_CODE_TEMPLATE
                .replace("__PARAMS__", repr(json.dumps(params)))
                .replace("__SWALLOWER__", FAILURE_SWALLOWER_CODE))
        if ctx:
            await ctx.info("{} {} cot, {} dam tren level {} (tag {})...".format(
                "Chay thu" if dry_run else "Dang dung", len(cols_clean), len(beams_clean), level_name, tag))
        try:
            result = await run_revit_json(
                revit_post, code, "PDF2BIM framing {} {}".format(tag, "dry-run" if dry_run else "apply"),
                ctx, timeout=180.0)
        except Exception as e:
            return format_response({"status": "error", "message": str(e), "preflight": pre})
        if isinstance(result, dict):
            result["preflight"] = pre
        post = None
        if not dry_run and isinstance(result, dict) and result.get("status") in ("success", "warning"):
            post = await post_build_duplicate_check(revit_post, ctx)
        return format_response(_attach_dup_report(result, guard, post))

    @mcp.tool()
    async def batch_create_footings_and_walls(
        level_name: str,
        pad_footings: Optional[List[Dict[str, Any]]] = None,
        walls: Optional[List[Dict[str, Any]]] = None,
        strip_footings: Optional[List[Dict[str, Any]]] = None,
        source_tag: str = "",
        dry_run: bool = False,
        replace_existing: bool = False,
        footing_top_offset_mm: float = -150.0,
        wall_top_level_name: str = "",
        allow_duplicates: bool = False,
        wall_type_from: Optional[Dict[str, str]] = None,
        append_to_existing: bool = False,
        ctx: Context = None
    ) -> str:
        """
        Dung Mong don, Tuong va Mong bang tu ket qua parse_pdf_foundation_plan bang LOAI CO SAN cua du an:
          - Mong don: FamilyInstance loai '<MA> - LxWxDD' (Width theo X, Length theo Y; tu xoay 90 do khi
            can), dinh mong = Level + footing_top_offset_mm (mac dinh -150: duoi tam san 150).
          - Tuong: loai co ten ket thuc ' - <MA>' (W1, SW1, LW1, RW1...), dat dung TIM tuong, cao tu
            Level den Level ngay tren cung toa nha (hoac wall_top_level_name), structural.
          - Mong bang: san mong loai '<MA> - ...' (vd 'SF1 - 2500Wx500D'), dinh = Level + offset. Nen truyen
            strip_footing_polygons (da hop nhat, co outer_loop_mm) de khong chong be tong o goc.
          - Mong don/mong bang chong nhau (mong gop theo ban ve) duoc Join Geometry de khong tinh trung.
        Thieu loai cho bat ky cau kien nao -> bao 'problems', KHONG dung gi (khong tu chon loai thay the).
        wall_type_from {"SW2": "SW1"}: nhan ban loai tuong cua ma goc thanh ma moi (theo xac nhan nguoi dung).
        Quy trinh: dry_run=True truoc; moi cau kien ghi Comments 'PDF2BIM|<source_tag>|PAD|WALL|STRIP|<ma>';
        replace_existing=True xoa ban cu cung tag roi dung lai; append_to_existing=True CHI BO SUNG cau kien moi
        (vd tuong cong) vao trang da dung, khong xoa gi; doc lai so cau kien sau khi ghi.
        Tuong CONG: item co "mid_mm" (diem giua cung) -> Arc qua dau/giua/cuoi.
        KIEM TRA TRUNG (bat buoc): truoc khi ghi so voi phan tu dang co -> trung thi KHONG ghi (tru khi
        allow_duplicates=True); sau khi ghi tu quet trung toan model ('duplicate_check').
        """
        tag = (source_tag or "manual").strip().replace("|", "-")
        if replace_existing and not source_tag:
            return "Error: replace_existing=True can source_tag cu the (vd 'S201-p19')."
        planned = ([("PAD", x) for x in (pad_footings or [])] + [("WALL", x) for x in (walls or [])] +
                   [("STRIP", x) for x in (strip_footings or [])])
        try:
            guard, _ = await duplicate_guard(revit_post, planned, level_name, wall_top_level_name,
                                             "PDF2BIM|" + tag + "|" if replace_existing else "",
                                             footing_top_offset_mm, ctx=ctx)
        except Exception as e:
            return format_response({"status": "error", "message": "Kiem tra trung that bai: " + str(e)})
        if guard and not dry_run and not allow_duplicates:
            return format_response({
                "status": "error",
                "message": "{} cau kien sap dung se TRUNG voi phan tu dang co -> khong ghi. Xoa/xu ly phan tu cu "
                           "(existing_id) truoc, hoac dung replace_existing neu cung source_tag.".format(len(guard)),
                "would_duplicate_existing": guard})
        params = {
            "level_name": level_name, "wall_top_level_name": wall_top_level_name,
            "source_tag": tag, "dry_run": bool(dry_run), "replace_existing": bool(replace_existing),
            "footing_top_offset_mm": float(footing_top_offset_mm),
            "wall_type_from": wall_type_from or {},
            "append_to_existing": bool(append_to_existing) and not replace_existing,
            "pads": pad_footings or [], "walls": walls or [], "strips": strip_footings or [],
        }
        code = (FOOTING_WALL_CODE_TEMPLATE
                .replace("__PARAMS__", repr(json.dumps(params)))
                .replace("__SWALLOWER__", FAILURE_SWALLOWER_CODE))
        try:
            result = await run_revit_json(
                revit_post, code, "PDF2BIM footings/walls {} {}".format(tag, "dry-run" if dry_run else "apply"),
                ctx, timeout=300.0)
        except Exception as e:
            return format_response({"status": "error", "message": str(e)})
        post = None
        if not dry_run and isinstance(result, dict) and result.get("status") in ("success", "warning"):
            post = await post_build_duplicate_check(revit_post, ctx)
        return format_response(_attach_dup_report(result, guard, post))

    @mcp.tool()
    async def check_duplicates(ctx: Context = None) -> str:
        """
        Quet TRUNG LAP toan model (cot, dam, tuong, mong, san): 2 cau kien cung category, chong >= 90%
        dien tich cai nho hon, cung cao do, kich thuoc tuong duong -> 'duplicates' (phai xoa 1 trong 2).
        Chong lan lon khac loai/kich thuoc (mong don cat mong bang...) -> 'overlaps' (tham khao).
        BAT BUOC chay sau khi dung xong va bao ket qua cho nguoi dung.
        """
        try:
            return format_response(await post_build_duplicate_check(revit_post, ctx))
        except Exception as e:
            return format_response({"status": "error", "message": str(e)})

    @mcp.tool()
    async def batch_create_structural_slabs(
        level_name: str,
        slabs: List[Dict[str, Any]],
        ctx: Context = None
    ) -> str:
        """
        Dựng Sàn Kết cấu (Structural Slabs) và khoét lỗ mở (Openings) hàng loạt trong Revit trong 1 Transaction.
        """
        revit_code = f"""
import clr, json, math
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from System.Collections.Generic import List as CList

doc = __revit__.ActiveUIDocument.Document
{FAILURE_SWALLOWER_CODE}

def mm_to_ft(mm_val):
    return mm_val / 304.8

def get_or_create_floor_type(thickness_mm):
    target_name = "HPCE - {{}}mm Floor".format(int(thickness_mm))
    collector = FilteredElementCollector(doc).OfClass(FloorType)
    fallback = None
    for ft in collector:
        if ft.Name == target_name:
            return ft
        if not fallback:
            fallback = ft
    if not fallback:
        raise Exception("Khong tim thay FloorType mau")
    new_ft = fallback.Duplicate(target_name)
    try:
        cs = new_ft.GetCompoundStructure()
        if cs:
            cs.SetLayerWidth(0, mm_to_ft(thickness_mm))
            new_ft.SetCompoundStructure(cs)
    except Exception:
        pass
    return new_ft

def build_curve_loop(pt_list):
    cl = CurveLoop()
    n = len(pt_list)
    for i in range(n):
        p1 = XYZ(mm_to_ft(pt_list[i]['x']), mm_to_ft(pt_list[i]['y']), 0)
        p2 = XYZ(mm_to_ft(pt_list[(i+1)%n]['x']), mm_to_ft(pt_list[(i+1)%n]['y']), 0)
        if p1.DistanceTo(p2) > 0.005:
            cl.Append(Line.CreateBound(p1, p2))
    return cl

level_name = {json.dumps(level_name)}
slabs_data = {json.dumps(slabs)}

lvl = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == level_name), None)
if not lvl:
    lvl = doc.ActiveView.GenLevel

if not lvl:
    print(json.dumps({{"status": "error", "message": "Khong tim thay Level " + str(level_name)}}))
else:
    created_slabs = []
    t = Transaction(doc, "MCP: Auto-Build Structural Slabs from PDF")
    attach_failure_swallower(t)
    t.Start()
    try:
        for s in slabs_data:
            thk = s.get("thickness_mm", 150)
            ftype = get_or_create_floor_type(thk)
            
            profile_loops = CList[CurveLoop]()
            outer_cl = build_curve_loop(s["outer_loop_mm"])
            profile_loops.Add(outer_cl)
            
            for op in s.get("opening_loops_mm", []):
                if len(op) >= 3:
                    op_cl = build_curve_loop(op)
                    profile_loops.Add(op_cl)
            
            floor_inst = Floor.Create(doc, profile_loops, ftype.Id, lvl.Id)
            
            p_struct = floor_inst.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
            if p_struct and not p_struct.IsReadOnly:
                p_struct.Set(1)
                
            z_off = s.get("z_offset_mm", 0.0)
            if z_off != 0.0:
                pz = floor_inst.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
                if pz and not pz.IsReadOnly:
                    pz.Set(mm_to_ft(z_off))
                    
            created_slabs.append(floor_inst.Id.IntegerValue)
            
        t.Commit()
        print(json.dumps({{
            "status": "success",
            "level": lvl.Name,
            "created_slabs_count": len(created_slabs),
            "slab_ids": created_slabs
        }}))
    except Exception as ex:
        t.RollBack()
        print(json.dumps({{"status": "error", "message": str(ex)}}))
"""
        payload = {"code": revit_code, "description": f"Auto-Build Slabs for {level_name}"}
        if ctx:
            await ctx.info(f"Đang dựng {len(slabs)} sàn kết cấu trên level {level_name}...")
        response = await revit_post("/execute_code/", payload, ctx, timeout=120.0)
        return format_response(response)

    @mcp.tool()
    async def batch_create_structural_walls_and_foundations(
        level_name: str,
        shear_walls: Optional[List[Dict[str, Any]]] = None,
        pile_caps: Optional[List[Dict[str, Any]]] = None,
        pad_footings: Optional[List[Dict[str, Any]]] = None,
        strip_footings: Optional[List[Dict[str, Any]]] = None,
        wall_height_mm: float = 3500.0,
        ctx: Context = None
    ) -> str:
        """
        Dung Vach cung ket cau (Structural Shear Walls), Dai mong (Pile Caps), va Mong don/
        Mong dai khong coc (Pad/Strip Footings, dat truc tiep len dat/da) hang loat trong Revit
        trong 1 Transaction.
        """
        revit_code = f"""
import clr, json, math
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from System.Collections.Generic import List as CList

doc = __revit__.ActiveUIDocument.Document
{FAILURE_SWALLOWER_CODE}

def mm_to_ft(mm_val):
    return mm_val / 304.8

def get_or_create_structural_wall_type(thickness_mm):
    target_name = "RC Shear Wall - {{}}mm".format(int(thickness_mm))
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).OfClass(WallType)
    fallback_wt = None
    for wt in collector:
        if str(wt.Kind) == "Basic":
            fallback_wt = wt
            if wt.Name == target_name:
                return wt
    if not fallback_wt:
        for wt in collector:
            fallback_wt = wt
            break
    if not fallback_wt:
        raise Exception("Khong tim thay WallType mau")
    new_wt = fallback_wt.Duplicate(target_name)
    cs = new_wt.GetCompoundStructure()
    if cs and cs.LayerCount > 0:
        cs.SetLayerWidth(0, mm_to_ft(thickness_mm))
        new_wt.SetCompoundStructure(cs)
    return new_wt

def get_or_create_foundation_slab_type(type_prefix, thickness_mm):
    target_name = "{{}} - {{}}mm".format(type_prefix, int(thickness_mm))
    collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFoundation).OfClass(FloorType)
    if collector.GetElementCount() == 0:
        collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).OfClass(FloorType)
    fallback_ft = None
    for ft in collector:
        fallback_ft = ft
        if ft.Name == target_name:
            return ft
    if not fallback_ft:
        fallback_ft = FilteredElementCollector(doc).OfClass(FloorType).FirstElement()
    if not fallback_ft:
        raise Exception("Khong tim thay FloorType mau cho Mong")
    new_ft = fallback_ft.Duplicate(target_name)
    cs = new_ft.GetCompoundStructure()
    if cs and cs.LayerCount > 0:
        cs.SetLayerWidth(0, mm_to_ft(thickness_mm))
        new_ft.SetCompoundStructure(cs)
    return new_ft

def build_foundation_loop(doc, lvl, outer_loop_mm):
    loop = CurveLoop()
    pts = outer_loop_mm
    n = len(pts)
    for i in range(n):
        pt1 = XYZ(mm_to_ft(pts[i]["x"]), mm_to_ft(pts[i]["y"]), lvl.Elevation)
        pt2 = XYZ(mm_to_ft(pts[(i+1) % n]["x"]), mm_to_ft(pts[(i+1) % n]["y"]), lvl.Elevation)
        if pt1.DistanceTo(pt2) > mm_to_ft(10):
            loop.Append(Line.CreateBound(pt1, pt2))
    return loop

level_name = {json.dumps(level_name)}
walls_data = {json.dumps(shear_walls or [])}
caps_data = {json.dumps(pile_caps or [])}
pad_footings_data = {json.dumps(pad_footings or [])}
strip_footings_data = {json.dumps(strip_footings or [])}
default_wall_h = mm_to_ft({wall_height_mm})

lvl = next((l for l in FilteredElementCollector(doc).OfClass(Level) if l.Name == level_name), None)
if not lvl:
    lvl = doc.ActiveView.GenLevel

if not lvl:
    print(json.dumps({{"status": "error", "message": "Khong tim thay Level " + str(level_name)}}))
else:
    created_walls = []
    created_caps = []
    created_pad_footings = []
    created_strip_footings = []
    t = Transaction(doc, "MCP: Auto-Build Walls & Foundations")
    attach_failure_swallower(t)
    t.Start()
    try:
        # 1. Dung Vach cung (Shear Walls)
        for sw in walls_data:
            wt = get_or_create_structural_wall_type(sw.get("thickness_mm", 250))
            p1 = XYZ(mm_to_ft(sw["start_mm"]["x"]), mm_to_ft(sw["start_mm"]["y"]), lvl.Elevation)
            p2 = XYZ(mm_to_ft(sw["end_mm"]["x"]), mm_to_ft(sw["end_mm"]["y"]), lvl.Elevation)
            if p1.DistanceTo(p2) > mm_to_ft(200):
                line = Line.CreateBound(p1, p2)
                wall = Wall.Create(doc, line, wt.Id, lvl.Id, default_wall_h, 0.0, False, True)
                p_usage = wall.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM)
                if p_usage and not p_usage.IsReadOnly:
                    p_usage.Set(2)  # Shear
                created_walls.append(wall.Id.IntegerValue)

        # 2. Dung Dai mong (Pile Caps)
        for pc in caps_data:
            ft = get_or_create_foundation_slab_type("Pile Cap Foundation", pc.get("thickness_mm", 1200))
            loop = build_foundation_loop(doc, lvl, pc["outer_loop_mm"])
            loops = CList[CurveLoop]()
            loops.Add(loop)
            pile_cap = Floor.Create(doc, loops, ft.Id, lvl.Id)
            p_struct = pile_cap.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
            if p_struct and not p_struct.IsReadOnly:
                p_struct.Set(1)
            created_caps.append(pile_cap.Id.IntegerValue)

        # 3. Dung Mong don (Pad Footings) - khong coc, dat truc tiep len dat/da
        for pf in pad_footings_data:
            ft = get_or_create_foundation_slab_type("Pad Footing", pf.get("thickness_mm", 450))
            loop = build_foundation_loop(doc, lvl, pf["outer_loop_mm"])
            loops = CList[CurveLoop]()
            loops.Add(loop)
            pad = Floor.Create(doc, loops, ft.Id, lvl.Id)
            p_struct = pad.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
            if p_struct and not p_struct.IsReadOnly:
                p_struct.Set(1)
            created_pad_footings.append(pad.Id.IntegerValue)

        # 4. Dung Mong dai (Strip Footings) - khong coc, dat truc tiep len dat/da
        for sf in strip_footings_data:
            ft = get_or_create_foundation_slab_type("Strip Footing", sf.get("thickness_mm", 450))
            loop = build_foundation_loop(doc, lvl, sf["outer_loop_mm"])
            loops = CList[CurveLoop]()
            loops.Add(loop)
            strip = Floor.Create(doc, loops, ft.Id, lvl.Id)
            p_struct = strip.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
            if p_struct and not p_struct.IsReadOnly:
                p_struct.Set(1)
            created_strip_footings.append(strip.Id.IntegerValue)

        t.Commit()
        print(json.dumps({{
            "status": "success",
            "level": lvl.Name,
            "created_shear_walls": len(created_walls),
            "created_pile_caps": len(created_caps),
            "created_pad_footings": len(created_pad_footings),
            "created_strip_footings": len(created_strip_footings),
            "wall_ids": created_walls,
            "pile_cap_ids": created_caps,
            "pad_footing_ids": created_pad_footings,
            "strip_footing_ids": created_strip_footings
        }}))
    except Exception as ex:
        t.RollBack()
        print(json.dumps({{"status": "error", "message": str(ex)}}))
"""
        payload = {"code": revit_code, "description": f"Auto-Build Walls & Foundations for {level_name}"}
        if ctx:
            await ctx.info(
                f"Dang dung {len(shear_walls or [])} vach cung, {len(pile_caps or [])} dai mong, "
                f"{len(pad_footings or [])} mong don, {len(strip_footings or [])} mong dai tren level {level_name}..."
            )
        response = await revit_post("/execute_code/", payload, ctx, timeout=120.0)
        return format_response(response)

    @mcp.tool()
    async def generate_visual_qa_overlay(
        page_number: int,
        level_name: str,
        pdf_path: str = "",
        pdf_grid_pt1: Optional[List[float]] = None,
        pdf_grid_pt2: Optional[List[float]] = None,
        revit_grid_pt1_mm: Optional[List[float]] = None,
        revit_grid_pt2_mm: Optional[List[float]] = None,
        output_png_path: str = "qa_overlay_result.png",
        grid_step_mm: int = 5000,
        ctx: Context = None
    ):  # no return annotation: FastMCP cannot build a schema for Union[Image, str]
        """
        Lay toan bo cau kien vua dung tren tang `level_name` tu Revit, ve chong (Overlay)
        len trang ban ve PDF goc kem luoi toa do (X, Y) va ElementId, tra ve anh MCPImage
        de Vision LLM tu dong nhin thay va kiem tra cheo (Visual QA Loop).
        Nen truyen lai dung bo 4 toa do Grid moc (muc 'calibration' trong ket qua parse); neu
        bo trong, tool tu dong khop luoi truc lai tu PDF + Revit.
        """
        if generate_qa_overlay_image is None or AffineTransformer is None:
            return "Error: Module visual_qa_overlay hoac pdf_struct_parser chua duoc nap."

        path = find_project_pdf(pdf_path)
        if not path:
            return f"Error: Khong tim thay file PDF ('{pdf_path or DEFAULT_PDF_NAMES[0]}'). Hay cho biet duong dan."
        pdf_path = path

        try:
            (pdf_grid_pt1, pdf_grid_pt2, revit_grid_pt1_mm, revit_grid_pt2_mm), _cal = await resolve_calibration(
                revit_post, pdf_path, page_number,
                (pdf_grid_pt1, pdf_grid_pt2, revit_grid_pt1_mm, revit_grid_pt2_mm), ctx, level_name=level_name)
        except Exception as e:
            return f"Error: {str(e)}"


        # Truy vấn hình học thực tế từ Revit
        query_code = f"""
import clr, json
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document
level_name = {json.dumps(level_name)}

def ft_to_mm(ft_val):
    return round(ft_val * 304.8, 1)

elements_data = {{"columns": [], "beams": [], "walls": [], "slabs": []}}

# 1. Cột (Columns)
for col in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType():
    lvl_p = col.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM)
    lvl_elem = doc.GetElement(lvl_p.AsElementId()) if (lvl_p and lvl_p.AsElementId() != ElementId.InvalidElementId) else None
    if not lvl_elem and col.LevelId != ElementId.InvalidElementId:
        lvl_elem = doc.GetElement(col.LevelId)
    if lvl_elem and (lvl_elem.Name == level_name or level_name.lower() in lvl_elem.Name.lower()):
        loc = col.Location
        if isinstance(loc, LocationPoint):
            pt = loc.Point
            sym = col.Symbol
            b_p = sym.LookupParameter("b") or sym.LookupParameter("Width") or sym.LookupParameter("bf")
            h_p = sym.LookupParameter("h") or sym.LookupParameter("Depth") or sym.LookupParameter("d")
            b_mm = ft_to_mm(b_p.AsDouble()) if b_p else 500.0
            h_mm = ft_to_mm(h_p.AsDouble()) if h_p else 500.0
            eid_val = int(col.Id.ToString()) if hasattr(col.Id, 'ToString') else int(col.Id.IntegerValue)
            elements_data["columns"].append({{"id": eid_val, "x": ft_to_mm(pt.X), "y": ft_to_mm(pt.Y), "b_mm": b_mm, "h_mm": h_mm}})

# 2. Dầm (Beams)
for beam in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType():
    lvl_p = beam.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
    lvl_elem = doc.GetElement(lvl_p.AsElementId()) if (lvl_p and lvl_p.AsElementId() != ElementId.InvalidElementId) else None
    if not lvl_elem and beam.LevelId != ElementId.InvalidElementId:
        lvl_elem = doc.GetElement(beam.LevelId)
    if lvl_elem and (lvl_elem.Name == level_name or level_name.lower() in lvl_elem.Name.lower()):
        loc = beam.Location
        if isinstance(loc, LocationCurve):
            crv = loc.Curve
            p1, p2 = crv.GetEndPoint(0), crv.GetEndPoint(1)
            sym = beam.Symbol
            b_p = sym.LookupParameter("b") or sym.LookupParameter("Width") or sym.LookupParameter("bf")
            b_mm = ft_to_mm(b_p.AsDouble()) if b_p else 300.0
            eid_val = int(beam.Id.ToString()) if hasattr(beam.Id, 'ToString') else int(beam.Id.IntegerValue)
            elements_data["beams"].append({{"id": eid_val, "start": {{"x": ft_to_mm(p1.X), "y": ft_to_mm(p1.Y)}}, "end": {{"x": ft_to_mm(p2.X), "y": ft_to_mm(p2.Y)}}, "b_mm": b_mm}})

# 3. Vách (Walls)
for wall in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType():
    lvl_p = wall.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT)
    lvl_elem = doc.GetElement(lvl_p.AsElementId()) if (lvl_p and lvl_p.AsElementId() != ElementId.InvalidElementId) else None
    if not lvl_elem and wall.LevelId != ElementId.InvalidElementId:
        lvl_elem = doc.GetElement(wall.LevelId)
    if lvl_elem and (lvl_elem.Name == level_name or level_name.lower() in lvl_elem.Name.lower()):
        loc = wall.Location
        if isinstance(loc, LocationCurve):
            crv = loc.Curve
            p1, p2 = crv.GetEndPoint(0), crv.GetEndPoint(1)
            eid_val = int(wall.Id.ToString()) if hasattr(wall.Id, 'ToString') else int(wall.Id.IntegerValue)
            elements_data["walls"].append({{"id": eid_val, "start": {{"x": ft_to_mm(p1.X), "y": ft_to_mm(p1.Y)}}, "end": {{"x": ft_to_mm(p2.X), "y": ft_to_mm(p2.Y)}}, "thickness_mm": ft_to_mm(wall.Width)}})

print(json.dumps(elements_data))
"""
        if ctx:
            await ctx.info(f"Đang truy vấn hình học cấu kiện trên tầng {level_name}...")
        try:
            revit_elements = await run_revit_json(revit_post, query_code, "Query Level Geometry", ctx)
        except Exception as e:
            return f"Error khi đọc dữ liệu Revit: {str(e)}"

        p_pt1 = pdf_grid_pt1
        p_pt2 = pdf_grid_pt2
        r_pt1 = revit_grid_pt1_mm
        r_pt2 = revit_grid_pt2_mm

        transformer = AffineTransformer(tuple(p_pt1), tuple(p_pt2), tuple(r_pt1), tuple(r_pt2))
        
        # Duong dan tuong doi -> thu muc lam viec (khong phu thuoc cwd cua server, khong ra Desktop)
        abs_output = output_png_path if os.path.isabs(output_png_path) else work_path("qa", output_png_path)
        if ctx:
            await ctx.info(f"Đang kết xuất ảnh Overlay với lưới tọa độ milimet ra '{abs_output}'...")

        res = generate_qa_overlay_image(
            pdf_path=pdf_path,
            page_num=page_number - 1,
            transformer=transformer,
            revit_elements=revit_elements,
            output_img_path=abs_output,
            grid_step_mm=grid_step_mm
        )
        if ctx:
            summary = res.get("summary", {})
            await ctx.info(
                f"Visual QA Overlay hoàn tất: Cột={summary.get('rendered_columns', 0)}, "
                f"Dầm={summary.get('rendered_beams', 0)}, Vách={summary.get('rendered_walls', 0)}. "
                f"Đã lưu tại '{abs_output}'."
            )
        return MCPImage(path=abs_output)

    @mcp.tool()
    async def modify_or_delete_elements(
        delete_ids: Optional[List[int]] = None,
        move_vectors_mm: Optional[List[Dict[str, Any]]] = None,
        ctx: Context = None
    ) -> str:
        """
        Tool tự sửa lỗi sau khi chạy Visual QA:
        - delete_ids: Danh sách ElementId bị dựng nhầm/dư cần xóa bỏ (ví dụ: [123456, 123457]).
        - move_vectors_mm: Danh sách dịch chuyển [{"id": 123456, "dx_mm": 0.0, "dy_mm": 150.0}] để căn chỉnh dầm bị lệch.
        """
        revit_code = f"""
import clr, json
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document
delete_ids = {json.dumps(delete_ids or [])}
moves = {json.dumps(move_vectors_mm or [])}

deleted_count = 0
moved_count = 0

{FAILURE_SWALLOWER_CODE}

t = Transaction(doc, "MCP: Visual QA Self-Correction")
attach_failure_swallower(t)
t.Start()
try:
    # 1. Xóa các đối tượng bị nhầm
    for eid in delete_ids:
        try:
            doc.Delete(ElementId(int(eid)))
            deleted_count += 1
        except Exception:
            pass

    # 2. Dịch chuyển các đối tượng bị lệch
    for m in moves:
        try:
            elem_id = ElementId(int(m["id"]))
            elem = doc.GetElement(elem_id)
            if elem:
                dx_ft = m.get("dx_mm", 0.0) / 304.8
                dy_ft = m.get("dy_mm", 0.0) / 304.8
                if abs(dx_ft) > 0.0001 or abs(dy_ft) > 0.0001:
                    ElementTransformUtils.MoveElement(doc, elem_id, XYZ(dx_ft, dy_ft, 0))
                    moved_count += 1
        except Exception:
            pass

    t.Commit()
    print(json.dumps({{
        "status": "success",
        "deleted_count": deleted_count,
        "moved_count": moved_count
    }}))
except Exception as ex:
    t.RollBack()
    print(json.dumps({{"status": "error", "message": str(ex)}}))
"""
        payload = {"code": revit_code, "description": "Visual QA Self-Healing Fix"}
        if ctx:
            await ctx.info(f"Đang sửa lỗi: Xóa {len(delete_ids or [])} phần tử, dịch chuyển {len(move_vectors_mm or [])} phần tử...")
        response = await revit_post("/execute_code/", payload, ctx, timeout=60.0)
        return format_response(response)

    @mcp.tool()
    async def finalize_and_join_structure(
        level_name: str,
        ctx: Context = None
    ) -> str:
        """
        Tự động xử lý Join Geometry toàn bộ Cột - Vách - Dầm chính - Dầm phụ - Sàn
        trên tầng `level_name` theo đúng thứ tự ưu tiên kết cấu (Cột/Vách cắt Dầm/Sàn,
        Dầm chính cắt Dầm phụ, Dầm cắt Sàn), triệt tiêu Cutback đầu dầm về 0.0, và dọn sạch
        các cảnh báo (Warnings) phát sinh trong Revit.
        """
        revit_code = f"""
import clr, json
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

doc = __revit__.ActiveUIDocument.Document
level_name = {json.dumps(level_name)}

{FAILURE_SWALLOWER_CODE}

def ensure_join_and_order(doc, cutting_elem, cut_elem):
    try:
        are_joined = JoinGeometryUtils.AreElementsJoined(doc, cutting_elem, cut_elem)
        if not are_joined:
            JoinGeometryUtils.JoinGeometry(doc, cutting_elem, cut_elem)
            are_joined = True

        if are_joined:
            if not JoinGeometryUtils.IsCuttingElementInJoin(doc, cutting_elem, cut_elem):
                JoinGeometryUtils.SwitchJoinOrder(doc, cutting_elem, cut_elem)
                return "switched"
            return "joined"
    except Exception:
        pass
    return "failed"

def get_beam_volume_rank(beam):
    sym = beam.Symbol
    if not sym:
        return 0.0
    b_p = sym.LookupParameter("b") or sym.LookupParameter("Width") or sym.LookupParameter("bf")
    h_p = sym.LookupParameter("h") or sym.LookupParameter("Depth") or sym.LookupParameter("d")
    b = b_p.AsDouble() if b_p else 1.0
    h = h_p.AsDouble() if h_p else 2.0
    return round(h * 100.0 + b * 10.0, 3)

def find_intersecting_elements(doc, target_elem, category_bic, tolerance_ft=0.05):
    bbox = target_elem.get_BoundingBox(None)
    if not bbox:
        return []
    tol = XYZ(tolerance_ft, tolerance_ft, tolerance_ft)
    outline = Outline(bbox.Min - tol, bbox.Max + tol)
    bb_filter = BoundingBoxIntersectsFilter(outline)
    return list(
        FilteredElementCollector(doc)
        .OfCategory(category_bic)
        .WhereElementIsNotElementType()
        .WherePasses(bb_filter)
        .ToElements()
    )

stats = {{
    "col_wall_cut_beam": 0,
    "col_wall_cut_slab": 0,
    "beam_cut_slab": 0,
    "main_beam_cut_sec_beam": 0,
    "cutback_zeroed": 0,
    "unjoined_disconnected_warnings": 0
}}

beams_on_level = []
for b in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType():
    lvl_p = b.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
    lvl_elem = doc.GetElement(lvl_p.AsElementId()) if (lvl_p and lvl_p.AsElementId() != ElementId.InvalidElementId) else None
    if not lvl_elem and b.LevelId != ElementId.InvalidElementId:
        lvl_elem = doc.GetElement(b.LevelId)
    if lvl_elem and (lvl_elem.Name == level_name or level_name.lower() in lvl_elem.Name.lower()):
        beams_on_level.append(b)

slabs_on_level = []
for fl in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType():
    lvl_p = fl.get_Parameter(BuiltInParameter.LEVEL_PARAM)
    lvl_elem = doc.GetElement(lvl_p.AsElementId()) if (lvl_p and lvl_p.AsElementId() != ElementId.InvalidElementId) else None
    if not lvl_elem and fl.LevelId != ElementId.InvalidElementId:
        lvl_elem = doc.GetElement(fl.LevelId)
    if lvl_elem and (lvl_elem.Name == level_name or level_name.lower() in lvl_elem.Name.lower()):
        slabs_on_level.append(fl)

t = Transaction(doc, "MCP: Auto-Join Structure & Fix Warnings")
attach_failure_swallower(t)
t.Start()

try:
    # Bước A: Khử Cutback ở 2 đầu dầm bê tông để không bị hở mép Cột
    for beam in beams_on_level:
        for bip in [BuiltInParameter.START_JOIN_CUTBACK, BuiltInParameter.END_JOIN_CUTBACK]:
            p_cb = beam.get_Parameter(bip)
            if p_cb and not p_cb.IsReadOnly and p_cb.AsDouble() > 0:
                p_cb.Set(0.0)
                stats["cutback_zeroed"] += 1

    doc.Regenerate()

    # Bước B: Xử lý Join cho từng Dầm
    processed_beam_pairs = set()

    for beam in beams_on_level:
        beam_id = beam.Id.IntegerValue if hasattr(beam.Id, 'IntegerValue') else int(beam.Id.ToString())

        # 1. Cột cắt Dầm
        cols = find_intersecting_elements(doc, beam, BuiltInCategory.OST_StructuralColumns)
        for col in cols:
            res = ensure_join_and_order(doc, cutting_elem=col, cut_elem=beam)
            if res in ("joined", "switched"):
                stats["col_wall_cut_beam"] += 1

        # 2. Vách cứng cắt Dầm
        walls = find_intersecting_elements(doc, beam, BuiltInCategory.OST_Walls)
        for wall in walls:
            res = ensure_join_and_order(doc, cutting_elem=wall, cut_elem=beam)
            if res in ("joined", "switched"):
                stats["col_wall_cut_beam"] += 1

        # 3. Dầm chính cắt Dầm phụ
        other_beams = find_intersecting_elements(doc, beam, BuiltInCategory.OST_StructuralFraming)
        for ob in other_beams:
            ob_id = ob.Id.IntegerValue if hasattr(ob.Id, 'IntegerValue') else int(ob.Id.ToString())
            if ob_id == beam_id:
                continue
            pair_key = (min(beam_id, ob_id), max(beam_id, ob_id))
            if pair_key in processed_beam_pairs:
                continue
            processed_beam_pairs.add(pair_key)

            if get_beam_volume_rank(beam) >= get_beam_volume_rank(ob):
                res = ensure_join_and_order(doc, cutting_elem=beam, cut_elem=ob)
            else:
                res = ensure_join_and_order(doc, cutting_elem=ob, cut_elem=beam)
            
            if res in ("joined", "switched"):
                stats["main_beam_cut_sec_beam"] += 1

    # Bước C: Xử lý Join cho Sàn
    for slab in slabs_on_level:
        for col in find_intersecting_elements(doc, slab, BuiltInCategory.OST_StructuralColumns):
            if ensure_join_and_order(doc, cutting_elem=col, cut_elem=slab) in ("joined", "switched"):
                stats["col_wall_cut_slab"] += 1

        for wall in find_intersecting_elements(doc, slab, BuiltInCategory.OST_Walls):
            if ensure_join_and_order(doc, cutting_elem=wall, cut_elem=slab) in ("joined", "switched"):
                stats["col_wall_cut_slab"] += 1

        for beam in find_intersecting_elements(doc, slab, BuiltInCategory.OST_StructuralFraming):
            if ensure_join_and_order(doc, cutting_elem=beam, cut_elem=slab) in ("joined", "switched"):
                stats["beam_cut_slab"] += 1

    # Bước D: Dọn dẹp cảnh báo "joined but do not intersect"
    for failure_msg in doc.GetWarnings():
        desc = failure_msg.GetDescriptionText().lower()
        if "joined but do not intersect" in desc:
            failing_ids = list(failure_msg.GetFailingElements())
            if len(failing_ids) == 2:
                e1 = doc.GetElement(failing_ids[0])
                e2 = doc.GetElement(failing_ids[1])
                if e1 and e2 and JoinGeometryUtils.AreElementsJoined(doc, e1, e2):
                    JoinGeometryUtils.UnjoinGeometry(doc, e1, e2)
                    stats["unjoined_disconnected_warnings"] += 1

    t.Commit()
    print(json.dumps({{
        "status": "success",
        "level": level_name,
        "join_summary": stats
    }}))
except Exception as ex:
    t.RollBack()
    print(json.dumps({{"status": "error", "message": str(ex)}}))
"""
        payload = {"code": revit_code, "description": f"Auto-Join Structure & Fix Warnings for {level_name}"}
        if ctx:
            await ctx.info(f"Đang thực hiện hậu xử lý: Ép thứ tự Join, khử Cutback và dọn Warnings cho level {level_name}...")
        response = await revit_post("/execute_code/", payload, ctx, timeout=180.0)
        return format_response(response)
