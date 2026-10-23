#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pdf_struct_parser.py - Bóc tách Hình học & Thuộc tính Kết cấu từ Vector PDF
Hỗ trợ: Cột (Columns), Dầm (Beams), Vách (Walls), Móng (Footings)
Thuật toán:
  1. AffineTransformer (Khớp hệ tọa độ PDF pt -> Revit mm qua 2 giao điểm Grid).
  2. Rectangle Detection (Nhận diện hình chữ nhật cột).
  3. Parallel Lines Centerline Detection (Tìm đường tâm dầm/vách từ cặp nét đôi song song).
  4. Beam-to-Column Node Snapping (Bắt dính đầu mút dầm vào tâm cột).
  5. Schedule Mapping (Liên kết mã hiệu B1, C1, W1, PF1 với bảng thống kê tiết diện).
"""

import sys
import os
import math
import re
from typing import List, Dict, Tuple, Optional
import fitz  # PyMuPDF

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from beam_topology_snapper import extend_and_snap_structural_beams
    from slab_and_opening_parser import detect_x_mark_openings, extract_slab_boundaries_and_openings
except ImportError:
    from .beam_topology_snapper import extend_and_snap_structural_beams
    from .slab_and_opening_parser import detect_x_mark_openings, extract_slab_boundaries_and_openings


class AffineTransformer:
    """Quy đổi tọa độ từ trang PDF (pt) sang tọa độ Revit (mm) dựa trên 2 giao điểm Grid mốc."""
    def __init__(self, pdf_pt1: Tuple[float, float], pdf_pt2: Tuple[float, float],
                 rvt_pt1: Tuple[float, float], rvt_pt2: Tuple[float, float]):
        # Trục Y của PDF hướng xuống, trục Y của Revit hướng lên -> Đảo dấu Y của PDF
        p1 = (pdf_pt1[0], -pdf_pt1[1])
        p2 = (pdf_pt2[0], -pdf_pt2[1])
        
        dx_pdf, dy_pdf = p2[0] - p1[0], p2[1] - p1[1]
        dx_rvt, dy_rvt = rvt_pt2[0] - rvt_pt1[0], rvt_pt2[1] - rvt_pt1[1]
        
        dist_pdf = math.hypot(dx_pdf, dy_pdf)
        dist_rvt = math.hypot(dx_rvt, dy_rvt)
        self.scale = dist_rvt / dist_pdf if dist_pdf > 0 else 1.0
        
        angle_pdf = math.atan2(dy_pdf, dx_pdf)
        angle_rvt = math.atan2(dy_rvt, dx_rvt)
        self.theta = angle_rvt - angle_pdf
        
        self.cos_t = math.cos(self.theta)
        self.sin_t = math.sin(self.theta)
        
        self.tx = rvt_pt1[0] - self.scale * (p1[0] * self.cos_t - p1[1] * self.sin_t)
        self.ty = rvt_pt1[1] - self.scale * (p1[0] * self.sin_t + p1[1] * self.cos_t)

    def to_revit_mm(self, x_pdf: float, y_pdf: float) -> Dict[str, float]:
        px, py = x_pdf, -y_pdf
        rx = self.scale * (px * self.cos_t - py * self.sin_t) + self.tx
        ry = self.scale * (px * self.sin_t + py * self.cos_t) + self.ty
        return {"x": round(rx, 1), "y": round(ry, 1)}

    def to_pdf_pt(self, x_rvt: float, y_rvt: float) -> Dict[str, float]:
        dx = x_rvt - self.tx
        dy = y_rvt - self.ty
        px = (dx * self.cos_t + dy * self.sin_t) / self.scale
        py = (-dx * self.sin_t + dy * self.cos_t) / self.scale
        return {"x": round(px, 2), "y": round(-py, 2)}


def parse_structural_tag(text: str) -> Dict:
    """
    Dùng Regex giải mã ghi chú kết cấu phổ biến, tương thích nhiều quy ước ký hiệu
    của các hãng thiết kế khác nhau (không chỉ 1 dự án cụ thể):
    Ví dụ: '2B12 (300x650) (-0.050)', 'C1 600x600', 'W1 200', 'PF2 4800x4300x800D',
           'SF1 450Wx300D' (quy ước W=Width/D=Depth kiểu Úc), 'CC01 450D' (cột tròn đường kính).
    """
    clean_txt = text.strip()

    # 1. Bắt kích thước L x W x D hoặc b x h x d, cho phép hậu tố chữ cái tùy chọn
    #    ngay sau mỗi số (VD: 300x600, 4800x4300x800D, 450Wx300D, 2100x1300x500D).
    dim3_match = re.search(
        r'(\d{2,5})\s*[a-zA-Z]{0,3}\s*[xX\*]\s*(\d{2,5})\s*[a-zA-Z]{0,3}\s*[xX\*]\s*(\d{2,5})\s*[a-zA-Z]{0,3}',
        clean_txt
    )
    dim2_match = re.search(
        r'(\d{2,5})\s*[a-zA-Z]{0,3}\s*[xX\*]\s*(\d{2,5})\s*[a-zA-Z]{0,3}',
        clean_txt
    )
    # 1b. Bắt tiết diện tròn: '450D', '450DIA', 'Ø450', 'D450' (cột/cọc tròn chỉ có 1 trị số)
    dia_match = re.search(r'(?:[ØøΦφ]\s*|D\s*=?\s*)(\d{2,4})\b|\b(\d{2,4})\s*(?:DIA\b|D\b|Ø)', clean_txt)

    width = None
    depth = None
    thickness = None

    if dim3_match:
        width = int(dim3_match.group(1))
        depth = int(dim3_match.group(2))
        thickness = int(dim3_match.group(3))
    elif dim2_match:
        width = int(dim2_match.group(1))
        depth = int(dim2_match.group(2))
    elif dia_match:
        diam = int(dia_match.group(1) or dia_match.group(2))
        width = diam
        depth = diam
        
    # 2. Bắt cao độ âm/dương trong ngoặc: (-0.050) hoặc (+150)
    elev_match = re.search(r'\(([+-]?\d+(?:\.\d+)?)\)', clean_txt)
    z_offset_mm = 0.0
    if elev_match:
        val = float(elev_match.group(1))
        # Nếu ghi dạng mét (-0.050) -> đổi ra mm (-50)
        z_offset_mm = val * 1000.0 if abs(val) < 10 else val

    # 3. Bắt mã hiệu cấu kiện (Mark): B1, C2, W1, PF3, SF1
    mark_match = re.search(r'\b([A-Z]{1,3}\d{1,3}[A-Z]?)\b', clean_txt)
    mark = mark_match.group(1) if mark_match else ""

    return {
        "raw_text": clean_txt,
        "mark": mark,
        "b_mm": width,
        "h_mm": depth,
        "d_mm": thickness,
        "z_offset_mm": z_offset_mm
    }


def parse_schedule_tables(page: fitz.Page) -> Dict[str, Dict]:
    """
    Quét toàn bộ text trên trang để nhận diện các bảng thống kê kết cấu (Schedules):
    - Beam Schedule: B1, B2 -> b, h
    - Column Schedule: C1, C2 -> b, h hoặc Dia
    - Footing Schedule: PF1, PF2 -> L, W, D
    - Wall Schedule: W1, SW1, LW1 -> Thickness
    """
    text = page.get_text()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    catalog = {}
    
    for i, line in enumerate(lines):
        # Mẫu 1: Dòng chứa Mã hiệu và Kích thước liền kề (VD: 'PF2' dòng trên, '4800x4300x800D' dòng dưới)
        tag_info = parse_structural_tag(line)
        if tag_info["mark"] and tag_info["b_mm"]:
            catalog[tag_info["mark"]] = tag_info
        elif tag_info["mark"] and i + 1 < len(lines):
            next_tag = parse_structural_tag(lines[i+1])
            if next_tag["b_mm"]:
                merged = {
                    "raw_text": f"{line} {lines[i+1]}",
                    "mark": tag_info["mark"],
                    "b_mm": next_tag["b_mm"],
                    "h_mm": next_tag["h_mm"],
                    "d_mm": next_tag["d_mm"],
                    "z_offset_mm": next_tag["z_offset_mm"]
                }
                catalog[tag_info["mark"]] = merged

    return catalog


def snap_beams_to_columns(beams: List[Dict], columns: List[Dict], snap_radius_mm: float = 800.0) -> List[Dict]:
    """
    Beam-to-Column Node Snapping & Quy tắc Xử lý Dầm lệch tâm:
    1. Dầm lệch tâm (Eccentric Beams / Flush with Column Edge):
       Đường tâm (Centerline) bóc tách từ cặp nét đôi trên PDF đã nằm đúng ở tâm thực tế của tiết diện dầm.
       Hàm này mở rộng đầu mút dầm tới trục cột dọc theo phương của dầm mà KHÔNG làm nghiêng dầm (bảo toàn tâm thực tế).
    2. Nối dài đường tâm dầm vào tâm cột (Node Snapping):
       Khắc phục hiện tượng nét vẽ dầm bị cắt cụt tại mép cột trên PDF 2D, kéo dài đầu mút vào đúng tim cột
       để bảo đảm mô hình phân tích lực (Analytical Model) liên tục và Revit Join Geometry sạch sẽ.
    """
    for b in beams:
        s_pt = b["start_mm"]
        e_pt = b["end_mm"]
        
        dx = e_pt["x"] - s_pt["x"]
        dy = e_pt["y"] - s_pt["y"]
        beam_len = math.hypot(dx, dy)
        if beam_len < 100:
            continue
            
        ux = dx / beam_len
        uy = dy / beam_len
        
        is_horizontal = abs(uy) < 0.15
        is_vertical = abs(ux) < 0.15

        # 1. Snap Start Point
        for col in columns:
            cx, cy = col["center"]["x"], col["center"]["y"]
            cw = col.get("b_mm", 500)
            ch = col.get("h_mm", 500)
            
            # Khoảng cách từ điểm start đến tâm cột
            d_start = math.hypot(s_pt["x"] - cx, s_pt["y"] - cy)
            if d_start <= snap_radius_mm:
                # Kiểm tra dầm nằm ngang: chỉ kéo dài tọa độ X tới cx, giữ nguyên Y để bảo toàn độ lệch tâm
                if is_horizontal and abs(s_pt["y"] - cy) <= (ch / 2.0 + 150):
                    b["start_mm"]["x"] = cx
                    b["snapped_start_col"] = col.get("mark", "Col")
                    break
                # Kiểm tra dầm thẳng đứng: chỉ kéo dài tọa độ Y tới cy, giữ nguyên X để bảo toàn độ lệch tâm
                elif is_vertical and abs(s_pt["x"] - cx) <= (cw / 2.0 + 150):
                    b["start_mm"]["y"] = cy
                    b["snapped_start_col"] = col.get("mark", "Col")
                    break
                # Dầm xiên hoặc gần tim: bắt dính trực tiếp vào tâm cột
                elif d_start <= (max(cw, ch) / 2.0 + 200):
                    b["start_mm"] = {"x": cx, "y": cy}
                    b["snapped_start_col"] = col.get("mark", "Col")
                    break

        # 2. Snap End Point
        for col in columns:
            cx, cy = col["center"]["x"], col["center"]["y"]
            cw = col.get("b_mm", 500)
            ch = col.get("h_mm", 500)
            
            d_end = math.hypot(e_pt["x"] - cx, e_pt["y"] - cy)
            if d_end <= snap_radius_mm:
                if is_horizontal and abs(e_pt["y"] - cy) <= (ch / 2.0 + 150):
                    b["end_mm"]["x"] = cx
                    b["snapped_end_col"] = col.get("mark", "Col")
                    break
                elif is_vertical and abs(e_pt["x"] - cx) <= (cw / 2.0 + 150):
                    b["end_mm"]["y"] = cy
                    b["snapped_end_col"] = col.get("mark", "Col")
                    break
                elif d_end <= (max(cw, ch) / 2.0 + 200):
                    b["end_mm"] = {"x": cx, "y": cy}
                    b["snapped_end_col"] = col.get("mark", "Col")
                    break
                    
    return beams


_BEAM_MARK_RE = re.compile(r"^[A-Z]{0,2}B\d{1,3}[A-Z]?$")


def is_beam_tag(parsed: Dict) -> bool:
    """Ghi chú dầm hợp lệ: mã dầm (B1, GB2, TB1, RB3) hoặc tiết diện 2 số 'b x h' không kèm mã khác."""
    mark = parsed.get("mark") or ""
    if _BEAM_MARK_RE.match(mark):
        return True
    return bool(parsed.get("b_mm") and parsed.get("h_mm") and not parsed.get("d_mm") and not mark)


def snap_section_mm(v: float, step: float = 25.0, tol_ratio: float = 0.02, tol_min: float = 6.0) -> int:
    """Làm tròn kích thước đo từ nét vẽ (301, 298, 294...) về bội số 25 mm khi chênh lệch nhỏ."""
    r = round(v / step) * step
    return int(r) if abs(v - r) <= max(tol_min, tol_ratio * v) else int(round(v))


def column_to_revit(feat: Dict, transformer: AffineTransformer) -> Dict:
    """
    Quy đổi cột PDF sang Revit: b_mm/h_mm là kích thước theo phương X/Y của Revit (trang bị xoay
    90°/270° thì đổi chỗ), rotation_deg là phần góc lẻ còn lại ngoài bội số 90°.
    """
    c = transformer.to_revit_mm(feat["x"], feat["y"])
    # angle_deg: cột vẽ xoay trên trang (hệ trang Y xuống) -> góc trong Revit = theta - angle_deg
    deg = math.degrees(transformer.theta) - float(feat.get("angle_deg") or 0.0)
    k = int(round(deg / 90.0))
    rest = round(deg - 90.0 * k, 3)
    if feat.get("angle_deg") is not None:
        # góc đo từ nét vẽ có sai số nhỏ -> bám về trục Revit (0°) hoặc hướng chính của trang khi lệch < 0.5°
        t_deg = math.degrees(transformer.theta)
        t_rest = round(t_deg - 90.0 * round(t_deg / 90.0), 3)
        for cand in (0.0, t_rest):
            if abs(rest - cand) < 0.5:
                rest = cand
                break
    bx, hy = feat["b_mm"], feat["h_mm"]
    if k % 2:
        bx, hy = hy, bx
    out = {"center": {"x": round(c["x"], 1), "y": round(c["y"], 1)},
           "b_mm": snap_section_mm(bx), "h_mm": snap_section_mm(hy), "mark": feat["mark"],
           "shape": "round" if feat["kind"] == "circle" else "rect"}
    if feat["kind"] == "circle":
        out["diameter_mm"] = snap_section_mm(bx)
        out["b_mm"] = out["h_mm"] = out["diameter_mm"]
    if abs(rest) > 1e-6:
        out["rotation_deg"] = rest
    return out


def extract_structural_pdf(pdf_path: str, page_num: int, transformer: AffineTransformer,
                           include_slabs: bool = True, default_slab_thickness_mm: int = 150,
                           drawing_area_bbox: Optional[Tuple[float, float, float, float]] = None,
                           drawing_area_pt: Optional[Tuple[float, float, float, float]] = None,
                           require_beam_tag: bool = True) -> Dict:
    """
    Trích xuất Cột, Dầm (và Sàn) từ trang PDF Vector sang tọa độ Revit mm.
    include_slabs: chạy tiếp Phase 4 (lỗ mở chữ X + đa giác hóa ô sàn từ mạng dầm đã snap).
    drawing_area_pt: khung mặt bằng (point PDF) - bỏ qua chú thích, bảng thống kê, khung tên.
    require_beam_tag: chỉ nhận cặp nét đôi có ghi chú dầm (B1, GB2, 300x600) - loại tường, khe co
      giãn, mép móng. Trang sàn trên nền đất (S.O.G) không có ghi chú dầm -> 0 dầm.
    """
    from column_calibration import extract_pdf_column_features, PT_TO_MM  # tránh import vòng

    def in_area(x, y):
        a = drawing_area_pt
        return a is None or (a[0] <= x <= a[2] and a[1] <= y <= a[3])

    doc = fitz.open(pdf_path)
    page = doc[page_num]
    drawings = page.get_drawings()

    # Bóc tách bảng thống kê nếu có (bảng nằm NGOÀI khung mặt bằng nên quét cả trang)
    schedule_catalog = parse_schedule_tables(page)
    page_text = page.get_text().upper()
    slab_on_ground = "S.O.G" in page_text or "SLAB ON GROUND" in page_text

    # 1. Trích xuất Text & Tọa độ tâm Text (trong khung mặt bằng)
    texts = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip()
                if not txt:
                    continue
                bbox = span["bbox"]
                cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                if not in_area(cx, cy):
                    continue
                rvt_pt = transformer.to_revit_mm(cx, cy)
                texts.append({
                    "text": txt,
                    "x": rvt_pt["x"],
                    "y": rvt_pt["y"],
                    "parsed": parse_structural_tag(txt)
                })

    # 2. Cột: hình chữ nhật / tròn CÓ mã cột ở gần (bỏ ô bảng, chú thích, đoạn tường không mã)
    scale = transformer.scale / PT_TO_MM
    feats = extract_pdf_column_features(page, scale, drawings, area_pt=drawing_area_pt)
    columns = [column_to_revit(f, transformer) for f in feats]

    # Thu thập các đoạn thẳng (Lines) để nhận diện Dầm
    lines = []
    for path in drawings:
        for item in path.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if not (in_area(p1.x, p1.y) and in_area(p2.x, p2.y)):
                    continue
                rp1 = transformer.to_revit_mm(p1.x, p1.y)
                rp2 = transformer.to_revit_mm(p2.x, p2.y)
                length = math.hypot(rp2["x"] - rp1["x"], rp2["y"] - rp1["y"])
                if length >= 400:  # Lấy nét dài >= 400mm
                    lines.append((rp1, rp2, length))

    # 3. Thuật toán tìm cặp nét đôi song song (Parallel Line Pair -> Centerline)
    beams = []
    used_indices = set()
    skipped_untagged = 0
    
    for i in range(len(lines)):
        if i in used_indices:
            continue
        p1, p2, len1 = lines[i]
        dx1, dy1 = p2["x"] - p1["x"], p2["y"] - p1["y"]
        angle1 = math.atan2(dy1, dx1)
        
        for j in range(i + 1, len(lines)):
            if j in used_indices:
                continue
            q1, q2, len2 = lines[j]
            dx2, dy2 = q2["x"] - q1["x"], q2["y"] - q1["y"]
            angle2 = math.atan2(dy2, dx2)
            
            # Kiểm tra song song (sai số góc < 1 độ ~ 0.017 rad)
            if abs(math.sin(angle1 - angle2)) < 0.017:
                # Tính khoảng cách vuông góc giữa 2 nét
                dist = abs((q1["x"] - p1["x"]) * (-dy1) + (q1["y"] - p1["y"]) * dx1) / len1
                width_mm = round(dist, -1)
                
                # Bề rộng dầm / vách kết cấu chuẩn (150mm - 1200mm)
                if 150 <= width_mm <= 1200 and abs(len1 - len2) < 1500:
                    # Nội suy đường tâm thực tế (Centerline)
                    start_mid = {"x": round((p1["x"] + q1["x"]) / 2, 1), "y": round((p1["y"] + q1["y"]) / 2, 1)}
                    end_mid = {"x": round((p2["x"] + q2["x"]) / 2, 1), "y": round((p2["y"] + q2["y"]) / 2, 1)}
                    mid_pt = {"x": (start_mid["x"] + end_mid["x"]) / 2, "y": (start_mid["y"] + end_mid["y"]) / 2}
                    
                    # Tìm ghi chú dầm gần nhất (bán kính < 1500mm): mã dầm hoặc 'b x h'
                    matched_tag = None
                    min_tdist = 1500.0
                    for t in texts:
                        tdist = math.hypot(t["x"] - mid_pt["x"], t["y"] - mid_pt["y"])
                        if tdist < min_tdist and is_beam_tag(t["parsed"]):
                            min_tdist = tdist
                            matched_tag = t["parsed"]
                    if require_beam_tag and matched_tag is None:
                        skipped_untagged += 1
                        continue  # nét đôi không có ghi chú dầm: tường, khe co giãn, mép móng...
                    used_indices.add(i)
                    used_indices.add(j)

                    # Tra cứu kích thước từ Schedule Catalog nếu text chỉ có tên (ví dụ: 'B2')
                    b_final = int(width_mm)
                    h_final = 600
                    z_offset = 0.0
                    mark_final = "Beam"
                    
                    if matched_tag:
                        mark_final = matched_tag["raw_text"]
                        if matched_tag["b_mm"]:
                            b_final = matched_tag["b_mm"]
                            h_final = matched_tag["h_mm"] if matched_tag["h_mm"] else 600
                        elif matched_tag["mark"] in schedule_catalog:
                            cat = schedule_catalog[matched_tag["mark"]]
                            b_final = cat.get("b_mm", b_final)
                            h_final = cat.get("h_mm", 600)
                        z_offset = matched_tag.get("z_offset_mm", 0.0)
                    
                    beams.append({
                        "start_mm": start_mid,
                        "end_mm": end_mid,
                        "b_mm": b_final,
                        "h_mm": h_final,
                        "z_offset_mm": z_offset,
                        "mark": mark_final
                    })
                    break

    # 4. Hậu xử lý: Chuẩn hóa Tô-pô & Bắt dính Dầm (Node Snapping & Collinear Merge)
    beams = extend_and_snap_structural_beams(beams, columns, merge_broken_segments=True, max_extend_mm=600.0)

    # 5. Phase 4: Lỗ mở chữ X & Sàn kết cấu (Polygonize mạng dầm đã snap)
    if drawing_area_bbox is None and drawing_area_pt is not None:
        a = drawing_area_pt
        corners = [transformer.to_revit_mm(x, y) for x in (a[0], a[2]) for y in (a[1], a[3])]
        drawing_area_bbox = (min(c["x"] for c in corners), min(c["y"] for c in corners),
                             max(c["x"] for c in corners), max(c["y"] for c in corners))
    slabs, openings = [], []
    if include_slabs:
        openings = detect_x_mark_openings(page, transformer, drawing_area_bbox=drawing_area_bbox)
        # Dấu X trong ký hiệu cột không phải lỗ mở
        openings = [o for o in openings
                    if not any(abs(o["center"]["x"] - c["center"]["x"]) <= c["b_mm"] / 2.0 + 100 and
                               abs(o["center"]["y"] - c["center"]["y"]) <= c["h_mm"] / 2.0 + 100
                               for c in columns)]
        slabs = extract_slab_boundaries_and_openings(
            beams, openings, texts,
            default_thickness_mm=default_slab_thickness_mm,
            drawing_area_bbox=drawing_area_bbox
        )
    doc.close()

    return {
        "columns": columns,
        "beams": beams,
        "slabs": slabs,
        # Bỏ đối tượng Shapely để kết quả serialize được ra JSON
        "openings": [{"center": o["center"], "loop_mm": o["loop_mm"]} for o in openings],
        "schedule_catalog": schedule_catalog,
        "raw_texts_count": len(texts),
        "slab_on_ground": slab_on_ground,
        "untagged_line_pairs_skipped": skipped_untagged,
        "round_columns": sum(1 for c in columns if c["shape"] == "round"),
    }
