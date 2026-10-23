# Lịch sử làm việc — dự án HPCE 250793 (nhánh feat/auto-grid-calibration-slabs)

Gộp từ 3 phiên chat (20–22/10/2026). Đọc file này + `project_summary.md` để nắm toàn bộ bối cảnh.

## 1. Đã dựng trong model Revit

| Hạng mục | Zone A | Zone B |
|---|---|---|
| Móng (S201 / S202) | 38 móng đơn PF, 23 tường, móng băng SF1 (bổ sung 1 dải SF1 dưới W1 góc ĐB) | 30 móng đơn, 22 tường (tạo loại SW2 nhân bản từ SW1), 5 tấm SF |
| Tường cong | RW2 R1944 (tag S201-p19) | RW1 R3800 (tag S202-p20) |
| Cột tầng trệt (S204 / S205) | 39 cột | 33 cột (tạo loại CC2 - 500DIA) |
| Dầm tầng trệt | 0 (sàn trên nền, đúng) | 0 |
| Sàn S.O.G 100 mm | id 1916650, 1 393,65 m², 2 giếng thang | id 1916690, 1 313,16 m² |

- Kiểm tra trùng toàn model = 0. Tấm sàn tay 1912844 đã xóa.
- Mốc tọa độ: trang tổng S200 (móng) / S203 (tầng trệt), sai số 2,6–4 mm. KHÔNG dùng link kiến trúc (lệch 78–105 mm).
- Cao độ: GF 1.200, L01 4.300, L02 7.500, L03 10.700, ROOF 14.000; đỉnh móng RL 1.050 (= GF − 150, suy từ mặt cắt S100).
- Legend: mọi tường/cột ở móng + tầng trệt đều OVER → dựng GF → L01 là đúng.

### Tầng L1 (22/10) — L01 → L02

| Trang | Cột | Tường | Mốc tọa độ |
|---|---|---|---|
| S207 (Zone A) | 13 (CC4B×2, CC6, CC1B×3, CC5×7) | 20 (W1×14, SW1×3, LW1×3) | columns 37/37, RMS 0,1 mm |
| S208 (Zone B) | 16 (+4 trùng S207 ở cánh nối -> giữ S207) | 18 (W1×15, SW2×3) | columns 31/31, RMS 0,6 mm |

- Loại mới: CC4B - 800x300, CC6 - 500x200, CC1B - 400DIA. Kiểm tra trùng = 0.
- Sàn PT L1 ĐÃ DỰNG (22/10, suspended_slab_extractor.py, dải 370 = vùng sàn riêng, không chồng bê tông):
  S207-p25 16 tấm 1 402,78 m² (370 162,21 / 220 361,87 / 250 293,39 / 240 2,71 / 250 MIN hạ 70 582,59);
  S208-p26 12 tấm 1 327,58 m² (370 207,93 / 240 666,45 / 250 MIN hạ 70 453,19). Diện tích Revit = payload.
  Kiểm tra trùng sàn nay so HÌNH CHIẾU THẬT (poly mặt trên) thay vì hình bao -> duplicates_count = 0. ĐÃ LƯU model.
  Chưa dựng: S207 2 vùng 17,1/17,4 m² trong cung US1 (không có số chiều dày), S208 12,2 m² tại (121894,275281).
- Sàn S.O.G tầng trệt đã DỰNG LẠI (22/10): Zone A 1916866 (1 393,65 m², 2 giếng thang), Zone B 1916906
  (1 313,16 m²); sàn tay 1912844 đã xóa lại. Commit code L1: af3160f.
- Lưu ý: parse_pdf_slab_on_ground lỗi 'NoneType ... item assignment' nếu view đang mở là tầng khác GF
  -> mở view GROUND FLOOR trước khi chạy.

