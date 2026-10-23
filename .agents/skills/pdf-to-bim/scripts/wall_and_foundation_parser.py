# -*- coding: utf-8 -*-
"""
wall_and_foundation_parser.py - Nhận Diện Vách Cứng (Shear Walls) & Đài Móng (Pile Caps)
Thuật toán chuyên sâu phân biệt:
  1. Vách cứng (Core Wall / Shear Wall): Đa giác chữ L, T, U, I có nét tô Solid Fill hoặc
     hàng loạt nét Hatch bê tông nghiêng 30-60 độ và độ mảnh (Perimeter^2 / Area) >= 24.
     Tự động phân rã thành các đoạn thẳng Wall Centerline có kéo dài bù góc (Corner Butt/Miter Join).
  2. Cọc (Piles): Đường tròn (4 hoặc 8 cung Bezier khép kín) đường kính 250mm - 1500mm.
  3. Đài móng (Pile Caps): Đa giác khép kín chứa từ 1 đến nhiều cọc bên trong, ghép nối ghi chú
     kích thước L x B x H hoặc h=... để xác định chiều dày đài móng.
"""

import math
import re
from typing import List, Dict, Tuple, Optional
from shapely.geometry import LineString, Polygon, Point, MultiPolygon, box
from shapely.ops import polygonize, unary_union


def parse_foundation_or_wall_tag(text: str) -> Dict:
    """
    Giải mã ghi chú Vách cứng và Đài móng.
    Ví dụ Vách: 'W1 (t=300)', 'SW2-250', 'CW1 (400)'
    Ví dụ Móng: 'PC1 (2000x2000x1200)', 'F2 1500x1500 H=900', 'PC3 (h=1500)'
    """
    txt = text.strip()
    
    # 1. Tìm kích thước 3 chiều L x B x H của Đài móng (VD: 1800x1800x1200)
    dim3_match = re.search(r'(\d{3,5})\s*[xX\*]\s*(\d{3,5})\s*[xX\*]\s*(\d{3,4})', txt)
    if dim3_match:
        return {
            "type": "foundation",
            "mark": txt.split()[0],
            "length_mm": int(dim3_match.group(1)),
            "width_mm": int(dim3_match.group(2)),
            "thickness_mm": int(dim3_match.group(3)),
            "raw_text": txt
        }

    # 2. Tìm chiều dày (t=300, h=1200, H=1000, hoặc SW1-250)
    thk_match = re.search(r'(?:[tThH]\s*=\s*|-)(\d{2,4})|\((\d{3,4})\)', txt)
    val = int(thk_match.group(1) or thk_match.group(2)) if thk_match else None

    is_wall = bool(re.match(r'^(?:W|SW|CW|DW)\d+', txt, re.IGNORECASE))
    is_found = bool(re.match(r'^(?:PC|F|CF|MF)\d+', txt, re.IGNORECASE))

    return {
        "type": "wall" if is_wall else ("foundation" if is_found else "unknown"),
        "mark": txt.split()[0] if txt else "Unlabeled",
        "thickness_mm": val,
        "raw_text": txt
    }


