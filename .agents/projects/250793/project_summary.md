# Tóm tắt dự án — KAI HUSKISSON, 4 Murdoch St (HPCE 250793), Combined set_1.pdf (35 trang)

## Danh mục
- S000 bìa, S001 danh mục, S002 ghi chú chung (tender/sơ bộ, NOT FOR CONSTRUCTION), S003–S004 mặt bằng tải trọng
- S100/S101 chi tiết móng điển hình, S111 SOG, S121 tường chắn RW1/RW2, S122 Dincel, S125 tường BT 2 lớp,
  S131 sàn treo, S132 PT, S140 cầu thang, S150 cột điển hình (CC1A, CC1B, CC2, CC3, CC4A, CC4B, CC5, CC6), S160/S161 precast
- Mặt bằng: S200 móng tổng, S201 móng Zone A, S202 móng Zone B; S203 GF tổng, S204/S205 GF Zone A/B;
  S206–S208 L1; S209–S211 L2 (theo Building A/B); S212–S214 L3; S215–S217 Roof

## Ghi chú chung ảnh hưởng mô hình
- Móng đặt theo TIM CỘT / dưới tâm tường U.N.O.
- "Refer to architectural drawings for column setout, and TOP FOOTING LEVEL" → bản KC không ghi cao độ đỉnh móng;
  offset −150 mm đang dùng là GIẢ ĐỊNH.
- BT N40 (móng, SOG), S40 sàn treo; lớp bảo vệ móng 65.
- Đất nền: pad 150 kPa, strip 125 kPa.

## Bảng thống kê (S202 = S201)
- PF1 2400x2400x450, PF2 4800x4300x800, PF3 4300x4300x750, PF4 5200x4700x850, PF5 2600x1600x450
- SF1 2500W x 500D
- Tường Dincel 200: W1 (GF-L1, L1-ROOF), LW1/SW1 (GF-L2, L2-L3, L3-ROOF), SW2 (GF-L2, L2-ROOF)
  US1 200 upstand GF, US2 150 upstand ROOF; RW1/RW2 200 tường chắn, chỉ ở GF
- Bảng "EW BEDROCK" có cùng mã nhưng thép khác (không ảnh hưởng hình học)

## Zone / Building
- Zone A = Building A (vuông theo trang). Zone B = Building B xoay ≈ −30.7° so với Zone A + phần nối.
- S200 có dải chồng Zone A/B ở chỗ nối → cấu kiện ở dải này có thể đã dựng từ S201 → dựa vào duplicate guard.
- Revit levels (ft→mm): GF 1200, L01 4300, L02 7500, L03 10700, ROOF 14000, PARAPET 14600 (A và B giống nhau).

## Zone B (S202) chú ý
- Lõi thang máy SW2 x4 quanh sàn hố thang dày 750 (N20-250 EW top & bottom) — có tag độ dày "750".
- PF4 chỉ ở Zone B (gần CC3), PF2 dưới CC2/CC4A ở cánh xoay.
- SW2 chưa có loại tường trong Revit.

## Bổ sung từ bộ kiến trúc TA2358 (turco and associates, Rev1 19/06/2026) — drive-download-20260724T032928Z-1-001
- A001 site, A100 GF, A101–A104 L1–Roof tổng, A111–A113 Bldg A L1–L3, A121–A123 Bldg B L1–L3, A201–A204 mặt đứng, A301/A302 mặt cắt. Có DWG đi kèm.
- Cao độ (A301/A302): GF (car park) FFL 1.200; L01 4.300; L02 7.500; L03 10.700; ROOF RL 14.000; TOW parapet 14.600; 13m trên NGL RL 14.800; mực chống ngập RL 3.100; mực nước biển 0.000.
  → TRÙNG KHỚP level Revit hiện có (A và B giống nhau).
- Tầng trệt là bãi xe chung 2 tòa (một sàn liền), có các cốt cục bộ FFL 1.450 / 1.800 / 2.200 / 2.850 / 3.100 / 3.250 ở ram dốc, sân, lối vào.
- Revit đã link sẵn DWG kiến trúc: GROUND (view tổng), BUILDING A/B - GROUND FLOOR, LEVEL 1–3.
- Cao độ đỉnh móng: bản kiến trúc không ghi TOF; S100 mặt cắt 01/02 cho thấy SOG dày 150 nằm trên móng đơn/móng băng
  → đỉnh móng = FFL − 150 = RL 1.050 (khớp offset −150 đang dùng). Hố thang máy: sâu theo nhà sản xuất (không xác định).