### CAD kiến trúc L1 (22/10)
- A L01 view: 'BUILDING A - LEVEL 1.dwg' (A111 sạch lại, 2461->306 KB) reload, instance 1907056, đúng tọa độ.
- B L01 view: 'BUILDING B - LEVEL 1 (OVERALL).dwg' (A101 sạch, 9625->810 KB), instance 1917942, xoay +30,7172° quanh
  gốc (Revit đặt A101 xoay −30,717°; khớp 124 cung với A111 -> sau khi xoay 0°/0 mm). Gỡ template 'HPCE - Marking Plan'
  khỏi view B L01 (template ẩn Imported Categories), giống view GF. Link A121 cũ (đặt sai chỗ) đã gỡ; type 1909654 còn, không dùng.

### Sắp xếp lại view móng + cao độ đỉnh móng (22/10) - LÀM LẠI SAU CRASH, ĐÃ LƯU 10:03
- View mới: A/B GF marking plan 1918072/1918083; OVERALL - LEVEL 1 1918107 (link 1918119 xoay +30,7172°, khớp 0 mm).
- Quyết định người dùng: 'BUILDING A/B - GROUND FLOOR - MARKING PLAN' (1903761/1903811) là FOOTING plan -> đổi tên
  'BUILDING A/B - FOOTING MARKING PLAN'; tạo view GF mới (duplicate with detailing, range +600/+300/-100/-100);
  'OVERALL - LEVEL 1 - MARKING PLAN' (1916853) gắn nhầm level GF -> tạo lại trên A-LEVEL 01 + link
  'BUILDING B - LEVEL 1 (OVERALL).dwg' xoay +30,7172° (XOAY TRONG TRANSACTION RIÊNG sau khi link).
- Đỉnh móng (TOF) = RL 1.100 = GF −100 (S.O.G 100 nằm trên móng): móng S201/S202 +50 mm, tường S201/S202 base
  offset −100, cột S204/S205 base offset −100. Đã chạy thành công nhưng chưa lưu.
- KHÔNG chạy finalize_and_join_structure trên GF: Revit crash (Assertion GeomTable.cpp) khi join cột/tường với
  sàn S.O.G (boolean fail cột CC3 1913359 với sàn 1916866). Nếu cần join: từng nhóm nhỏ, lưu trước.

### Tầng L2 (23/10, máy công ty) — sàn L02
- Sàn PT L2 ĐÃ DỰNG bằng suspended_slab_extractor (band 300/330/340, split x = 98 480):
  S210-p28 17 tấm 1 037,6 m² (210 348 / 240 336,8 / 300 band 85,7 / 330 band 44 / 200 MIN hạ 70 61,3 / 230 MIN hạ 70 161,7);
  S211-p29 18 tấm 965,6 m² (210 631,5 / 240 23,5 / 300 band 124,2 / 340 band 40,9 / 200 MIN 80,8 / 240 MIN 64,8; close_step_dashes=True).
  Kiểm tra trùng = 0, không có cảnh báo floors overlap. Cột/tường L2 đã có từ trước (máy cá nhân).
- Bổ sung (23/10): S210-add sảnh + hành lang nối sang B 112,8 m² (200 MIN hạ 70; viền hở vì 2 nét hành lang
  dừng trước x = 98 480 -> kéo nét tới đường chia, thêm nét bậc 0.48); S211-add hành lang ngoài phía bắc 188,9 m²
  (200 MIN hạ 70). 0 trùng, không cảnh báo chồng sàn. Script: l2_lobby.py (C:\RevitMCP-work).
- Ô trống còn lại là LỖ MỞ đúng: giếng trời (X), lõi thang SW1/SW2, hố thang máy LW1.
- Sửa (23/10): cột/tường gặp sàn hạ cốt MIN nhô/hở 70 mm -> Top Offset −70 cho 40 cột + 33 tường, Base Offset −70 cho 28 cột + 3 tường. Kiểm tra lại: mọi đỉnh/chân khớp mặt sàn (trừ −100 chân cắm móng GF).
- Làm trơn viền sàn (23/10): 63 tấm L1/L2 dựng lại bằng slab_edge_smoother (răng lược ban công -> cung thật; 66 tấm, 2 vành mỏng 330/370 nhập vào ban công); join 3 cặp chồng nhỏ; tường SW1 1916745 giữ chân tại level (đứng trên tường GF).
- Chờ người dùng xác nhận: ban công PBS1 không có vòng số - S210 góc trên trái 17,7 m², S211 giữa dưới 12,2 m²
  (ban công kề bên là 200 MIN).
