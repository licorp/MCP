# Cài Revit MCP dùng chung trên một máy mới

Thư viện này (code MCP + skills + CLAUDE.md) nằm trên GitHub. Máy nào cũng cài giống nhau, cập nhật bằng `git pull`.

## Cần có trước
- Revit (2024–2027) + **pyRevit**
- **Git**: https://git-scm.com/download/win
- **uv**: `winget install astral-sh.uv`
- Claude Desktop

## Cài lần đầu
1. **Thoát hẳn Claude** (cả icon ở khay hệ thống). Claude đang chạy sẽ ghi đè `claude_desktop_config.json`.
2. Mở PowerShell:
   ```powershell
   git clone https://github.com/licorp/MCP.git C:\RevitMCP\mcp-server-for-revit-python.extension
   C:\RevitMCP\mcp-server-for-revit-python.extension\setup.cmd
   ```
3. Revit: tab **pyRevit → Reload**.
4. Revit: tab **MCP → Bridge → Connect → Yes** (mỗi máy một lần; mã pairing lưu riêng theo user Windows).
5. Mở lại Claude, hỏi: "kiểm tra kết nối Revit".

`setup.cmd` làm gì:
| Việc | Chi tiết |
|---|---|
| Repo | `git pull` tại `C:\RevitMCP\mcp-server-for-revit-python.extension` |
| Extension trùng | Cất `revit-mcp-python.extension` / bản cũ trong `%APPDATA%\pyRevit\Extensions` sang `Extensions_backup` (hai bản cùng route `revit_mcp` sẽ xung đột) |
| pyRevit | Thêm `C:\RevitMCP` vào Custom Extension Directories, bật Routes server (cổng 48884) |
| Claude | Mục `Revit Connector` chạy `uv run main.py` của repo; venv ở `C:\RevitMCP-venv` (riêng từng máy) |
| Skills | Tạo liên kết `.agents\skills\*` → `%USERPROFILE%\.claude\skills\` (Claude Code dùng được ngay) |

## Cập nhật hằng ngày
- Máy vừa sửa: `git add -A && git commit -m "..." && git push`
- Máy khác: chạy lại `setup.cmd` (hoặc `git pull`) → pyRevit **Reload**.
- Chỉ sửa ở một máy một lúc, nhớ push trước khi chuyển máy.

## Lỗi thường gặp
| Triệu chứng | Nguyên nhân / cách sửa |
|---|---|
| `All connection attempts failed` | Routes server tắt hoặc chưa Reload pyRevit. Kiểm tra `pyRevit_config.ini` → `[routes] enabled = true`. |
| `Could not find ... pairing.dpapi` / 401 | Chưa bấm **MCP → Bridge → Connect**. |
| Kết quả lạ, route không đúng | Hai extension MCP cùng cài. Chỉ giữ một bản. |
| Nhiều Revit cùng mở | Chỉ một phiên giữ được cổng 48884; Reload pyRevit ở đúng phiên cần dùng. |
| Sửa config Claude bị mất | Claude đang chạy đã ghi đè. Thoát hẳn Claude rồi chạy lại `setup.cmd`. |
| Kích thước/cao độ "sai" | Revit API trả đơn vị nội bộ **feet**. 1 ft = 0.3048 m. |