def extract_circles_and_polygons_from_pdf(page, transformer) -> Tuple[List[Dict], List[Polygon], List[LineString], List[Point]]:
    """
    Quét trang PDF để tách riêng:
    1. Các đường tròn (Piles / Cọc khoan nhồi / Cọc ép).
    2. Các vùng tô đặc (Solid Fills - thường là Vách cứng hoặc Cột).
    3. Các đoạn thẳng biên (Boundary Lines) và tâm các nét Hatch nghiêng.
    """
    piles = []
    solid_fill_polys = []
    boundary_lines = []
    hatch_midpoints = []

    for path in page.get_drawings():
        items = path.get("items", [])
        fill_color = path.get("fill")  # Nếu có màu fill -> Vùng tô đặc (Solid Hatch)

        # Kiểm tra đường tròn (Trong PDF, hình tròn thường xuất ra 4 đường cong Bezier 'c' khép kín)
        curve_items = [it for it in items if it[0] == "c"]
        if len(curve_items) in (4, 8) and path.get("rect"):
            r = path["rect"]
            p_min = transformer.to_revit_mm(r.x0, r.y1)
            p_max = transformer.to_revit_mm(r.x1, r.y0)
            w = abs(p_max["x"] - p_min["x"])
            h = abs(p_max["y"] - p_min["y"])
            # Nếu gần như tròn (sai số < 5%) và đường kính từ 250mm -> 1500mm -> Chính là Cọc (Pile)
            if 250 <= w <= 1500 and abs(w - h) / max(w, h) < 0.05:
                cx = round((p_min["x"] + p_max["x"]) / 2.0, 1)
                cy = round((p_min["y"] + p_max["y"]) / 2.0, 1)
                diam = int(round((w + h) / 2.0, -1))
                piles.append({"center_mm": {"x": cx, "y": cy}, "diameter_mm": diam})
                continue

        # Thu thập các đoạn thẳng
        path_pts = []
        for item in items:
            if item[0] == "l":
                p1 = transformer.to_revit_mm(item[1].x, item[1].y)
                p2 = transformer.to_revit_mm(item[2].x, item[2].y)
                seg_len = math.hypot(p2["x"] - p1["x"], p2["y"] - p1["y"])
                if seg_len < 10:
                    continue

                path_pts.extend([(p1["x"], p1["y"]), (p2["x"], p2["y"])])
                dx, dy = abs(p2["x"] - p1["x"]), abs(p2["y"] - p1["y"])
                
                # Nhận diện nét Hatch: Đoạn thẳng ngắn (50mm -> 900mm) nghiêng góc ~30-60 độ
                is_diagonal = (dx > 20 and dy > 20 and 0.4 <= (dy / dx) <= 2.5)
                if 50 <= seg_len <= 900 and is_diagonal:
                    hatch_midpoints.append(Point((p1["x"] + p2["x"]) / 2.0, (p1["y"] + p2["y"]) / 2.0))
                elif seg_len >= 150:
                    boundary_lines.append(LineString([(p1["x"], p1["y"]), (p2["x"], p2["y"])]))

            elif item[0] == "re":
                r = item[1]
                p1 = transformer.to_revit_mm(r.x0, r.y0)
                p2 = transformer.to_revit_mm(r.x1, r.y1)
                poly = box(min(p1["x"], p2["x"]), min(p1["y"], p2["y"]),
                           max(p1["x"], p2["x"]), max(p1["y"], p2["y"]))
                if fill_color is not None and poly.area > 30000:
                    solid_fill_polys.append(poly)
                else:
                    boundary_lines.append(poly.exterior)

        if fill_color is not None and len(path_pts) >= 3:
            poly = Polygon(path_pts)
            if poly.is_valid and poly.area > 30000:
                solid_fill_polys.append(poly)

    return piles, solid_fill_polys, boundary_lines, hatch_midpoints


