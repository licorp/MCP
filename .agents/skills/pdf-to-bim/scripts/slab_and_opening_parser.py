# -*- coding: utf-8 -*-
"""
slab_and_opening_parser.py - Nhận Diện Sàn Kết Cấu & Lỗ Mở Chữ X (Shapely + PyMuPDF)
Thuật toán Phase 4 theo chuẩn HPCE Structure:
  1. detect_x_mark_openings: Nhận diện lỗ mở hộp gen / thông tầng có ký hiệu chữ X.
  2. extract_slab_boundaries_and_openings: Đưa mạng lưới dầm đã Snap qua Shapely Polygonize
     để tự động sinh các ô sàn khép kín, lọc lỗ mở, gom nhóm độ dày / cao độ hạ sàn.
"""

import math
import re
from typing import List, Dict, Tuple, Optional, Any
from shapely.geometry import LineString, Polygon, MultiPolygon, Point
from shapely.ops import polygonize, unary_union


def detect_x_mark_openings(page, transformer, max_mid_dist_mm: float = 40.0,
                           len_tol_ratio: float = 0.08,
                           drawing_area_bbox: Optional[Tuple[float, float, float, float]] = None
                           ) -> List[Dict[str, Any]]:
    """
    Phase 4.1: Quét các cặp đoạn thẳng cắt nhau tại chính giữa có độ dài tương đương
    để nhận diện lỗ mở chữ X (Shafts, Voids, MEP Openings).

    drawing_area_bbox: (x_min, y_min, x_max, y_max) tính bằng mm theo hệ tọa độ Revit, dùng để
      loại bỏ các nét vẽ Khung tên (Title Block) ngoài vùng mặt bằng thực tế. Nếu None, quét
      toàn bộ trang (mặc định, không giả định khung tên nằm ở đâu).
    """
    def _in_bbox(x, y):
        if drawing_area_bbox is None:
            return True
        x0, y0, x1, y1 = drawing_area_bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    lines = []
    for path in page.get_drawings():
        for item in path.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                rp1 = transformer.to_revit_mm(p1.x, p1.y)
                rp2 = transformer.to_revit_mm(p2.x, p2.y)
                if not (_in_bbox(rp1["x"], rp1["y"]) and _in_bbox(rp2["x"], rp2["y"])):
                    continue
                length = math.hypot(rp2["x"] - rp1["x"], rp2["y"] - rp1["y"])
                if 200 <= length <= 6000:  # Kích thước nét gạch chéo lỗ mở
                    mid = {"x": (rp1["x"] + rp2["x"]) / 2.0, "y": (rp1["y"] + rp2["y"]) / 2.0}
                    lines.append((rp1, rp2, mid, length))

    openings = []
    used = set()

    for i in range(len(lines)):
        if i in used:
            continue
        p1, p2, mid1, len1 = lines[i]

        for j in range(i + 1, len(lines)):
            if j in used:
                continue
            q1, q2, mid2, len2 = lines[j]

            # Kiểm tra độ chênh lệch chiều dài < len_tol_ratio (8%)
            if abs(len1 - len2) / max(len1, len2) > len_tol_ratio:
                continue

            # Kiểm tra khoảng cách giữa 2 trung điểm <= max_mid_dist_mm (40mm)
            d_mid = math.hypot(mid1["x"] - mid2["x"], mid1["y"] - mid2["y"])
            if d_mid <= max_mid_dist_mm:
                # 4 đỉnh của chữ X
                pts = [p1, q1, p2, q2]
                center_x = (mid1["x"] + mid2["x"]) / 2.0
                center_y = (mid1["y"] + mid2["y"]) / 2.0

                # Sắp xếp 4 đỉnh ngược chiều kim đồng hồ (CCW) quanh tâm
                sorted_pts = sorted(pts, key=lambda pt: math.atan2(pt["y"] - center_y, pt["x"] - center_x))
                poly_coords = [(pt["x"], pt["y"]) for pt in sorted_pts]
                poly = Polygon(poly_coords)

                if poly.is_valid and poly.area > 40000:  # Diện tích >= 0.04 m2
                    used.add(i)
                    used.add(j)
                    openings.append({
                        "center": {"x": round(center_x, 1), "y": round(center_y, 1)},
                        "polygon": poly,
                        "loop_mm": [{"x": round(pt["x"], 1), "y": round(pt["y"], 1)} for pt in sorted_pts]
                    })
                    break

    return openings


