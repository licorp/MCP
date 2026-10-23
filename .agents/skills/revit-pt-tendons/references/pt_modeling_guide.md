# Post-Tensioning (PT / UCL) Tendon Modeling & Annotation Guide in Revit

Tài liệu hướng dẫn chi tiết về kỹ thuật mô hình hóa 3D Cáp Ứng Lực (UCL / Post-Tensioning Tendons) và thể hiện bản vẽ mặt bằng 2D trong Autodesk Revit từ dữ liệu AutoCAD DWG.

---

## 1. Nguyên lý Hình học & Cao độ Ghế kê CGS

### 1.1 Khái niệm CGS (Center of Gravity of Steel)
- **CGS** là khoảng cách tính bằng milimét (mm) từ đáy sàn (Slab Soffit) lên đến trọng tâm bó cáp thép dự ứng lực.
- Cao độ đáy sàn:
  $$Z_{\text{soffit}} = Z_{\text{slab\_top}} - \text{SlabThickness}$$
- Cao độ tuyệt đối tại từng điểm ghế kê / uốn cáp thứ $i$:
  $$Z_i = Z_{\text{soffit}} + CGS_i$$
- Đổi sang đơn vị nội bộ Revit (feet):
  $$Z_{\text{internal}} = \frac{Z_i (\text{mm})}{304.8}$$

### 1.2 Các vị trí CGS điển hình
- **Điểm võng lớn nhất (Giữa nhịp / Mid-span)**: $30\text{ mm} - 50\text{ mm}$ (ví dụ ghế kê $30\text{ mm}, 40\text{ mm}$).
- **Điểm gối / Đỉnh dầm / Cột (Supports)**: Gần lớp bê tông bảo vệ trên, ví dụ $230\text{ mm} - 350\text{ mm}$.
- **Đầu neo sống / chết (Anchorage Live/Dead Ends)**: Thường nằm ở giữa chiều dày sàn, ví dụ $115\text{ mm} - 160\text{ mm}$.

---

## 2. Hệ Toạ độ & Chuyển đổi Hình học CAD $\rightarrow$ Revit

### 2.1 Ma trận Chuyển đổi 2D (Rigid Transformation)
Khi bản vẽ CAD và mô hình Revit có góc xoay dự án (Project North vs True North) và độ lệch gốc toạ độ:
$$\begin{pmatrix} X_{\text{revit}} \\ Y_{\text{revit}} \end{pmatrix} = \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix} \begin{pmatrix} X_{\text{cad}} / 304.8 \\ Y_{\text{cad}} / 304.8 \end{pmatrix} + \begin{pmatrix} T_x \\ T_y \end{pmatrix}$$
- **Phương pháp xác định**: Khớp toạ độ của ít nhất 2 giao điểm trục kết cấu (ví dụ Trục 1-A và 1-G).

---

## 3. Tạo Mô hình 3D DirectShape trong Revit API

### 3.1 Đường cong Spline uốn lượn (HermiteSpline)
- Sử dụng `DB.HermiteSpline.Create(List[XYZ], False)` với cờ `False` (đường cong hở).
- Đảm bảo độ trơn liên tục bậc 1 ($C^1$) phù hợp đường dẹp parabol thực tế của cáp DUL.

### 3.2 Quy tắc Xử lý Khoảng cách Điểm (Tolerance Rule)
- **Lưu ý quan trọng**: Revit API ném lỗi ngoại lệ `Exception: Curve length is too small` nếu khoảng cách giữa 2 điểm liên tiếp $< 1/16\text{ in} \approx 1.6\text{ mm}$.
- **Giải pháp**: Lọc bỏ mọi điểm liền kề có khoảng cách $< 20\text{ mm}$ ($0.065\text{ ft}$) trước khi tạo Spline.

### 3.3 Thiết lập DirectShape & Tham số
- **Category**: `DB.BuiltInCategory.OST_GenericModel`.
- **Gán thông tin**:
  - `Mark`: Mã định danh cáp (`PT-01`, `PT-02`, ...).
  - `Comments`: Toàn bộ chuỗi mặt cắt cao độ CGS (ví dụ: `CGS (mm): 115 -> 250 -> 350 -> 40 -> 350 -> 40 -> 140`).

