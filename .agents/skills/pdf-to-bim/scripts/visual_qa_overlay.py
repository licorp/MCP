# -*- coding: utf-8 -*-
"""
visual_qa_overlay.py - Visual QA Overlay Generator (Chiếu Ngược Tọa Độ Revit Lên PDF)
Giải quyết triệt để 2 vấn đề lớn trong Visual QA Loop:
  1. Loại bỏ lệch khung nhìn (Crop Box Mismatch): Render trực tiếp trang PDF gốc và dùng
     ma trận nghịch đảo (Inverse Affine Matrix) để vẽ đè đối tượng Revit chuẩn xác 100% đến từng pixel.
  2. Định vị tọa độ lỗi (Coordinate Grid Overlay): In đè lưới milimet của Revit (X, Y) và mã ElementId
     lên ảnh để AI Agent đọc trực tiếp vị trí sai lệch và gọi tool sửa lại ngay lập tức.
"""

import os
import math
from typing import Dict, Tuple, List, Optional, Any
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont


class InverseAffineProjector:
    """
    Chiếu ngược tọa độ thực tế trong Revit (mm) về đúng tọa độ Pixel trên ảnh render trang PDF.
    Đảm bảo độ khớp tuyệt đối 100% không phụ thuộc vào Crop View của Revit.
    """
    def __init__(self, transformer, zoom_factor: float = 2.5, rotation_matrix=None):
        self.t = transformer
        # Trang co /Rotate (vd S208 xoay 90 do): toa do vector la toa do CHUA xoay, anh render la DA xoay
        # -> nhan them page.rotation_matrix truoc khi doi ra pixel.
        self.rot = rotation_matrix
        self.zoom = zoom_factor  # zoom = 2.5 tương đương ~180 DPI (rất nét cho Vision LLM)

    def revit_mm_to_pdf_pixel(self, x_rvt: float, y_rvt: float) -> Tuple[int, int]:
        # Bước 1: Đảo ngược Translation và Scale
        dx = (x_rvt - self.t.tx) / self.t.scale
        dy = (y_rvt - self.t.ty) / self.t.scale
        
        # Bước 2: Đảo ngược Rotation (-theta)
        px = dx * self.t.cos_t + dy * self.t.sin_t
        py = -dx * self.t.sin_t + dy * self.t.cos_t
        
        # Bước 3: Đảo lại dấu trục Y của PDF và nhân hệ số phóng đại ảnh (zoom_factor)
        ux, vy = px, -py
        if self.rot is not None:
            r = self.rot
            ux, vy = ux * r.a + vy * r.c + r.e, ux * r.b + vy * r.d + r.f
        u_pixel = int(round(ux * self.zoom))
        v_pixel = int(round(vy * self.zoom))
        return (u_pixel, v_pixel)

    def mm_length_to_pixels(self, mm_val: float) -> int:
        return max(2, int(round((mm_val / self.t.scale) * self.zoom)))


