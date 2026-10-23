# Sổ Tay Kỹ Thuật Revit Structural API & Cốt Thép 3D (Revit 2024–2027)

Tài liệu tham khảo chuyên sâu về giải thuật hình học, khởi tạo cấu kiện và tự động hóa cốt thép trong Autodesk Revit API, tích hợp tinh hoa từ các open-source repositories hàng đầu thế giới:
- **`kevinzurro/JumpForRevit`**: Add-in kết cấu C#, tự động hóa chi tiết Cột, Dầm, Tường, Sàn, Móng; bóc tách Solid/BoundingBox tính Cover và sinh Rebar 3D kèm mặt cắt chi tiết.
- **`KonkovDV/OpenRebar`**: Thuật toán bố trí cốt thép tự động qua `Rebar.CreateFromCurves`, theo dõi hình dạng uốn (bending-shape tracking) và tự động gắn Tag (`IndependentTag.Create`).
- **`m-wolin/PyRebar`**: Bộ công cụ Python / pyRevit chuyên về hiển thị thép xuyên bê tông (Unobscured/Solid 3D), đảo chiều móc (Reverse hook), tính hàm lượng thép ($\mu\%$) trên thể tích bê tông và kiểm toán chiều dài thanh.
- **`eibre/EiBreRebarUtils`**: Copy cốt thép giữa cấu kiện tuyến tính (dầm sang dầm, tường sang tường), tự phát sinh thép góc uốn (Rebar in Bend), phân tích cú pháp chuỗi text ("ø12c200").
- **`jeremytammik/RevitSdkSamples`**:
  - `Reinforcement`: Tạo tự động thép đai (Stirrups) và thép chủ (Longitudinal bars) từ hình học tiết diện dầm/cột.
  - `NewRebar`: Quản lý RebarShape (móc 90/135/180 độ) và ràng buộc RebarConstraintsManager vào mặt bê tông.
  - `FrameBuilder`: Tạo hàng loạt Cột & Dầm theo Grid & Level, tự động Duplicate FamilySymbol theo kích thước $b \times h$.
- **`BHoM/Revit_Toolkit`**: Chuyển đổi Line/Curve sang Beam, Column, Wall; xử lý Justification, Level Offset và xoay góc cột (`ElementTransformUtils.RotateElement`).
- **`specklesystems/speckle-sharp-connectors`**: Kích hoạt FamilySymbol (`!symbol.IsActive -> symbol.Activate()`), xử lý cột xiên (Slanted Column) và tường cong/vát.

---

## 1. Kiến Trúc 4 Nhóm API Khởi Tạo Cốt Lõi

### ① Tạo Tường Kết Cấu (Structural Wall)
Tường là System Family trong Revit nên không thể dùng `NewFamilyInstance`, mà bắt buộc phải dùng static method `Wall.Create()`:

```python
# Python / pyRevit
# location_curve: Line hoặc Arc
# structural: True (Bắt buộc để tường có tính năng chịu lực và làm Host cho Rebar)
wall = DB.Wall.Create(
    doc,
    location_curve,
    wall_type_id,
    base_level_id,
    height_in_feet, # Chiều cao tường = (top_level.Elevation - base_level.Elevation)
    base_offset_ft,
    False,          # flip
    True            # structural = True
)

# Thiết lập ràng buộc đỉnh (Top Constraint) thay vì Unconnected Height
top_param = wall.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE)
if top_param and not top_param.IsReadOnly:
    top_param.Set(top_level_id)
top_offset_param = wall.get_Parameter(DB.BuiltInParameter.WALL_TOP_OFFSET)
if top_offset_param and not top_offset_param.IsReadOnly:
    top_offset_param.Set(0.0)
```

```csharp
// C# tương đương
Wall wall = Wall.Create(
    doc,
    locationCurve,
    wallTypeId,
    baseLevelId,
    heightInFeet,
    baseOffset,
    flip: false,
    structural: true
);
```