---

## 4. Thiết lập View 3D Nhìn Xuyên Bê Tông

- **Tên View**: Tuyệt đối không dùng ký tự ngoặc nhọn `{}` vì Revit cấm (dùng `3D - PT TENDONS B1`).
- **Độ trong suốt (Surface Transparency)**: Đặt độ trong suốt của các đối tượng bê tông (`OST_Floors`, `OST_Walls`, `OST_StructuralFraming`, `OST_StructuralColumns`) lên $80\%$.
- **Màu nét sợi cáp**: Override màu của `OST_GenericModel` sang màu Đỏ cánh sen (Magenta `RGB 255, 0, 128`), nét dày 4 để nhìn rõ từ mọi góc phối cảnh.

---

## 5. Thể hiện Bản vẽ Mặt bằng 2D (Plan View) Chuẩn AutoCAD 1:1

### 5.1 Giới hạn của 3D Curve trong Floor Plan
- DirectShape dạng 3D Curve đơn lẻ không có thể tích đặc (solid volume) nên **không bị cắt bởi Cut Plane** trong chế độ hiển thị `Hidden Line` / `Shaded` của mặt bằng sàn Revit.
- **Giải pháp chuẩn**: Tạo các đường nét 2D `DetailCurve` trực tiếp trên View mặt bằng chuyên biệt.

### 5.2 Quy tắc Màu sắc & Hướng tuyến Cáp
Theo đúng quy chuẩn thể hiện bản vẽ Shopdrawing PT từ AutoCAD:
1. **Phương Ngang (Horizontal trên màn hình)**:
   - Tuyến cáp: Nét `DetailCurve` màu **Xanh lá** (`PT Tendon - Green`, RGB 0, 175, 0, weight 4).
   - Vạch gạch chỉ thị (Tick marks): Đường ngắn $200\text{ mm}$ vuông góc màu **Vàng** (`PT Tick - Yellow`, RGB 215, 145, 0, weight 3).
   - Nhãn cao độ CGS: Chữ màu **Vàng** (`PT - CGS Elevation 2.5mm YELLOW`), xoay **chạy ngang song song theo sợi cáp** (`BaseDirection = View.RightDirection`).
2. **Phương Đứng (Vertical trên màn hình)**:
   - Tuyến cáp: Nét `DetailCurve` màu **Đỏ** (`PT Tendon - Red`, RGB 230, 20, 20, weight 4).
   - Vạch gạch chỉ thị (Tick marks): Đường ngắn $200\text{ mm}$ vuông góc màu **Xanh dương** (`PT Tick - Blue`, RGB 0, 0, 230, weight 3).
   - Nhãn cao độ CGS: Chữ màu **Xanh dương** (`PT - CGS Elevation 2.5mm BLUE`), xoay **chạy đứng dọc theo sợi cáp** (`BaseDirection = View.UpDirection`).

### 5.3 Xoay Text theo Scope Box (Chống Xiên / Lệch Chữ)
- Khi View mặt bằng được gán `Scope Box`, Revit tự động căn trục hoành của khung nhìn song song với cạnh dài của Scope Box (`View.RightDirection`).
- Khi gọi `DB.TextNote.Create(doc, view.Id, origin, txt, typeId)`, chữ được sinh ra đã có `BaseDirection` song song với `View.RightDirection`.
- **Để xoay chữ theo phương đứng (Vertical)**:
  - Tính góc chênh lệch:
    $$\Delta\theta = \text{atan2}(V_{\text{up}}.Y, V_{\text{up}}.X) - \text{atan2}(\text{BaseDirection}.Y, \text{BaseDirection}.X)$$
  - Gọi `DB.ElementTransformUtils.RotateElement(doc, tn.Id, axis, \Delta\theta)`.
  - Tuyệt đối không cộng thêm góc xoay Scope Box vào lần nữa vì sẽ gây lệch $90^\circ$ (chữ bị xiên $45^\circ$).