def decompose_shear_wall_polygon(wall_poly: Polygon, min_thick: float = 150.0, max_thick: float = 800.0) -> List[Dict]:
    """
    Thuật toán bóc tách Vách cứng phức tạp (chữ L, T, U, I) thành các đoạn thẳng Revit Wall:
    1. Lấy các cạnh dài của đa giác vách.
    2. Ghép cặp các cạnh đối diện song song cách nhau khoảng thickness (150mm -> 800mm).
    3. Tự động kéo dài đường tâm (Centerline) tại các góc giao chữ L, T một đoạn bằng (thickness / 2)
       để các tấm vách trong Revit tự động nối góc (Auto-Join Butt/Miter) kín khít.
    """
    ext_coords = list(wall_poly.simplify(5.0).exterior.coords)
    edges = []
    for i in range(len(ext_coords) - 1):
        p1, p2 = ext_coords[i], ext_coords[i + 1]
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if length >= 400.0:  # Cạnh vách dài tối thiểu 400mm
            ux, uy = (p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length
            edges.append({"p1": p1, "p2": p2, "len": length, "ux": ux, "uy": uy})

    wall_segments = []
    used = set()

    for i in range(len(edges)):
        if i in used:
            continue
        e1 = edges[i]
        best_j = None
        best_thick = None

        for j in range(i + 1, len(edges)):
            if j in used:
                continue
            e2 = edges[j]
            # Kiểm tra song song
            if abs(e1["ux"] * e2["uy"] - e1["uy"] * e2["ux"]) > 0.02:
                continue

            # Khoảng cách vuông góc giữa 2 mép vách
            dist = abs((e2["p1"][0] - e1["p1"][0]) * (-e1["uy"]) + (e2["p1"][1] - e1["p1"][1]) * e1["ux"])
            thick = round(dist, -1)

            if min_thick <= thick <= max_thick:
                # Kiểm tra hình chiếu của 2 cạnh có chồng lên nhau (overlap) không
                t1 = (e2["p1"][0] - e1["p1"][0]) * e1["ux"] + (e2["p1"][1] - e1["p1"][1]) * e1["uy"]
                t2 = (e2["p2"][0] - e1["p1"][0]) * e1["ux"] + (e2["p2"][1] - e1["p1"][1]) * e1["uy"]
                t_min, t_max = max(0.0, min(t1, t2)), min(e1["len"], max(t1, t2))
                
                if t_max - t_min >= 300.0:  # Đoạn chồng lấp dài ít nhất 300mm
                    best_j = j
                    best_thick = int(thick)
                    # Lấy bao phủ tối đa chiều dài của nhánh vách (hàn góc chữ L/T tự động)
                    full_min = min(0.0, t1, t2)
                    full_max = max(e1["len"], t1, t2)
                    
                    # Vector pháp tuyến hướng từ e1 sang e2
                    nx = -e1["uy"] if ((e2["p1"][0] - e1["p1"][0]) * (-e1["uy"]) + (e2["p1"][1] - e1["p1"][1]) * e1["ux"]) > 0 else e1["uy"]
                    ny = e1["ux"] if nx == -e1["uy"] else -e1["ux"]
                    
                    cx1 = e1["p1"][0] + full_min * e1["ux"] + (dist / 2.0) * nx
                    cy1 = e1["p1"][1] + full_min * e1["uy"] + (dist / 2.0) * ny
                    cx2 = e1["p1"][0] + full_max * e1["ux"] + (dist / 2.0) * nx
                    cy2 = e1["p1"][1] + full_max * e1["uy"] + (dist / 2.0) * ny
                    
                    wall_segments.append({
                        "start_mm": {"x": round(cx1, 1), "y": round(cy1, 1)},
                        "end_mm": {"x": round(cx2, 1), "y": round(cy2, 1)},
                        "thickness_mm": best_thick
                    })
                    break

        if best_j is not None:
            used.add(i)
            used.add(best_j)

    return wall_segments


def extract_shear_walls_and_foundations(
    page,
    transformer,
    texts: List[Dict],
    default_pile_cap_thick_mm: int = 1200
) -> Dict:
    """
    Hàm chính phân loại và bóc tách:
    - Vách cứng (Shear Walls / Core Walls) có chứa ký hiệu Hatch hoặc Solid Fill.
    - Đài móng (Pile Caps / Footings) có chứa Cọc (Piles) hoặc ghi chú móng.
    """
    piles, solid_polys, boundary_lines, hatch_pts = extract_circles_and_polygons_from_pdf(page, transformer)
    
    # Đóng vùng toàn bộ các đoạn thẳng biên trên bản vẽ
    noded_lines = unary_union(boundary_lines)
    candidate_polys = list(polygonize(noded_lines)) + solid_polys

    shear_walls = []
    pile_caps = []

    for poly in candidate_polys:
        if not poly.is_valid or poly.area < 60000:  # Bỏ qua vùng quá nhỏ (< 0.06 m2)
            continue

        # 1. KIỂM TRA ĐÀI MÓNG (PILE CAP): Đa giác có chứa Cọc (Piles) bên trong
        contained_piles = [
            p for p in piles 
            if poly.contains(Point(p["center_mm"]["x"], p["center_mm"]["y"]))
        ]
        if len(contained_piles) >= 1 and poly.area <= 150_000_000:  # Diện tích đài <= 150 m2
            clean_poly = poly.simplify(5.0)
            ext_coords = list(clean_poly.exterior.coords)[:-1]
            
            # Tìm Text ghi chú đài móng gần tâm đài nhất (bán kính < 2500mm)
            cx, cy = clean_poly.centroid.x, clean_poly.centroid.y
            thick = default_pile_cap_thick_mm
            mark = f"PC-{len(contained_piles)}P"
            
            for t in texts:
                parsed = parse_foundation_or_wall_tag(t["text"])
                if parsed["thickness_mm"] and math.hypot(t["x"] - cx, t["y"] - cy) < 2500.0:
                    thick = parsed["thickness_mm"]
                    mark = parsed["mark"]
                    break

            pile_caps.append({
                "mark": mark,
                "thickness_mm": thick,
                "piles_count": len(contained_piles),
                "piles": contained_piles,
                "outer_loop_mm": [{"x": round(x, 1), "y": round(y, 1)} for x, y in ext_coords]
            })
            continue

        # 2. KIỂM TRA VÁCH CỨNG (SHEAR WALL): Đa giác mảnh dài có chứa mật độ điểm Hatch bên trong
        # hoặc nằm trong danh sách Solid Fill
        hatch_count = sum(1 for hp in hatch_pts if poly.contains(hp))
        is_solid = any(poly.equals(sp) for sp in solid_polys)
        
        # Tỷ lệ Chu vi^2 / Diện tích > 24 chứng tỏ hình mảnh dài (Vách I, L, T, U) chứ không phải Cột vuông
        slenderness = (poly.length ** 2) / poly.area if poly.area > 0 else 0
        
        if (hatch_count >= 3 or is_solid) and slenderness >= 24.0:
            segments = decompose_shear_wall_polygon(poly)
            for seg in segments:
                shear_walls.append(seg)

    return {
        "shear_walls": shear_walls,
        "pile_caps": pile_caps,
        "standalone_piles": piles,
        "standalone_piles_count": len(piles)
    }