---

### ② Tạo Dầm (Beam) & Cột (Column)
Cả Dầm và Cột đều là `FamilyInstance`, được tạo qua `doc.Create.NewFamilyInstance()`, nhưng khác nhau căn bản ở kiểu hình học và `StructuralType`:

#### A. Kích hoạt FamilySymbol trước khi đặt (Guardrail từ Speckle & FrameBuilder):
```python
if not symbol.IsActive:
    symbol.Activate()
    doc.Regenerate()
```

#### B. Tạo Dầm Kết Cấu (`StructuralType.Beam`):
Truyền vào đường trục Curve (từ điểm đầu đến điểm cuối) và Level tham chiếu:
```python
# line: DB.Line.CreateBound(start_pt, end_pt)
beam = doc.Create.NewFamilyInstance(
    line,
    beam_symbol,
    reference_level,
    DB.Structure.StructuralType.Beam
)
# Cao độ dầm căn chỉnh qua Start/End Level Offset
beam.get_Parameter(DB.BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION).Set(start_offset)
beam.get_Parameter(DB.BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION).Set(end_offset)
```

#### C. Tạo Cột Thẳng Đứng (`StructuralType.Column`):
Truyền vào điểm tâm `XYZ`, `FamilySymbol`, `base_level`:
```python
col = doc.Create.NewFamilyInstance(
    point_xyz,
    col_symbol,
    base_level,
    DB.Structure.StructuralType.Column
)
# Thiết lập Top Level & Base/Top Offset
col.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM).Set(top_level.Id)
col.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(0.0)
col.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM).Set(0.0)

# Xoay góc cột (nếu cột đặt phương ngang hoặc nghiêng theo trục công trình):
if rotation_angle != 0.0:
    axis = DB.Line.CreateBound(point_xyz, DB.XYZ(point_xyz.X, point_xyz.Y, point_xyz.Z + 10.0))
    DB.ElementTransformUtils.RotateElement(doc, col.Id, axis, rotation_angle)
```

#### D. Tạo Cột Xiên / Nghiêng (Slanted Column):
Truyền một đường thẳng `Line` nối từ chân cột lên đỉnh cột:
```python
slanted_line = DB.Line.CreateBound(base_pt, top_pt)
slanted_col = doc.Create.NewFamilyInstance(
    slanted_line,
    col_symbol,
    base_level,
    DB.Structure.StructuralType.Column
)
```

---

### ③ Phân Tích Hình Học Host & Thiết Lập Lớp Bê Tông Bảo Vệ (Cover)
Kế thừa từ `JumpForRevit` và `Reinforcement`:
Để rải cốt thép chính xác vào lõi bê tông, ta lấy BoundingBox và Transform của cấu kiện:

```python
def get_column_core_curves(col, cover_ft):
    """
    Tính toán chu vi đường bao cốt đai trong cột chữ nhật dựa trên kích thước b, h và lớp cover.
    """
    # Lấy Transform để chuyển đổi hệ toạ độ từ Local sang World Coordinates (WCS)
    tf = col.GetTransform()
    origin = tf.Origin
    basis_x = tf.BasisX
    basis_y = tf.BasisY
    basis_z = tf.BasisZ

    col_type = doc.GetElement(col.GetTypeId())
    b_ft = col_type.get_Parameter(DB.BuiltInParameter.GENERIC_WIDTH).AsDouble()
    h_ft = col_type.get_Parameter(DB.BuiltInParameter.GENERIC_DEPTH).AsDouble()

    # Kích thước lõi thép (trừ cover 2 bên)
    half_b = (b_ft / 2.0) - cover_ft
    half_h = (h_ft / 2.0) - cover_ft

    # 4 đỉnh hình chữ nhật lõi
    p1 = origin + basis_x * (-half_b) + basis_y * (-half_h)
    p2 = origin + basis_x * ( half_b) + basis_y * (-half_h)
    p3 = origin + basis_x * ( half_b) + basis_y * ( half_h)
    p4 = origin + basis_x * (-half_b) + basis_y * ( half_h)

    curves = [
        DB.Line.CreateBound(p1, p2),
        DB.Line.CreateBound(p2, p3),
        DB.Line.CreateBound(p3, p4),
        DB.Line.CreateBound(p4, p1)
    ]
    return curves, basis_z # normal vector là trục dọc cột
```

