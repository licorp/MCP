# -*- coding: utf-8 -*-
"""
beam_topology_snapper.py - Thuật Toán Chuẩn Hóa Tô-pô & Bắt Dính Dầm Kết Cấu
Giải quyết triệt để 2 bài toán lớn khi chuyển đổi PDF Kết cấu sang Revit:
  1. Kéo dài đúng phương dầm vào tim Cột hoặc tim Dầm chính (chống hụt đầu, giữ liên tục Analytical Model).
  2. Không làm xoay xiên dầm lệch tâm (Chiếu vuông góc Orthogonal Projection lên trục tâm cột).
  3. Bắt dính Dầm phụ vào tim Dầm chính bằng giải thuật Tìm giao điểm tia (Ray-Segment Intersection).
  4. Gộp các đoạn dầm thẳng hàng cùng tiết diện bị vỡ nét (Collinear Beam Merge).
"""

import math
from typing import List, Dict, Tuple, Optional


def get_beam_vector(beam: Dict) -> Tuple[float, float, float, float, float, float, float]:
    """Trả về (x1, y1, x2, y2, length, ux, uy) của dầm."""
    x1, y1 = beam["start_mm"]["x"], beam["start_mm"]["y"]
    x2, y2 = beam["end_mm"]["x"], beam["end_mm"]["y"]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return x1, y1, x2, y2, 0.0, 0.0, 0.0
    return x1, y1, x2, y2, length, dx / length, dy / length


def merge_collinear_beams(beams: List[Dict], angle_tol_deg: float = 1.5,
                          offset_tol_mm: float = 20.0, max_gap_mm: float = 150.0) -> List[Dict]:
    """
    Bước 0 (Rất quan trọng): Gộp các đoạn dầm cùng phương, cùng tiết diện bị cắt đứt 
    hoặc bị vỡ nét trên PDF thành 1 dầm liên tục.
    - Mặc định max_gap_mm = 150.0 (chỉ nối các nét vỡ trên PDF, giữ nhịp dầm ngắt tại cột theo chuẩn thi công).
    """
    merged = [dict(b, start_mm=dict(b["start_mm"]), end_mm=dict(b["end_mm"])) for b in beams]
    sin_tol = math.sin(math.radians(angle_tol_deg))
    
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                b1, b2 = merged[i], merged[j]
                # Chỉ gộp khi cùng tiết diện b x h và cùng cao độ z_offset
                if (b1.get("b_mm") != b2.get("b_mm") or 
                    b1.get("h_mm") != b2.get("h_mm") or 
                    b1.get("z_offset_mm", 0) != b2.get("z_offset_mm", 0)):
                    continue

                x1, y1, x2, y2, len1, ux1, uy1 = get_beam_vector(b1)
                x3, y3, x4, y4, len2, ux2, uy2 = get_beam_vector(b2)
                if len1 == 0 or len2 == 0:
                    continue

                # 1. Kiểm tra song song: |u1 x u2| < sin_tol
                cross_u = abs(ux1 * uy2 - uy1 * ux2)
                if cross_u > sin_tol:
                    continue

                # 2. Kiểm tra đồng trục (khoảng cách vuông góc giữa 2 đường tâm <= offset_tol_mm)
                perp_dist = abs((x3 - x1) * (-uy1) + (y3 - y1) * ux1)
                if perp_dist > offset_tol_mm:
                    continue

                # 3. Chiếu cả 4 điểm lên trục của dầm 1 để kiểm tra khoảng hở (gap)
                pts = [
                    (0.0, (x1, y1)),
                    (len1, (x2, y2)),
                    ((x3 - x1) * ux1 + (y3 - y1) * uy1, (x3, y3)),
                    ((x4 - x1) * ux1 + (y4 - y1) * uy1, (x4, y4))
                ]
                t_b2_min = min(pts[2][0], pts[3][0])
                t_b2_max = max(pts[2][0], pts[3][0])

                # Khoảng hở giữa đoạn [0, len1] và [t_b2_min, t_b2_max]
                gap = max(0.0, t_b2_min - len1, 0.0 - t_b2_max)
                if gap <= max_gap_mm:
                    pts.sort(key=lambda item: item[0])
                    # Giữ thẳng tuyệt đối theo phương của dầm dài hơn
                    new_start = pts[0][1]
                    new_end = (x1 + pts[-1][0] * ux1, y1 + pts[-1][0] * uy1)
                    b1["start_mm"] = {"x": round(new_start[0], 1), "y": round(new_start[1], 1)}
                    b1["end_mm"] = {"x": round(new_end[0], 1), "y": round(new_end[1], 1)}
                    if b1.get("mark") == "Unlabeled" and b2.get("mark") != "Unlabeled":
                        b1["mark"] = b2["mark"]
                    merged.pop(j)
                    changed = True
                    break
            if changed:
                break
    return merged