def _get_font(size: int = 20) -> ImageFont.ImageFont:
    """Tải font TrueType rõ nét trên Windows với fallback an toàn."""
    font_candidates = ["arial.ttf", "segoeui.ttf", "calibri.ttf", "consola.ttf"]
    for fn in font_candidates:
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_qa_overlay_image(
    pdf_path: str,
    page_num: int,
    transformer,
    revit_elements: Dict[str, Any],
    output_img_path: str,
    grid_step_mm: int = 5000
) -> Dict[str, Any]:
    """
    Tạo ảnh kiểm tra chéo (Visual QA Overlay):
    - Nền: Bản vẽ PDF gốc (RGB).
    - Lớp phủ Đỏ (Red): Cột kết cấu đã dựng trong Revit (C:ID).
    - Lớp phủ Xanh dương (Blue): Dầm kết cấu đã dựng trong Revit (B:ID) với bề rộng thực tế.
    - Lớp phủ Xanh lá (Green): Vách cứng đã dựng trong Revit (W:ID) với bề dày thực tế.
    - Lớp phủ Vàng cam (Amber): Sàn/Móng đã dựng trong Revit (S:ID / F:ID).
    - Lưới tọa độ (Magenta Grid): Hiển thị tọa độ (X, Y) thực tế của Revit mỗi 5000mm.
    """
    zoom = 2.5
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    
    # 1. Render trang PDF gốc ra ảnh nền (RGB)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    base_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")
    
    # Tạo lớp trong suốt (Transparent Overlay) để vẽ cấu kiện Revit
    overlay = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    projector = InverseAffineProjector(transformer, zoom_factor=zoom,
                                       rotation_matrix=page.rotation_matrix if page.rotation else None)

    # Khởi tạo font chữ nét cao
    font_elem = _get_font(22)
    font_grid = _get_font(18)

    # 2. Vẽ Sàn/Móng kết cấu nếu có (Màu Vàng cam bán trong suốt)
    for slab in revit_elements.get("slabs", []):
        pts_mm = slab.get("polygon_mm", [])
        if pts_mm and len(pts_mm) >= 3:
            poly_px = [projector.revit_mm_to_pdf_pixel(p[0], p[1]) for p in pts_mm]
            draw.polygon(poly_px, fill=(255, 170, 0, 45), outline=(230, 130, 0, 200))
            if "id" in slab:
                cx = sum(p[0] for p in poly_px) // len(poly_px)
                cy = sum(p[1] for p in poly_px) // len(poly_px)
                draw.text((cx, cy), f"S:{slab['id']}", fill=(200, 100, 0, 255),
                          font=font_elem, stroke_width=2, stroke_fill=(255, 255, 255, 230))

    # 3. Vẽ Dầm kết cấu (Màu Xanh dương bán trong suốt: RGBA = 0, 102, 255, 120)
    for beam in revit_elements.get("beams", []):
        p1 = projector.revit_mm_to_pdf_pixel(beam["start"]["x"], beam["start"]["y"])
        p2 = projector.revit_mm_to_pdf_pixel(beam["end"]["x"], beam["end"]["y"])
        width_px = projector.mm_length_to_pixels(beam.get("b_mm", 300))
        
        # Thân dầm đúng bề rộng b_mm
        draw.line([p1, p2], fill=(0, 102, 255, 120), width=width_px)
        # Đường tim dầm nét mảnh để định vị giao điểm
        draw.line([p1, p2], fill=(0, 40, 200, 230), width=2)
        mid_px = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
        draw.text(mid_px, f"B:{beam['id']}", fill=(0, 0, 140, 255),
                  font=font_elem, stroke_width=2, stroke_fill=(255, 255, 255, 230))

    # 4. Vẽ Vách cứng (Màu Xanh lá bán trong suốt: RGBA = 0, 180, 80, 140)
    for wall in revit_elements.get("walls", []):
        p1 = projector.revit_mm_to_pdf_pixel(wall["start"]["x"], wall["start"]["y"])
        p2 = projector.revit_mm_to_pdf_pixel(wall["end"]["x"], wall["end"]["y"])
        thick_px = projector.mm_length_to_pixels(wall.get("thickness_mm", 250))
        draw.line([p1, p2], fill=(0, 180, 80, 140), width=thick_px)
        draw.line([p1, p2], fill=(0, 100, 40, 230), width=2)
        mid_px = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
        draw.text(mid_px, f"W:{wall['id']}", fill=(0, 110, 40, 255),
                  font=font_elem, stroke_width=2, stroke_fill=(255, 255, 255, 230))

    # 5. Vẽ Cột kết cấu (Màu Đỏ bán trong suốt: RGBA = 255, 40, 40, 150)
    for col in revit_elements.get("columns", []):
        cx, cy = col["x"], col["y"]
        hb, hh = col.get("b_mm", 500) / 2.0, col.get("h_mm", 500) / 2.0
        tl = projector.revit_mm_to_pdf_pixel(cx - hb, cy + hh)
        br = projector.revit_mm_to_pdf_pixel(cx + hb, cy - hh)
        x0, x1 = min(tl[0], br[0]), max(tl[0], br[0])
        y0, y1 = min(tl[1], br[1]), max(tl[1], br[1])
        draw.rectangle([x0, y0, x1, y1], fill=(255, 40, 40, 150), outline=(180, 0, 0, 255), width=2)
        draw.text((x0, y0 - 18), f"C:{col['id']}", fill=(180, 0, 0, 255),
                  font=font_elem, stroke_width=2, stroke_fill=(255, 255, 255, 230))

    # 6. Vẽ Lưới tọa độ tham chiếu của Revit (Ruler Grid) giúp AI đọc thẳng tọa độ vùng bị thiếu
    all_x = [c["x"] for c in revit_elements.get("columns", [])] + [b["start"]["x"] for b in revit_elements.get("beams", [])]
    all_y = [c["y"] for c in revit_elements.get("columns", [])] + [b["start"]["y"] for b in revit_elements.get("beams", [])]
    
    if all_x and all_y:
        min_x = int(min(all_x) // grid_step_mm) * grid_step_mm
        max_x = int(max(all_x) // grid_step_mm + 1) * grid_step_mm
        min_y = int(min(all_y) // grid_step_mm) * grid_step_mm
        max_y = int(max(all_y) // grid_step_mm + 1) * grid_step_mm
        
        for gx in range(min_x, max_x + 1, grid_step_mm):
            p_bot = projector.revit_mm_to_pdf_pixel(gx, min_y)
            p_top = projector.revit_mm_to_pdf_pixel(gx, max_y)
            draw.line([p_bot, p_top], fill=(180, 0, 180, 70), width=1)
            draw.text((p_top[0] + 4, max(12, p_top[1])), f"X={gx}", fill=(140, 0, 140, 255),
                      font=font_grid, stroke_width=2, stroke_fill=(255, 255, 255, 220))
            
        for gy in range(min_y, max_y + 1, grid_step_mm):
            p_left = projector.revit_mm_to_pdf_pixel(min_x, gy)
            p_right = projector.revit_mm_to_pdf_pixel(max_x, gy)
            draw.line([p_left, p_right], fill=(180, 0, 180, 70), width=1)
            draw.text((max(12, p_left[0]), p_left[1] - 16), f"Y={gy}", fill=(140, 0, 140, 255),
                      font=font_grid, stroke_width=2, stroke_fill=(255, 255, 255, 220))

    # 7. Gộp ảnh và xuất ra file PNG
    combined = Image.alpha_composite(base_img, overlay).convert("RGB")
    out_dir = os.path.dirname(os.path.abspath(output_img_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    combined.save(output_img_path, "PNG", optimize=True)
    
    return {
        "status": "success",
        "qa_image_path": output_img_path,
        "summary": {
            "rendered_columns": len(revit_elements.get("columns", [])),
            "rendered_beams": len(revit_elements.get("beams", [])),
            "rendered_walls": len(revit_elements.get("walls", [])),
            "rendered_slabs": len(revit_elements.get("slabs", []))
        }
    }