---

### ④ Khởi Tạo Cốt Thép & Thiết Lập Dải Thép (Rebar & Rebar Set)
Kế thừa từ `OpenRebar`, `PyRebar` & `RevitSdkSamples/NewRebar`:

#### A. Khởi tạo thanh thép chuẩn từ Curves:
```python
def create_rebar_stirrup(doc, host, bar_type, curves, normal_vector, hook_type):
    """
    Tạo cốt đai (StirrupTie) khép kín
    """
    rebar = DB.Structure.Rebar.CreateFromCurves(
        doc,
        DB.Structure.RebarStyle.StirrupTie,
        bar_type,
        hook_type,  # Start Hook (ví dụ 135 độ)
        hook_type,  # End Hook (ví dụ 135 độ)
        host,
        normal_vector,
        curves,
        DB.Structure.RebarHookOrientation.Left,
        DB.Structure.RebarHookOrientation.Left,
        True,       # useExistingShapeIfPossible
        True        # createNewShape
    )
    return rebar
```

#### B. Biến 1 thanh thép thành 1 Dải thép (Rebar Set) qua RebarShapeDrivenAccessor:
> [!IMPORTANT]
> Tuyệt đối **không** dùng vòng lặp tạo hàng trăm thanh đơn lẻ. Phải sử dụng `GetShapeDrivenAccessor()` để Revit tự quản lý mảng thép tối ưu hiệu năng:

```python
# 1. Rải theo khoảng cách tối đa (Maximum Spacing), ví dụ: đai dày a100mm, đai thưa a200mm
accessor = rebar.GetShapeDrivenAccessor()
spacing_ft = 150.0 / 304.8 # 150mm
array_length_ft = 2400.0 / 304.8 # Chiều dài đoạn rải 2400mm

accessor.SetLayoutAsMaximumSpacing(
    spacing_ft,
    array_length_ft,
    True, # barsOnNormalSide
    True, # includeFirstBar
    True  # includeLastBar
)

# 2. Rải theo số lượng thanh cố định (Fixed Number), ví dụ: 4 cây thép chủ dầm:
accessor.SetLayoutAsFixedNumber(
    4,                # 4 bars
    array_length_ft,
    True,
    True,
    True
)
```

#### C. Tự Động Đặt Tag Ngay Sau Khi Rải Thép (Từ OpenRebar):
```python
def tag_rebar(doc, view, rebar, tag_symbol):
    ref = DB.Reference(rebar)
    bb = rebar.get_BoundingBox(view)
    center = (bb.Min + bb.Max) / 2.0
    tag = DB.IndependentTag.Create(
        doc,
        view.Id,
        ref,
        False, # addLeader
        DB.TagMode.TM_ADDBY_CATEGORY,
        DB.TagOrientation.Horizontal,
        center
    )
    if tag_symbol:
        tag.ChangeTypeId(tag_symbol.Id)
    return tag
```

---

## 2. Kỹ Thuật Hiển Thị & Kiểm Toán Thực Chiến (PyRebar & EiBre)

### 2.1 Hiển Thị Khối Đặc 3D & Nhìn Xuyên Bê Tông:
```python
def make_rebar_fully_visible_in_view(doc, rebar, view_3d):
    # Nhìn xuyên bê tông
    rebar.SetUnobscuredInView(view_3d, True)
    # Hiển thị khối đặc 3D (Solid)
    rebar.SetSolidInView(view_3d, True)
```