def snap_endpoint_to_column(
    ep: Dict[str, float],
    dir_x: float,
    dir_y: float,
    columns: List[Dict],
    max_extend_mm: float = 800.0,
    center_snap_tol_mm: float = 35.0
) -> Optional[Dict[str, float]]:
    """
    Ưu tiên 1: Kéo dài đầu mút dầm (ep) theo hướng ra ngoài (dir_x, dir_y) để bắt vào Cột.
    - Nếu dầm đi đúng tâm cột (sai số <= center_snap_tol_mm): Bắt dính chính xác vào tâm cột (cx, cy).
    - Nếu dầm lệch tâm (dầm biên bằng mép cột): Chiếu vuông góc tâm cột lên đường tâm dầm 
      để kéo dài đúng tới trục cột mà KHÔNG làm xoay góc dầm.
    """
    ex, ey = ep["x"], ep["y"]
    best_pt = None
    min_advance = float("inf")

    for col in columns:
        cx, cy = col["center"]["x"], col["center"]["y"]
        half_b = col.get("b_mm", 500) / 2.0
        half_h = col.get("h_mm", 500) / 2.0

        # Vector từ đầu mút dầm tới tâm cột
        vx, vy = cx - ex, cy - ey

        # t_proj: Khoảng cách cần kéo dài dọc theo trục dầm để ngang bằng với tâm cột
        t_proj = vx * dir_x + vy * dir_y

        # Chỉ xét khi tâm cột nằm ở phía trước đầu mút dầm (hoặc lùi nhẹ do sai số nét vẽ)
        # và nằm trong tầm với (max_extend_mm + nửa kích thước cột)
        max_reach = max_extend_mm + max(half_b, half_h)
        if -100.0 <= t_proj <= max_reach:
            # Khoảng cách lệch tâm (vuông góc từ tâm cột tới đường tim dầm)
            eccentricity = abs(vx * (-dir_y) + vy * dir_x)

            # Điểm sau khi kéo dài dọc theo phương dầm
            proj_x = ex + t_proj * dir_x
            proj_y = ey + t_proj * dir_y

            # Kiểm tra điểm chiếu có rơi vào trong phạm vi tiết diện cột (cộng dung sai 50mm) không
            in_col_box = (abs(proj_x - cx) <= half_b + 50.0) and (abs(proj_y - cy) <= half_h + 50.0)

            if in_col_box and abs(t_proj) < min_advance:
                min_advance = abs(t_proj)
                if eccentricity <= center_snap_tol_mm:
                    # Dầm đồng tâm với cột -> Snap thẳng vào tọa độ tâm cột
                    best_pt = {
                        "x": round(cx, 1),
                        "y": round(cy, 1),
                        "snap_type": "Column_Center",
                        "target_col": col.get("mark", "Col")
                    }
                else:
                    # Dầm lệch tâm -> Kéo dài thẳng theo phương dầm tới đúng trục tâm cột
                    best_pt = {
                        "x": round(proj_x, 1),
                        "y": round(proj_y, 1),
                        "snap_type": "Column_Axis_Projected",
                        "target_col": col.get("mark", "Col")
                    }

    return best_pt


