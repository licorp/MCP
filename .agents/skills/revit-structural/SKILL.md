---
name: revit-structural
description: >-
  Tự động hóa toàn diện mô hình hóa Kết cấu (Structural BIM) trong Autodesk Revit qua MCP Server:
  tạo Cột (Structural Columns), Dầm (Structural Framing), Sàn (Floors), Vách (Walls), Móng (Foundations);
  gán mác bê tông và vật liệu; tự động mô hình hóa Cốt thép Rebar 3D (thép chủ, thép tăng cường gối/nhịp L/3, L/4,
  thép đai gia cường gối a100/a200, thép sàn 2 lớp); kiểm soát lớp bê tông bảo vệ (Rebar Cover);
  và trích xuất bảng thống kê khối lượng bê tông (m3) & cốt thép (kg). Tuân thủ Revit API 2024-2027 & TCVN/Eurocode.
---

# Quy Trình Tự Động Hóa Kỹ Thuật Kết Cấu (Revit Structural BIM & Rebar)

Skill này cung cấp bộ công cụ và quy chuẩn (BIM SOP) hoàn chỉnh dành cho Kỹ sư Kết cấu khi làm việc với Autodesk Revit thông qua MCP Server (`mcp-server-for-revit-python`):
1. **Dựng hình thô kết cấu tự động (Structural Elements Modeling)**: Cột, dầm, sàn, móng, vách từ toạ độ CAD, lưới trục hoặc bảng tính Excel/Etabs.
2. **Quản lý Thông số Vật liệu & Mác bê tông**: Tự động gán mác bê tông (B20, B25, B30, B35, C25/30, C30/37) và cấp độ bền thép (CB240-T, CB300-V, CB400-V, CB500-V).
3. **Mô hình hóa Cốt thép Rebar 3D tự động (Rebar Automation)**: Rải cốt thép chủ, cốt thép tăng cường, cốt đai dầm/cột và thép sàn theo đúng nguyên lý thiết kế kết cấu (đoạn uốn neo $40d$, cắt thép gối $L/3$, nhịp $L/4$, đai dày ở gối).
4. **Kiểm toán mô hình & Bóc tách khối lượng (QTO)**: Xuất bảng thống kê khối lượng bê tông ($m^3$) và thống kê cốt thép ($kg$) phân loại theo đường kính và cấu kiện.

---

## 1. Cấu Trúc Thư Mục Skill

```
skills/revit-structural/
├── SKILL.md                          # Hướng dẫn tổng thể, quy chuẩn BIM SOP & lệnh gọi
├── references/
│   └── structural_api_guide.md       # Cẩm nang Revit Rebar API 2024-2027, tiêu chuẩn Cover & TCVN
└── scripts/
    ├── model_structural_elements.py  # Tạo cột, dầm, sàn, móng hàng loạt qua MCP
    ├── model_rebar.py                # Rải cốt thép dầm, cột, sàn tự động
    └── structural_qto.py             # Trích xuất khối lượng bê tông & bảng thống kê thép
```

### 1.1 Các Kho Mã Nguồn Mẫu & Cấu Trúc API Cốt Lõi
Skill kế thừa giải thuật và chuẩn hóa từ 7 kho mã nguồn hàng đầu:
1. **`kevinzurro/JumpForRevit`** & **`jeremytammik/RevitSdkSamples`** (`Reinforcement`, `NewRebar`, `FrameBuilder`): Trích xuất BoundingBox/Solid tính Cover, tự động tạo RebarShape/ConstraintsManager và nhân bản FamilySymbol $b \times h$.
2. **`KonkovDV/OpenRebar`** & **`eibre/EiBreRebarUtils`**: `Rebar.CreateFromCurves`, theo dõi uốn thép, copy thép giữa cấu kiện và tự động gắn Tag (`IndependentTag.Create`).
3. **`m-wolin/PyRebar`**: Bộ công cụ Python/pyRevit hiển thị thép xuyên bê tông (`SetUnobscuredInView`, `SetSolidInView`), đảo móc và tính hàm lượng thép $\mu\%$.
4. **`BHoM/Revit_Toolkit`** & **`specklesystems/speckle-sharp-connectors`**: Chuẩn hóa khởi tạo Dầm, Cột (thẳng đứng & xiên) và Tường kết cấu từ Line/Curve, kích hoạt Symbol (`!symbol.IsActive -> symbol.Activate()`).

#### Cấu trúc 4 nhóm API chính:
- **Tường kết cấu**: `Wall.Create(doc, locationCurve, wallTypeId, baseLevelId, heightInFeet, baseOffset, flip: false, structural: true)`
- **Dầm & Cột**: `doc.Create.NewFamilyInstance()` với `StructuralType.Beam` (Curve) hoặc `StructuralType.Column` (XYZ hoặc Line xiên).
- **Phân tích Host & Cover**: `FamilyInstance.GetTransform()`, `LocationCurve`, BoundingBox và `CLEAR_COVER_OTHER`.
- **Rebar & Rebar Set**: `Rebar.CreateFromCurves()` + `RebarShapeDrivenAccessor` (`SetLayoutAsMaximumSpacing` / `SetLayoutAsFixedNumber`).


---

## 2. Tiêu Chuẩn Kỹ Thuật & Quy Tắc Cốt Thép (Structural SOP)

### 2.1 Lớp Bê Tông Bảo Vệ (Rebar Cover Standards)
Theo TCVN 5574:2018 / Eurocode 2, lớp bảo vệ tối thiểu của các cấu kiện:

| Loại Cấu Kiện | Vị Trí / Bề Mặt | Chiều Dày Lớp Bảo Vệ (Cover) |
| :--- | :--- | :--- |
| **Bản sàn (Slabs)** | Bề mặt trên & dưới | $15\text{ mm} - 20\text{ mm}$ |
| **Dầm (Beams)** | Đáy dầm, mặt bên & đỉnh | $25\text{ mm} - 30\text{ mm}$ (tính đến mép ngoài thép đai) |
| **Cột (Columns)** | 4 mặt xung quanh | $25\text{ mm} - 35\text{ mm}$ (tính đến mép ngoài thép đai) |
| **Vách (Walls)** | 2 mặt vách | $20\text{ mm} - 25\text{ mm}$ |
| **Móng (Foundations)** | Tiếp xúc bê tông lót | $50\text{ mm}$ (nếu không lót: $70\text{ mm}$) |

### 2.2 Quy Tắc Bố Trí Cốt Thép Dầm Chuẩn Kỹ Thuật
1. **Thép chủ liên tục**:
   - Chạy suốt dầm qua các gối và nhịp.
   - Thép trên: neo vào cột/gối biên tối thiểu $30d - 40d$.
   - Thép dưới: neo vào cột biên tối thiểu $20d - 30d$.
2. **Thép gia cường gối (Top Support Reinforcement)**:
   - Đoạn vươn ra khỏi mép cột vào nhịp tối thiểu $L/3$ hoặc $L/4$ (trong đó $L$ là nhịp thông thủy).
3. **Thép gia cường nhịp (Bottom Mid-span Reinforcement)**:
   - Đoạn cách mép gối tối thiểu $0.15L - 0.2L$.
4. **Cốt đai (Stirrups)**:
   - **Vùng nối/ngàm gối (vùng dẻo)**: Chiều dài $2h$ (với $h$ là chiều cao dầm), khoảng cách đai dày: $a100$ hoặc $a150$.
   - **Vùng giữa nhịp**: Khoảng cách đai thưa: $a200$ hoặc $a250$.

---

## 3. Các Bước Thực Hiện Chuẩn

### Bước 0: Tiền kiểm tra qua MCP (Pre-flight Inspection)
Trước khi sinh cấu kiện, AI Agent kiểm tra:
1. Gọi `GET /revit_mcp/status/` để đảm bảo kết nối Revit khả dụng.
2. Kiểm tra danh sách tầng (`Levels`) và lưới trục (`Grids`) trong Document.
3. Kiểm tra xem Family Type cần dùng (ví dụ: `Concrete-Rectangular-Column`, `M_Concrete-Rectangular Beam`) đã được nạp vào dự án chưa.

### Bước 1: Dựng Khung Cấu Kiện Thô
Chạy script [model_structural_elements.py](./scripts/model_structural_elements.py):
```python
# Ví dụ tạo dầm (Structural Framing)
# Điểm bắt đầu p1, điểm kết thúc p2, Level, FamilySymbol
line = DB.Line.CreateBound(p1, p2)
beam = doc.Create.NewFamilyInstance(line, beam_symbol, level, DB.Structure.StructuralType.Beam)
```
- Tự động gán tham số mác bê tông vào `STRUCTURAL_MATERIAL_PARAM`.

### Bước 2: Thiết Lập Rebar Cover
Trước khi rải thép, thiết lập Cover Type cho phần tử:
```python
cover_param = element.get_Parameter(DB.BuiltInParameter.CLEAR_COVER_OTHER)
if cover_param:
    cover_param.Set(cover_type_id)
```

### Bước 3: Rải Cốt Thép Rebar 3D
Chạy script [model_rebar.py](./scripts/model_rebar.py):
- **Cốt đai**: Tạo đường curve hình chữ nhật theo chu vi lõi bê tông (trừ lớp cover) và gọi:
  ```python
  rebar = DB.Structure.Rebar.CreateFromCurves(doc, DB.Structure.RebarStyle.Standard, bar_type, hook_type, hook_type, host, norm, curves, start_hook_orient, end_hook_orient, True, True)
  rebar.GetShapeDrivenAccessor().SetLayoutAsMaximumSpacing(spacing_ft, array_length_ft, True, True, True)
  ```
- **Cốt chủ**: Rải thép dọc theo chiều dài cấu kiện, gán số lượng thanh bằng `SetLayoutAsFixedNumber(count, array_length_ft, True, True, True)`.

### Bước 4: Bóc Tách Khối Lượng (QTO)
Chạy script [structural_qto.py](./scripts/structural_qto.py):
- Quét toàn bộ cấu kiện `OST_StructuralFraming`, `OST_StructuralColumns`, `OST_Floors` để tính tổng thể tích bê tông ($m^3$).
- Quét toàn bộ `OST_Rebar` để tính tổng chiều dài từng đường kính ($\Phi10, \Phi12, \Phi16, \Phi20, \Phi25...$) và nhân với trọng lượng đơn vị ($kg/m = \frac{d^2}{162}$) để ra tổng khối lượng thép.

---

## 4. Chống Ảo Giác Revit Rebar API 2024–2027

1. **Rebar Shape & Curve**:
   - Từ Revit 2023+, ưu tiên sử dụng `Rebar.CreateFromCurves()` để tạo thép linh hoạt không phụ thuộc vào Family RebarShape có sẵn trong template.
2. **Đơn vị Rebar Length**:
   - Đường kính thanh trong Revit API là đơn vị feet (Internal unit). Cần chia cho $304.8$ khi nhập từ milimét.
3. **Transaction an toàn**:
   - Luôn đặt trong `try...except/finally` và `t.Commit()`.
