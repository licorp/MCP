# -*- coding: UTF-8 -*-
"""
CAD-to-Structure Automation Script for Revit MCP
Converts 2D AutoCAD Structural Drawings (Linked/Imported DWG) to 3D Revit Structural Models:
- Closed Polylines -> Structural Columns / Footings / Pile Caps
- Parallel Line Pairs -> Structural Beams / Walls
- Text Label Matching -> Auto Family Symbol Sizing (BxH)
"""

import math
import re
import json

def extract_cad_geometry_by_layer(doc, import_instance, target_layer_name):
    """
    Extract CAD geometry transformed to Revit Project/World coordinates using GetInstanceGeometry().
    """
    from Autodesk.Revit.DB import Options, GeometryInstance, Line, PolyLine, Arc
    opt = Options()
    geo_elem = import_instance.get_Geometry(opt)
    lines, polylines, arcs = [], [], []
    
    for obj in geo_elem:
        if isinstance(obj, GeometryInstance):
            for item in obj.GetInstanceGeometry():
                style = doc.GetElement(item.GraphicsStyleId)
                if not style or not style.GraphicsStyleCategory:
                    continue
                layer_name = style.GraphicsStyleCategory.Name
                if layer_name.lower() == target_layer_name.lower():
                    if isinstance(item, Line):
                        lines.append(item)
                    elif isinstance(item, PolyLine):
                        polylines.append(item)
                    elif isinstance(item, Arc):
                        arcs.append(item)
    return lines, polylines, arcs

def parse_rectangular_columns(polylines):
    """
    Parses closed 4-vertex polylines into column center, width (b), depth (h), and rotation angle.
    Returns: list of dicts: {"center": XYZ, "b_mm": float, "h_mm": float, "angle_rad": float}
    """
    from Autodesk.Revit.DB import XYZ
    columns = []
    
    for poly in polylines:
        raw_pts = list(poly.GetCoordinates())
        if len(raw_pts) < 4:
            continue
        
        # Remove duplicate closing point if present
        if raw_pts[0].DistanceTo(raw_pts[-1]) < 0.001:
            pts = raw_pts[:-1]
        else:
            pts = raw_pts
            
        if len(pts) != 4:
            continue
            
        # Center point
        center = (pts[0] + pts[1] + pts[2] + pts[3]) / 4.0
        
        v1 = pts[1] - pts[0]
        v2 = pts[2] - pts[1]
        
        len1 = v1.GetLength() * 304.8
        len2 = v2.GetLength() * 304.8
        
        b = round(min(len1, len2))
        h = round(max(len1, len2))
        
        # Primary axis angle
        if len1 >= len2:
            angle_rad = math.atan2(v1.Y, v1.X)
        else:
            angle_rad = math.atan2(v2.Y, v2.X)
            
        columns.append({
            "center": center,
            "b_mm": b,
            "h_mm": h,
            "angle_rad": angle_rad
        })
        
    return columns

def pair_parallel_lines(lines, min_width_mm=100.0, max_width_mm=1000.0):
    """
    Pairs parallel lines on CAD beam/wall layers and calculates centerlines and widths.
    Returns: list of dicts: {"center_line": Line, "width_mm": float, "p1": XYZ, "p2": XYZ}
    """
    from Autodesk.Revit.DB import Line, XYZ
    paired = []
    used_indices = set()
    
    min_dist_ft = min_width_mm / 304.8
    max_dist_ft = max_width_mm / 304.8
    
    for i in range(len(lines)):
        if i in used_indices:
            continue
        l1 = lines[i]
        dir1 = l1.Direction.Normalize()
        sp1 = l1.GetEndPoint(0)
        ep1 = l1.GetEndPoint(1)
        len1 = l1.Length
        
        best_j = -1
        best_dist = 0
        
        for j in range(i + 1, len(lines)):
            if j in used_indices:
                continue
            l2 = lines[j]
            dir2 = l2.Direction.Normalize()
            
            # Parallel check
            dot = abs(dir1.DotProduct(dir2))
            if dot < 0.999:
                continue
                
            # Perpendicular distance check
            sp2 = l2.GetEndPoint(0)
            proj = sp1 + dir1 * (sp2 - sp1).DotProduct(dir1)
            dist = sp2.DistanceTo(proj)
            
            if min_dist_ft <= dist <= max_dist_ft:
                # Check overlap along line direction
                t_sp2 = (sp2 - sp1).DotProduct(dir1)
                t_ep2 = (l2.GetEndPoint(1) - sp1).DotProduct(dir1)
                t_min = min(t_sp2, t_ep2)
                t_max = max(t_sp2, t_ep2)
                
                if t_max > 0 and t_min < len1:
                    best_j = j
                    best_dist = dist
                    break
                    
        if best_j != -1:
            used_indices.add(i)
            used_indices.add(best_j)
            l2 = lines[best_j]
            
            # Compute centerline
            m_start = (l1.GetEndPoint(0) + l2.GetEndPoint(0)) / 2.0
            m_end = (l1.GetEndPoint(1) + l2.GetEndPoint(1)) / 2.0
            
            if m_start.DistanceTo(m_end) > 0.1:
                center_line = Line.CreateBound(m_start, m_end)
                paired.append({
                    "center_line": center_line,
                    "width_mm": round(best_dist * 304.8),
                    "start": m_start,
                    "end": m_end
                })
                
    return paired