def snap_endpoint_to_main_beam(
    beam_idx: int,
    ep: Dict[str, float],
    dir_x: float,
    dir_y: float,
    all_beams: List[Dict],
    max_extend_mm: float = 800.0
) -> Optional[Dict[str, float]]:
    """
    Ưu tiên 2: Nếu đầu dầm không gặp cột, tìm dầm chính (Main Girder) cắt ngang phía trước 
    và kéo dài đầu dầm phụ từ mép dầm chính vào đúng đường tâm (Centerline) của dầm chính.
    """
    ex, ey = ep["x"], ep["y"]
    best_pt = None
    min_t = float("inf")

    for j, target in enumerate(all_beams):
        if j == beam_idx:
            continue

        x3, y3, x4, y4, len_target, ux2, uy2 = get_beam_vector(target)
        if len_target == 0:
            continue

        # Bỏ qua nếu 2 dầm gần như song song (góc giao < 15 độ)
        sin_angle = abs(dir_x * uy2 - dir_y * ux2)
        if sin_angle < 0.2588:  # sin(15°)
            continue

        # Giải hệ phương trình giao điểm giữa:
        # Tia kéo dài của dầm phụ: P(t) = (ex, ey) + t * (dir_x, dir_y)
        # Đoạn thẳng tim dầm chính: Q(u) = (x3, y3) + u * (ux2, uy2), với 0 <= u <= len_target
        denom = dir_x * uy2 - dir_y * ux2
        dx, dy = x3 - ex, y3 - ey
        
        t = (dx * uy2 - dy * ux2) / denom
        u = (dx * dir_y - dy * dir_x) / denom

        half_main_width = target.get("b_mm", 300) / 2.0
        max_reach = max_extend_mm + half_main_width

        # Điều kiện hợp lệ:
        # 1. Giao điểm nằm phía trước đầu mút dầm phụ (-50mm <= t <= max_reach)
        # 2. Giao điểm nằm trên thân dầm chính (cho phép dung sai 100mm ở 2 đầu mút dầm chính)
        if -50.0 <= t <= max_reach and (-100.0 <= u <= len_target + 100.0):
            if abs(t) < min_t:
                min_t = abs(t)
                ix = ex + t * dir_x
                iy = ey + t * dir_y
                best_pt = {
                    "x": round(ix, 1),
                    "y": round(iy, 1),
                    "snap_type": "Main_Beam_Centerline",
                    "target_beam": target.get("mark", "Beam")
                }

    return best_pt


def extend_and_snap_structural_beams(
    beams: List[Dict],
    columns: List[Dict],
    merge_broken_segments: bool = True,
    max_extend_mm: float = 600.0
) -> List[Dict]:
    """
    Hàm tổng hợp chạy trước khi gửi payload qua Revit MCP:
    1. Gộp các đoạn dầm vỡ nét (Collinear Merge).
    2. Kéo dài & bắt dính 2 đầu dầm vào Tâm Cột (Ưu tiên 1) hoặc Tim Dầm Chính (Ưu tiên 2).
    """
    # Bước 1: Gộp các nét dầm bị đứt đoạn (chỉ gộp nét vỡ <= 150mm để giữ nguyên nhịp dầm giữa các cột)
    processed_beams = merge_collinear_beams(beams, max_gap_mm=150.0) if merge_broken_segments else list(beams)

    # Bước 2: Duyệt từng dầm để xử lý 2 đầu mút (Start và End)
    for i, beam in enumerate(processed_beams):
        x1, y1, x2, y2, length, ux, uy = get_beam_vector(beam)
        if length == 0:
            continue

        # --- XỬ LÝ ĐIỂM ĐẦU (START POINT): Hướng kéo dài ra ngoài là (-ux, -uy) ---
        start_col_snap = snap_endpoint_to_column(
            beam["start_mm"], -ux, -uy, columns, max_extend_mm=max_extend_mm
        )
        if start_col_snap:
            beam["start_mm"] = {"x": start_col_snap["x"], "y": start_col_snap["y"]}
            beam["start_connection"] = start_col_snap["snap_type"]
            beam["snapped_start_col"] = start_col_snap.get("target_col", "Col")
        else:
            start_beam_snap = snap_endpoint_to_main_beam(
                i, beam["start_mm"], -ux, -uy, processed_beams, max_extend_mm=max_extend_mm
            )
            if start_beam_snap:
                beam["start_mm"] = {"x": start_beam_snap["x"], "y": start_beam_snap["y"]}
                beam["start_connection"] = start_beam_snap["snap_type"]
                beam["snapped_start_beam"] = start_beam_snap.get("target_beam", "Beam")
            else:
                beam["start_connection"] = "Free_Cantilever"

        # --- XỬ LÝ ĐIỂM CUỐI (END POINT): Hướng kéo dài ra ngoài là (+ux, +uy) ---
        end_col_snap = snap_endpoint_to_column(
            beam["end_mm"], ux, uy, columns, max_extend_mm=max_extend_mm
        )
        if end_col_snap:
            beam["end_mm"] = {"x": end_col_snap["x"], "y": end_col_snap["y"]}
            beam["end_connection"] = end_col_snap["snap_type"]
            beam["snapped_end_col"] = end_col_snap.get("target_col", "Col")
        else:
            end_beam_snap = snap_endpoint_to_main_beam(
                i, beam["end_mm"], ux, uy, processed_beams, max_extend_mm=max_extend_mm
            )
            if end_beam_snap:
                beam["end_mm"] = {"x": end_beam_snap["x"], "y": end_beam_snap["y"]}
                beam["end_connection"] = end_beam_snap["snap_type"]
                beam["snapped_end_beam"] = end_beam_snap.get("target_beam", "Beam")
            else:
                beam["end_connection"] = "Free_Cantilever"

    return processed_beams
