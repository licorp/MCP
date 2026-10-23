---
name: revit-pt-tendons
description: >-
  Tự động hóa toàn diện quy trình mô hình hóa Cáp Ứng Lực (UCL / Post-Tensioning tendons / Cáp DUL)
  từ bản vẽ AutoCAD DWG vào Autodesk Revit: trích xuất toạ độ 2D & cao độ ghế kê CGS, khớp hệ toạ độ dự án,
  tạo mô hình cáp 3D DirectShape HermiteSpline chuẩn parabol, gán tham số CGS chain (Mark, Comments),
  tạo view 3D nhìn xuyên bê tông, và tự động vẽ cáp 2D (DetailCurve), vạch gạch chỉ thị (Tick marks 200mm),
  cùng nhãn cao độ CGS (TextNote) xoay song song theo Scope Box và đúng phương của từng sợi cáp.
  Tuân thủ chuẩn BIM SOP, Revit API 2024-2027 (ForgeTypeId, Transaction an toàn) và tự kiểm thử qua MCP.
---

# Quy Trình Tự Động Hóa Cáp Ứng Lực (UCL / Post-Tensioning) CAD $\rightarrow$ Revit

Skill này đóng gói quy trình chuẩn hóa (BIM Standard Operating Procedure - SOP) từ bản vẽ Shopdrawing AutoCAD DWG sang Autodesk Revit thông qua Revit MCP Server:
1. **Truy vấn tiền kiểm tra (Pre-flight Inspection SOP)**: Tự động kiểm tra trạng thái Revit, Document hiện hành, View mục tiêu, Level và Scope Box trước khi thực thi.
2. **Dựng mô hình cáp 3D (DirectShape Generic Models)**: Uốn lượn hình sin/parabol chính xác tuyệt đối theo chuỗi cao độ ghế kê CGS (Center of Gravity of Steel), tuân thủ giới hạn dung sai Revit API 2024–2027.
3. **Thiết lập khung nhìn 3D trực quan**: Độ trong suốt bê tông $80\%$, sợi cáp màu Magenta nổi bật để quan sát mạng lưới cáp trong sàn.
4. **Thể hiện bản vẽ mặt bằng 2D chuẩn xác 1:1 theo AutoCAD**:
   - Vẽ lại đầy đủ các tuyến cáp 2D bằng nét màu sắc nét.
   - Thêm vạch gạch ngắn vuông góc (Tick mark $200\text{ mm}$) tại từng điểm ghế kê uốn cáp.
   - Đặt nhãn ghi chú cao độ CGS (TextNote $2.5\text{ mm}$) chạy dọc song song theo từng phương sợi cáp và thẳng góc theo Scope Box.
5. **Tự kiểm thử & Hậu kiểm (Post-flight Verification)**: Kiểm đếm số lượng phần tử đã sinh và chụp ảnh view kiểm chứng trực quan trước khi báo hoàn thành.

---

## 1. Cấu Trúc Thư Mục Skill

```
skills/revit-pt-tendons/ (hoặc skills/ucl/)
├── SKILL.md                          # Hướng dẫn quy trình tổng thể & quy chuẩn BIM SOP
├── references/
│   └── pt_modeling_guide.md          # Chi tiết kỹ thuật Revit API, dung sai & toán học toạ độ
└── scripts/
    ├── extract_cad_pt.py             # Trích xuất polylines & text cao độ từ DWG qua headless AutoCAD
    ├── align_coordinates.py          # Tính ma trận chuyển toạ độ CAD (mm) -> Revit (ft)
    ├── generate_3d_tendons.py        # Tính toạ độ 3D parabol dựa trên cao độ đáy sàn & CGS
    ├── import_to_revit.py            # Tạo DirectShape 3D HermiteSpline & gán tham số (Mark, Comments)
    ├── place_pt_annotations.py       # Vẽ cáp 2D, vạch gạch và đặt nhãn TextNote đúng màu, đúng hướng
    └── run_ucl_workflow.py           # Script tổng điều phối toàn bộ workflow
```