- Còn lại: L3 (S213/S214) cột-tường-sàn, mái (S216/S217); thiếu cột L3->mái (A: CC1B 1, CC4B 8, CC6 1; B: CC1B 1, CC4B 5).

## 2. Chưa dựng — cần kiểm tra tay

- L1: PC1/PC2/PBS1 precast (o) chưa bóc tách; loại trong model dày 200 nhưng bảng ghi 180 (tên '-PC1' sai quy ước ' - PC1').
- L1: US1 (o) upstand (bảng ghi level GF, chiều cao không ghi; kiến trúc A301/A302 chỉ có PLANTER BOX ở mái) - chưa dựng.
- ĐÃ BỔ SUNG (đối chiếu chéo KT↔KC, 22/10): W1 cong góc ĐB S207 id 1916971 (R 1600 theo DWG kiến trúc, tâm dời
  −50 mm cho tiếp tuyến tường W1 1916750, khe 0 mm); LW1 bắc lõi thang Zone A 3 trụ 1916972-74 (ô cửa 1101/1097 mm
  theo nét má cửa kết cấu, khung KT 1041 mm), LW1 đông 1916756 kéo tới góc.
- GF STEP/FOLD: kiến trúc A100 có FFL +1.450/+1.800/+2.200/+2.850/+3.100/+3.250 -> cần tách sàn S.O.G theo vùng cao độ (chưa làm).
- L1: đoạn 'SW1' giữa thang bộ không hatch - không dựng.
- L1: CC5 chỉ theo hatch, nhãn không hậu tố: S207 ×3 (94059,260239)(95064,234572)(91165,234572); S208 ×1 id 1916802.

- 5 nhãn PF Zone B không định vị được (PF1 gần CC1A và CC5, PF3 gần CC4A trên phải); PF1 lệch tâm góc ĐB Zone A.
- Dải SF1 dọc RW1 chéo, góc dưới trái cánh nối (mép trong bị móng vẽ đè).
- Móng băng cong dưới RW1 cong (nhãn SF1, không đủ 2 mép).
- Đoạn trụ SW2 ngắn cạnh trên lõi thang; sàn đáy hố thang dày 750 mm (độ sâu theo NSX thang máy).
- STEP (S204, S205) và 600 FOLD quanh lõi thang Zone A — không có cao độ.
- Ô chữ nhật nét đôi Zone B không có ký hiệu X → chưa khoét lỗ.
- Tường tay không tag "S201 - South Jog West Connector" (id 1912816) còn trong model.

## 3. Code / commit (chưa push)

8599794 … e24a640: pipeline PDF→BIM, calibrate (grids/cad/overall/columns), móng/tường/SF, "no tag no element",
workdir, kiểm tra trùng, trang tổng làm chuẩn, tường cong, legend, Phase 0, undo_last, align_viewports, sàn S.O.G.
9c5e5a9: commit các skill còn lại + .agents/rules.

Tool mới chỉ có hiệu lực sau khi khởi động lại server `revit-mcp` (mở phiên mới) và Reload pyRevit.

## 4. Quyết định / quy tắc của người dùng

- Chỉ 1 MCP server `revit-mcp`; chức năng mới viết thành script trong skill (quy tắc 10).
- Trang tổng là chuẩn cho mọi zone (quy tắc 8); đọc legend từng trang (quy tắc 9).
- File sinh ra chỉ nằm trong `.agents/cache/` (quy tắc 6).
- Làm việc trên MỘT phiên chat để hiểu xuyên suốt.

## 5. Bước tiếp theo

- Lưu model Revit (chưa lưu sau các lần dựng).
- Tầng L1 (S206 trang tổng, S207/S208 trang 25–26): cột/tường/dầm/sàn, lọc UNDER theo legend.