def extract_slab_boundaries_and_openings(
    beams: List[Dict],
    openings: List[Dict],
    texts: List[Dict],
    default_thickness_mm: int = 150,
    drawing_area_bbox: Optional[Tuple[float, float, float, float]] = None
) -> List[Dict[str, Any]]:
    """
    Phase 4.2: Đưa mạng lưới đường tâm dầm qua Shapely Polygonize để tìm ô sàn.
    Gom nhóm theo độ dày và cao độ hạ sàn, gán các lỗ mở bên trong.

    drawing_area_bbox: (x_min, y_min, x_max, y_max) tính bằng mm theo hệ tọa độ Revit, dùng để
      loại bỏ các dầm/text thuộc Khung tên (Title Block) ngoài vùng mặt bằng thực tế. Nếu None,
      dùng toàn bộ dữ liệu đầu vào (mặc định).
    """
    def _in_bbox(x, y):
        if drawing_area_bbox is None:
            return True
        x0, y0, x1, y1 = drawing_area_bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    if drawing_area_bbox is not None:
        beams = [
            b for b in beams
            if _in_bbox(b["start_mm"]["x"], b["start_mm"]["y"]) and _in_bbox(b["end_mm"]["x"], b["end_mm"]["y"])
        ]
        texts = [t for t in texts if _in_bbox(t["x"], t["y"])]

    line_strings = []
    for b in beams:
        s = b["start_mm"]
        e = b["end_mm"]
        if math.hypot(e["x"] - s["x"], e["y"] - s["y"]) >= 100:
            line_strings.append(LineString([(s["x"], s["y"]), (e["x"], e["y"])]))

    if not line_strings:
        return []

    # 1. Hợp nhất mạng lưới dầm và đa giác hóa (Polygonize)
    multi_line = unary_union(line_strings)
    raw_polygons = list(polygonize(multi_line))

    # 2. Xử lý từng ô sàn (Slab Panels)
    panels = []
    for poly in raw_polygons:
        if not poly.is_valid or poly.area < 500000:  # Bỏ qua ô quá nhỏ < 0.5 m2
            continue

        # Kiểm tra xem ô có bị phủ bởi lỗ mở chữ X không
        is_void = False
        for op in openings:
            op_poly = op["polygon"]
            if poly.intersects(op_poly):
                inter_area = poly.intersection(op_poly).area
                if inter_area / poly.area >= 0.75:
                    is_void = True
                    break
        if is_void:
            continue

        # Đọc text ghi chú sàn nằm trong ô
        thk_mm = default_thickness_mm
        z_off_mm = 0.0
        mark_slab = "Slab"

        for t in texts:
            pt = Point(t["x"], t["y"])
            if poly.contains(pt):
                raw_t = t.get("text", "")
                parsed = t.get("parsed", {})
                # Ghi chú tiết diện Dầm/Cột/Vách (B1 300x600, C1 600x600, W1 200) nằm trong ô sàn
                # KHÔNG phải chiều dày sàn
                mark_t = parsed.get("mark", "")
                if (parsed.get("b_mm") and parsed.get("h_mm")) or \
                        (mark_t and not mark_t.startswith(("S", "FS", "RS"))):
                    continue
                if parsed.get("z_offset_mm") and parsed["z_offset_mm"] != 0.0:
                    z_off_mm = parsed["z_offset_mm"]

                thk_match = re.search(r'(\d{2,3})\s*(?:THK|D|mm)?\b', raw_t, re.IGNORECASE)
                if thk_match:
                    val = int(thk_match.group(1))
                    if 100 <= val <= 600:
                        thk_mm = val
                        mark_slab = raw_t.strip()
                        break

        panels.append({
            "polygon": poly,
            "thickness_mm": thk_mm,
            "z_offset_mm": z_off_mm,
            "mark": mark_slab
        })

    # 3. Gom nhóm ô sàn theo (thickness_mm, z_offset_mm)
    grouped = {}
    for p in panels:
        key = (p["thickness_mm"], p["z_offset_mm"])
        grouped.setdefault(key, []).append(p)

    final_slabs = []
    slab_idx = 1

    for (thk, z_off), group_panels in grouped.items():
        polys = [p["polygon"] for p in group_panels]
        merged = unary_union(polys)

        sub_polys = []
        if isinstance(merged, MultiPolygon):
            sub_polys = list(merged.geoms)
        elif isinstance(merged, Polygon):
            sub_polys = [merged]

        for sp in sub_polys:
            if sp.area < 500000:
                continue

            # Biên ngoài (Outer Loop)
            outer_coords = list(sp.exterior.coords)[:-1]
            outer_loop = [{"x": round(c[0], 1), "y": round(c[1], 1)} for c in outer_coords]

            # Biên trong / Lỗ mở nội bộ (Inner Loops)
            opening_loops = []
            for interior in sp.interiors:
                int_coords = list(interior.coords)[:-1]
                opening_loops.append([{"x": round(c[0], 1), "y": round(c[1], 1)} for c in int_coords])

            # Bổ sung các lỗ mở chữ X nằm bên trong sàn này
            for op in openings:
                if sp.contains(op["polygon"].centroid):
                    opening_loops.append(op["loop_mm"])

            final_slabs.append({
                "mark": f"S{slab_idx} ({thk}mm)",
                "thickness_mm": thk,
                "z_offset_mm": z_off,
                "outer_loop_mm": outer_loop,
                "opening_loops_mm": opening_loops
            })
            slab_idx += 1

    return final_slabs