### 2.2 Đảo Hướng Móc Cốt Thép Tự Động:
```python
def toggle_rebar_hook_orientation(rebar):
    curr_start = rebar.GetHookOrientation(0)
    new_start = DB.Structure.RebarHookOrientation.Left if curr_start == DB.Structure.RebarHookOrientation.Right else DB.Structure.RebarHookOrientation.Right
    rebar.SetHookOrientation(0, new_start)
```

### 2.3 Tính Hàm Lượng Thép Trên Thể Tích Bê Tông ($\mu\%$):
$$\mu\% = \frac{V_{\text{steel}}}{V_{\text{concrete}}} \times 100\%$$
- Cột chịu nén: $\mu = 0.8\% - 3.5\%$.
- Dầm chịu uốn: $\mu = 0.2\% - 2.0\%$.

```python
def audit_element_rebar_ratio(element, rebars_in_element):
    geom_elem = element.get_Geometry(DB.Options())
    concrete_vol = 0.0
    for obj in geom_elem:
        if isinstance(obj, DB.Solid) and obj.Volume > 0:
            concrete_vol += obj.Volume
            
    total_rebar_vol = 0.0
    for r in rebars_in_element:
        # Volume của từng thanh Rebar
        vol_p = r.get_Parameter(DB.BuiltInParameter.REBAR_VOLUME)
        if vol_p:
            total_rebar_vol += vol_p.AsDouble()
            
    if concrete_vol > 0:
        ratio = (total_rebar_vol / concrete_vol) * 100.0
        return round(ratio, 2)
    return 0.0
```

---

## 3. Bảng Quy Cách & Trọng Lượng Thép Tiêu Chuẩn

$$q = \frac{d^2 (\text{mm})}{162.2} \quad (\text{kg/m})$$

| Đường Kính ($\Phi$) | Trọng lượng đơn vị ($kg/m$) | Diện tích ($mm^2$) | Ứng dụng kết cấu chuẩn |
| :--- | :--- | :--- | :--- |
| **D10 / N10** | $0.617$ | $78.5$ | Cốt đai dầm/cột, cốt thép sàn dân dụng |
| **D12 / N12** | $0.888$ | $113.1$ | Thép gia cường mũ sàn, đai dầm tải trọng lớn |
| **D16 / N16** | $1.578$ | $201.1$ | Thép chủ dầm phụ, thép cột nhỏ, thép đài móng PF1 |
| **D20 / N20** | $2.466$ | $314.2$ | Thép chủ cột CC3, CC4A, thép đài móng PF2, PF3, PF4 |
| **D25 / N25** | $3.853$ | $490.9$ | Thép chủ cột nhà cao tầng, đài móng khối lớn |
| **D32 / N32** | $6.313$ | $804.2$ | Dầm chuyển (Transfer girder), móng bè sâu |

---

## 4. Danh Sách Repository Tham Khảo Đầy Đủ

1. **`kevinzurro/JumpForRevit`**: [github.com/kevinzurro/JumpForRevit](https://github.com/kevinzurro/JumpForRevit)
2. **`KonkovDV/OpenRebar`**: [github.com/KonkovDV/OpenRebar](https://github.com/KonkovDV/OpenRebar)
3. **`m-wolin/PyRebar`**: [github.com/m-wolin/PyRebar](https://github.com/m-wolin/PyRebar)
4. **`eibre/EiBreRebarUtils`**: [github.com/eibre/EiBreRebarUtils](https://github.com/eibre/EiBreRebarUtils)
5. **`jeremytammik/RevitSdkSamples`**: [github.com/jeremytammik/RevitSdkSamples](https://github.com/jeremytammik/RevitSdkSamples)
6. **`BHoM/Revit_Toolkit`**: [github.com/BHoM/Revit_Toolkit](https://github.com/BHoM/Revit_Toolkit)
7. **`specklesystems/speckle-sharp-connectors`**: [github.com/specklesystems/speckle-sharp-connectors](https://github.com/specklesystems/speckle-sharp-connectors)
