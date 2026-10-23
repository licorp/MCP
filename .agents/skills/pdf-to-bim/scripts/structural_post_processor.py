# -*- coding: UTF-8 -*-
"""
structural_post_processor.py - Hậu xử lý mô hình Kết cấu trong Autodesk Revit
Giải quyết triệt để 3 vấn đề lớn sau khi dựng hình qua MCP:
  1. Hộp thoại cảnh báo treo tiến trình MCP: Tự động chặn bằng IFailuresPreprocessor (MCPAutoFailureSwallower).
  2. Thứ tự ưu tiên cắt (Cut Priority): Ép thứ tự Cột/Vách cắt Dầm/Sàn, Dầm chính cắt Dầm phụ, Dầm cắt Sàn.
  3. Đầu dầm bị hở (Cutback): Tự động triệt tiêu START_JOIN_CUTBACK và END_JOIN_CUTBACK về 0.0.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    BoundingBoxIntersectsFilter, Outline, XYZ, Transaction,
    JoinGeometryUtils, IFailuresPreprocessor, FailureProcessingResult,
    FailureSeverity, ElementId, LocationCurve, Structure
)


# ==============================================================================
# 1. BỘ CHẶN CẢNH BÁO TỰ ĐỘNG (TRÁNH TREO REVIT KHI CHẠY MCP TỰ ĐỘNG)
# ==============================================================================
class MCPAutoFailureSwallower(IFailuresPreprocessor):
    """
    Tự động bỏ qua (DeleteWarning) toàn bộ các cảnh báo thông thường (Off-axis, 
    Duplicate Mark, Room separation, Highlighted elements joined but do not intersect...)
    và tự động giải quyết lỗi Join để không bao giờ hiện Popup làm treo MCP Server.
    """
    def PreprocessFailures(self, failuresAccessor):
        fail_list = failuresAccessor.GetFailureMessages()
        for f in fail_list:
            severity = f.GetSeverity()
            # Nếu là cảnh báo (Warning) -> Xóa cảnh báo ngay lập tức
            if severity == FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(f)
            # Nếu là lỗi (Error) có thể tự động tháo gỡ (như lỗi Unjoin Elements) -> Chấp nhận giải pháp mặc định
            elif severity == FailureSeverity.Error and f.HasResolutions():
                failuresAccessor.ResolveFailure(f)
                return FailureProcessingResult.ProceedWithCommit
        return FailureProcessingResult.Continue


def attach_failure_swallower(transaction):
    """Gắn bộ chặn cảnh báo vào Transaction của Revit."""
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(MCPAutoFailureSwallower())
    options.SetClearAfterRollback(True)
    transaction.SetFailureHandlingOptions(options)


# ==============================================================================
# 2. HÀM KIỂM TRA VÀ ÉP THỨ TỰ ƯU TIÊN JOIN (CUT PRIORITY ENFORCER)
# ==============================================================================
def ensure_join_and_order(doc, cutting_elem, cut_elem):
    """
    Đảm bảo 2 đối tượng được Join với nhau và `cutting_elem` luôn là đối tượng CẮT `cut_elem`.
    Trả về: ("joined" | "switched" | "already_correct" | "failed")
    """
    try:
        are_joined = JoinGeometryUtils.AreElementsJoined(doc, cutting_elem, cut_elem)
        if not are_joined:
            JoinGeometryUtils.JoinGeometry(doc, cutting_elem, cut_elem)
            are_joined = True

        if are_joined:
            # Kiểm tra xem cutting_elem có thực sự đang cắt cut_elem không
            if not JoinGeometryUtils.IsCuttingElementInJoin(doc, cutting_elem, cut_elem):
                JoinGeometryUtils.SwitchJoinOrder(doc, cutting_elem, cut_elem)
                return "switched"
            return "joined"
    except Exception:
        # Bỏ qua nếu 2 BoundingBox chạm nhau ở góc nhưng hình khối thực tế không giao nhau
        pass
    return "failed"


def get_beam_volume_rank(beam):
    """
    Tính điểm ưu tiên cho Dầm để phân biệt Dầm chính (Main Girder) và Dầm phụ (Secondary Beam).
    Dầm nào có chiều cao h lớn hơn và tiết diện b*h lớn hơn sẽ làm Dầm chính (cắt dầm nhỏ hơn).
    """
    sym = beam.Symbol
    if not sym:
        return 0.0
    b_p = sym.LookupParameter("b") or sym.LookupParameter("Width") or sym.LookupParameter("bf")
    h_p = sym.LookupParameter("h") or sym.LookupParameter("Depth") or sym.LookupParameter("d")
    b = b_p.AsDouble() if b_p else 1.0
    h = h_p.AsDouble() if h_p else 2.0
    # Ưu tiên chiều cao dầm (h) gấp 10 lần bề rộng (b)
    return round(h * 100.0 + b * 10.0, 3)


def find_intersecting_elements(doc, target_elem, category_bic, tolerance_ft=0.05):
    """
    Dùng BoundingBoxIntersectsFilter tốc độ cao của Revit API để tìm tất cả cấu kiện 
    thuộc `category_bic` đang giao cắt với `target_elem`.
    """
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


# ==============================================================================
# 3. HÀM TỔNG HỢP: AUTO-JOIN & SỬA CẢNH BÁO TRÊN TOÀN BỘ TẦNG KẾT CẤU
# ==============================================================================
def auto_join_and_clean_warnings_on_level(doc, level_name):
    """
    Thực thi hậu xử lý sau khi MCP dựng xong mô hình Kết cấu:
    1. Khử Cutback ở 2 đầu dầm bê tông để ăn kín vào Cột/Vách.
    2. Thực thi Join Geometry theo đúng thứ tự:
       - Cột & Vách cắt Dầm.
       - Cột & Vách cắt Sàn.
       - Dầm cắt Sàn.
       - Dầm chính (h lớn) cắt Dầm phụ (h nhỏ).
    3. Quét và dọn dẹp các cảnh báo (Warnings) còn tồn đọng trong file Revit.
    """
    stats = {
        "col_wall_cut_beam": 0,
        "col_wall_cut_slab": 0,
        "beam_cut_slab": 0,
        "main_beam_cut_sec_beam": 0,
        "cutback_zeroed": 0,
        "unjoined_disconnected_warnings": 0
    }

    # Lọc các cấu kiện thuộc tầng level_name (hỗ trợ tìm kiếm linh hoạt)
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
        # ----------------------------------------------------------------------
        # BƯỚC A: Đưa Start/End Join Cutback của Dầm về 0 để không bị hở mép Cột
        # ----------------------------------------------------------------------
        for beam in beams_on_level:
            for bip in [BuiltInParameter.START_JOIN_CUTBACK, BuiltInParameter.END_JOIN_CUTBACK]:
                p_cb = beam.get_Parameter(bip)
                if p_cb and not p_cb.IsReadOnly and p_cb.AsDouble() > 0:
                    p_cb.Set(0.0)
                    stats["cutback_zeroed"] += 1

        doc.Regenerate()

        # ----------------------------------------------------------------------
        # BƯỚC B: Xử lý Join cho từng Dầm (Cột/Vách cắt Dầm & Dầm chính cắt Dầm phụ)
        # ----------------------------------------------------------------------
        processed_beam_pairs = set()

        for beam in beams_on_level:
            beam_id = beam.Id.IntegerValue if hasattr(beam.Id, 'IntegerValue') else int(beam.Id.ToString())

            # 1. Cột cắt Dầm (Columns cut Beams)
            cols = find_intersecting_elements(doc, beam, BuiltInCategory.OST_StructuralColumns)
            for col in cols:
                res = ensure_join_and_order(doc, cutting_elem=col, cut_elem=beam)
                if res in ("joined", "switched"):
                    stats["col_wall_cut_beam"] += 1

            # 2. Vách cứng cắt Dầm (Structural Walls cut Beams)
            walls = find_intersecting_elements(doc, beam, BuiltInCategory.OST_Walls)
            for wall in walls:
                res = ensure_join_and_order(doc, cutting_elem=wall, cut_elem=beam)
                if res in ("joined", "switched"):
                    stats["col_wall_cut_beam"] += 1

            # 3. Dầm chính cắt Dầm phụ (Main Girder cuts Secondary Beam)
            other_beams = find_intersecting_elements(doc, beam, BuiltInCategory.OST_StructuralFraming)
            for ob in other_beams:
                ob_id = ob.Id.IntegerValue if hasattr(ob.Id, 'IntegerValue') else int(ob.Id.ToString())
                if ob_id == beam_id:
                    continue
                pair_key = (min(beam_id, ob_id), max(beam_id, ob_id))
                if pair_key in processed_beam_pairs:
                    continue
                processed_beam_pairs.add(pair_key)

                # So sánh tiết diện để quyết định dầm nào là Dầm chính
                if get_beam_volume_rank(beam) >= get_beam_volume_rank(ob):
                    res = ensure_join_and_order(doc, cutting_elem=beam, cut_elem=ob)
                else:
                    res = ensure_join_and_order(doc, cutting_elem=ob, cut_elem=beam)
                
                if res in ("joined", "switched"):
                    stats["main_beam_cut_sec_beam"] += 1

        # ----------------------------------------------------------------------
        # BƯỚC C: Xử lý Join cho Sàn (Cột, Vách và Dầm đều cắt Sàn)
        # ----------------------------------------------------------------------
        for slab in slabs_on_level:
            # 1. Cột cắt Sàn
            for col in find_intersecting_elements(doc, slab, BuiltInCategory.OST_StructuralColumns):
                if ensure_join_and_order(doc, cutting_elem=col, cut_elem=slab) in ("joined", "switched"):
                    stats["col_wall_cut_slab"] += 1

            # 2. Vách cứng cắt Sàn
            for wall in find_intersecting_elements(doc, slab, BuiltInCategory.OST_Walls):
                if ensure_join_and_order(doc, cutting_elem=wall, cut_elem=slab) in ("joined", "switched"):
                    stats["col_wall_cut_slab"] += 1

            # 3. Dầm cắt Sàn
            for beam in find_intersecting_elements(doc, slab, BuiltInCategory.OST_StructuralFraming):
                if ensure_join_and_order(doc, cutting_elem=beam, cut_elem=slab) in ("joined", "switched"):
                    stats["beam_cut_slab"] += 1

        # ----------------------------------------------------------------------
        # BƯỚC D: Dọn dẹp các cảnh báo "Highlighted elements are joined but do not intersect"
        # ----------------------------------------------------------------------
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
        return {"status": "success", "level": level_name, "join_summary": stats}

    except Exception as ex:
        t.RollBack()
        return {"status": "error", "message": str(ex)}