---

## 2. Quy Định Màu Sắc & Hướng Chữ Chuẩn (CAD Standard 1:1)

Hệ thống cáp và nhãn cao độ được chuẩn hóa nghiêm ngặt:

| Thành phần | Phương Ngang (Horizontal trên màn hình) | Phương Đứng (Vertical trên màn hình) |
| :--- | :--- | :--- |
| **Tuyến cáp 2D** | **Màu Xanh lá** (`PT Tendon - Green`, RGB 0, 175, 0, nét 4) | **Màu Đỏ** (`PT Tendon - Red`, RGB 230, 20, 20, nét 4) |
| **Vạch gạch ngắn (Tick)** | **Màu Vàng** (`PT Tick - Yellow`, RGB 215, 145, 0, dài $200\text{ mm}$) | **Màu Xanh dương** (`PT Tick - Blue`, RGB 0, 0, 230, dài $200\text{ mm}$) |
| **Chữ cao độ CGS** | **Màu Vàng** (`PT - CGS Elevation 2.5mm YELLOW`) | **Màu Xanh dương** (`PT - CGS Elevation 2.5mm BLUE`) |
| **Hướng xoay của Chữ** | Chạy **Ngang** song song theo sợi cáp xanh (`View.RightDirection`) | Chạy **Đứng** dọc theo sợi cáp đỏ (`View.UpDirection`) |
| **Độ khớp Scope Box** | Thẳng hàng $100\%$ theo Scope Box | Thẳng hàng $100\%$ theo Scope Box |

---

## 3. Quy Trình Thực Hiện Chuẩn BIM SOP

### Bước 0: Tiền kiểm tra qua MCP (Pre-flight Inspection)
Trước khi thực hiện bất kỳ lệnh sửa đổi mô hình nào, AI Agent **bắt buộc** phải truy vấn trạng thái thực tế:
1. Gọi `GET /revit_mcp/status/` để xác nhận kết nối Revit sẵn sàng và tên tài liệu hiện hành (`doc.Title`).
2. Xác minh Floor Plan View mục tiêu (ví dụ `BUILDING 1 - GROUND POST TENSIONING`) và Scope Box gán kèm.
3. Kiểm tra cao độ mặt trên sàn ($Z_{\text{top}}$) và chiều dày sàn ($T$) để tính chính xác cao độ đáy sàn ($Z_{\text{soffit}} = Z_{\text{top}} - T$).

### Bước 1: Trích xuất Dữ liệu từ AutoCAD DWG
Sử dụng AutoCAD Core Console (`accoreconsole.exe`) để chạy trích xuất tự động không cần mở giao diện AutoCAD:
```bash
python scripts/extract_cad_pt.py "<đường_dẫn_dwg>" "scratch/cad_pt_data.json" [min_x min_y max_x max_y]
```
- Lớp tuyến cáp CAD: `CABLES` (phương ngang), `CABLES1` (phương đứng).
- Lớp cao độ CGS: `PROFILE1` (chữ vàng), `Profile X HL` / `PROFILE` (chữ xanh).

### Bước 2: Khớp Hệ Toạ Độ CAD $\rightarrow$ Revit
Xác định ít nhất 2 điểm mốc lưới trục giao nhau (ví dụ Trục 1-A và 1-G):
- Tính góc xoay $\theta$ và vector dịch chuyển $(T_x, T_y)$.
- Công thức chuyển đổi ma trận:
  $$\begin{pmatrix} X_{\text{revit}} \\ Y_{\text{revit}} \end{pmatrix} = \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix} \begin{pmatrix} X_{\text{cad}} / 304.8 \\ Y_{\text{cad}} / 304.8 \end{pmatrix} + \begin{pmatrix} T_x \\ T_y \end{pmatrix}$$