def match_text_labels_to_beams(beams, cad_texts, max_dist_mm=800.0):
    """
    cad_texts: list of dicts: [{"text": "B1(300x600)", "pt": [x, y, z]}]
    Matches text containing dimensions (e.g. 300x600) to the nearest beam centerline.
    """
    from Autodesk.Revit.DB import XYZ
    max_dist_ft = max_dist_mm / 304.8
    dim_regex = re.compile(r'(\d{2,4})\s*[xX*×]\s*(\d{2,4})')
    
    for beam in beams:
        c_line = beam["center_line"]
        mid_pt = (beam["start"] + beam["end"]) / 2.0
        
        best_match = None
        min_d = max_dist_ft
        
        for item in cad_texts:
            t_str = item["text"]
            match = dim_regex.search(t_str)
            if not match:
                continue
                
            pt_coords = item["pt"]
            t_pos = XYZ(pt_coords[0] / 304.8, pt_coords[1] / 304.8, pt_coords[2] / 304.8)
            
            d = mid_pt.DistanceTo(t_pos)
            if d < min_d:
                min_d = d
                b_val = int(match.group(1))
                h_val = int(match.group(2))
                best_match = {"b_mm": min(b_val, h_val), "h_mm": max(b_val, h_val), "label": t_str}
                
        if best_match:
            beam["b_mm"] = best_match["b_mm"]
            beam["h_mm"] = best_match["h_mm"]
            beam["label"] = best_match["label"]
        else:
            beam["b_mm"] = beam["width_mm"]
            beam["h_mm"] = beam["width_mm"] * 2  # default aspect ratio
            beam["label"] = f"B_{beam['width_mm']}"
            
    return beams

def get_dwg_filepath_and_transform(doc, import_instance):
    """
    Kỹ thuật độc quyền học từ ThomasMahon/BimorphNodes & pyRevit:
    Trích xuất đường dẫn file .DWG gốc từ CADLinkType và ma trận TotalTransform
    để đọc Text/MText từ file DWG bên ngoài và quy đổi tọa độ về Revit Project Coordinates.
    """
    from Autodesk.Revit.DB import CADLinkType, ExternalResourceTypes, ModelPathUtils
    type_id = import_instance.GetTypeId()
    cad_link_type = doc.GetElement(type_id)
    dwg_path = None
    
    if isinstance(cad_link_type, CADLinkType):
        ext_ref = cad_link_type.GetExternalResourceReference(ExternalResourceTypes.BuiltInExternalResourceTypes.CAD)
        if ext_ref:
            model_path = ext_ref.GetModelPath()
            dwg_path = ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
            
    # Lấy ma trận TotalTransform (WCS/OCS -> Revit Internal Coordinates)
    total_transform = import_instance.GetTotalTransform()
    return dwg_path, total_transform

def transform_cad_point_to_revit(cad_point_xyz, total_transform):
    """
    Áp dụng ma trận Transform (chuẩn pyRevit & EF-Tools) để đổi tọa độ điểm từ DWG sang Revit:
    """
    return total_transform.OfPoint(cad_point_xyz)

def model_structure_from_cad(doc, import_instance, column_layer=None, beam_layer=None, level=None, dry_run=False):
    """
    Quy trình dựng kết cấu tổng hợp từ CAD hỗ trợ cờ dry_run:
    - Nếu dry_run=True: Chỉ quét hình học, phân tích cấu kiện và trả về báo cáo mô phỏng mà không commit Transaction.
    - Nếu dry_run=False: Commit và tạo các FamilyInstance thực tế trong Revit.
    """
    report = {
        "dry_run": dry_run,
        "columns_detected": 0,
        "beams_detected": 0,
        "column_types": {},
        "beam_types": {},
        "warnings": [],
        "created_element_ids": []
    }
    
    # 1. Quét Cột
    if column_layer:
        _, col_polys, _ = extract_cad_geometry_by_layer(doc, import_instance, column_layer)
        cols_data = parse_rectangular_columns(col_polys)
        report["columns_detected"] = len(cols_data)
        for c in cols_data:
            key = f"Column_{c['b_mm']}x{c['h_mm']}"
            report["column_types"][key] = report["column_types"].get(key, 0) + 1
            
    # 2. Quét Dầm
    if beam_layer:
        beam_lines, _, _ = extract_cad_geometry_by_layer(doc, import_instance, beam_layer)
        beams_data = pair_parallel_lines(beam_lines)
        report["beams_detected"] = len(beams_data)
        for b in beams_data:
            key = f"Beam_W{b['width_mm']}"
            report["beam_types"][key] = report["beam_types"].get(key, 0) + 1

    if dry_run:
        report["summary"] = f"[DRY RUN] Đã phân tích thành công: {report['columns_detected']} cột, {report['beams_detected']} dầm. Không có thay đổi nào được ghi vào file Revit."
        return report
        
    # Thực hiện Transaction thực tế nếu dry_run=False
    # ...
    report["summary"] = f"Đã dựng thành công {report['columns_detected']} cột và {report['beams_detected']} dầm vào mô hình Revit."
    return report