### Bước 3: Tính Toán Toạ Độ 3D Parabol & Dung Sai API
- Tính cao độ từng điểm uốn: $Z_i = Z_{\text{soffit}} + CGS_i (\text{mm}) / 304.8$.
- **Quy tắc dung sai (Daniel Locatelli Standard)**: Lọc bỏ toàn bộ điểm liền kề cách nhau $< 20\text{ mm}$ ($0.065\text{ ft}$) để triệt tiêu lỗi giới hạn Revit API (`Curve length is too small`).

### Bước 4: Tạo Mô Hình Cáp 3D & Quản Lý Transaction An Toàn
Chạy script [import_to_revit.py](./scripts/import_to_revit.py) qua pyRevit MCP:
- Bọc toàn bộ quá trình dựng hình trong khối `try...except/finally` với `t = DB.Transaction(doc, "Generate 3D PT Tendons")`.
- Tạo `DB.HermiteSpline` trơn mượt nối qua các điểm 3D và đóng gói vào `DB.DirectShape` danh mục `OST_GenericModel`.
- Gán tham số:
  - `Mark`: `PT-01`, `PT-02`, ...
  - `Comments`: `CGS (mm): 115 -> 250 -> 350 -> 40 -> 350 -> 40 -> 140`
- Tự động tạo View `3D - PT TENDONS B1` với sàn bê tông trong suốt $80\%$, sợi cáp màu Magenta nổi bật.

### Bước 5: Thể Hiện Mặt Bằng 2D & Đặt Nhãn Cao Độ CGS
Chạy script [place_pt_annotations.py](./scripts/place_pt_annotations.py):
```bash
python scripts/place_pt_annotations.py "scratch/pt_annotations_complete.json" "scratch/b1_cables_revit_2d.json" "BUILDING 1 - GROUND POST TENSIONING"
```
- Cơ chế `clear_existing=True` dọn dẹp các nét/nhãn cũ trước khi vẽ mới, tránh vẽ đè.
- Vẽ toàn bộ 2D `DetailCurve` cáp ngang (Xanh lá) và cáp đứng (Đỏ).
- Vẽ các vạch gạch ngắn $200\text{ mm}$ màu Vàng / Xanh vuông góc với sợi cáp.
- Tạo `TextNote` cao độ CGS với cỡ chữ $2.5\text{ mm}$, xoay chạy dọc song song theo sợi cáp và thẳng thắn theo Scope Box.

### Bước 6: Tự Kiểm Thử Sau Thực Thi (Post-flight Verification)
- Truy vấn số lượng đối tượng sinh ra (`created_cables`, `created_ticks`, `created_texts`).
- Xuất hình ảnh kiểm chứng (view screenshot/crop) để xác nhận chữ không bị xiên và màu sắc khớp $100\%$ với quy định trước khi báo cáo hoàn thành.

---

## 4. Các Lưu Ý Kỹ Thuật (Anti-Hallucination & Revit API Rules)

1. **Hiển thị Mặt bằng Sàn (Floor Plan)**:
   - Các DirectShape chỉ gồm đường Curve 3D **không hiển thị** trên mặt bằng sàn ở chế độ Hidden Line vì không có thể tích cắt. Việc kết hợp 2D `DetailCurve` là bắt buộc.
2. **Xoay Chữ Theo Scope Box**:
   - Khi View có Scope Box xoay góc, lệnh `TextNote.Create` mặc định đã tạo chữ song song với phương ngang của Scope Box (`View.RightDirection`).
   - Để xoay chữ theo phương đứng, chỉ cần xoay thêm góc `View.UpDirection - tn.BaseDirection`, không được cộng thêm góc xoay Scope Box lần thứ hai.
3. **Revit 2024–2027 Cross-Version Compatibility**:
   - ElementId trong Revit 2024+ dùng `Id.Value` (kiểu `Int64`), trong khi Revit 2023 trở về trước dùng `Id.IntegerValue`. Luôn sử dụng hàm bọc tương thích hoặc chuyển sang `str(Id)`.
   - Không sử dụng `ParameterType` đã bị xóa bỏ; sử dụng `GetDataType()` / `ForgeTypeId`.
   - Tránh đặt tên View chứa ký tự cấm `{}` (như `{3D - PT TENDONS}`).
