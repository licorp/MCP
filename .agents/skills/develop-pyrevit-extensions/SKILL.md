---
name: develop-pyrevit-extensions
description: >-
  Hướng dẫn phát triển, mở rộng và đóng gói pyRevit Extension & FastMCP Tools cho Revit.
  Chuẩn hóa cấu trúc thư mục .extension, viết endpoint pyRevit Routes (IronPython 2.7 / .NET),
  xây dựng công cụ FastMCP (CPython 3.10+), xử lý tương thích JSON giữa 2 môi trường và tự động kiểm thử.
---

# Phát Triển pyRevit Extension & MCP Tools (develop-pyrevit-extensions)

Skill này cung cấp quy chuẩn kiến trúc và quy trình từng bước để phát triển, thêm mới các công cụ (Tools) và các điểm cuối API (Routes) cho hệ thống **`mcp-server-for-revit-python`**, lấy cảm hứng từ chuẩn `OriAshkenazi/ai-pyrevit-developer-template`.

---

## 1. Kiến Trúc Hai Tầng (Dual-Layer Architecture)

Hệ thống hoạt động theo mô hình 2 tầng phân tách rõ ràng:

```
[ AI Agent / Claude / Antigravity ]
              │ (MCP Protocol - stdio / SSE)
              ▼
    [ FastMCP Server (CPython 3.x) ]
    File: main.py + tools/*.py
              │ (HTTP JSON over localhost:48884)
              ▼
   [ pyRevit Routes (IronPython 2.7 / .NET) ]
   File: startup.py + revit_mcp/*.py
              │ (Direct .NET / Revit API)
              ▼
      [ Autodesk Revit Engine ]
```

1. **Tầng Máy chủ MCP (`main.py` & `tools/`)**:
   - Chạy trên môi trường CPython hiện đại (Python 3.10+).
   - Đóng gói các hàm thành MCP Tool bằng thư viện `mcp.server.fastmcp.FastMCP`.
   - Giao tiếp với Revit thông qua các HTTP request (`revit_get`, `revit_post`, `revit_image`).

2. **Tầng Tiện ích mở rộng Revit (`startup.py` & `revit_mcp/`)**:
   - Chạy trực tiếp trong tiến trình Revit qua micro-framework `pyrevit.routes`.
   - Có toàn quyền truy cập luồng chính và ngữ cảnh Revit API (`doc`, `uidoc`, `DB.Transaction`).

---

## 2. Quy Trình Thêm Một Tính Năng / MCP Tool Mới

### Bước 1: Viết Route Endpoint trong Revit (`revit_mcp/<tên_chức_năng>.py`)
Ví dụ: Thêm tính năng kiểm tra va chạm hoặc tạo Sheet:
```python
# -*- coding: UTF-8 -*-
from pyrevit import routes
import logging

logger = logging.getLogger(__name__)

def register_sheet_routes(api):
    @api.route('/sheets/create/', methods=["POST"])
    def create_sheet(request):
        try:
            from pyrevit import revit, DB
            doc = revit.doc
            
            data = request.data
            sheet_number = data.get("number", "A101")
            sheet_name = data.get("name", "UNNAMED")
            
            t = DB.Transaction(doc, "Create New Sheet via MCP")
            t.Start()
            
            # Tìm TitleBlock mặc định
            tb_collector = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType()
            tb_id = tb_collector.FirstElementId()
            
            sheet = DB.ViewSheet.Create(doc, tb_id)
            sheet.SheetNumber = sheet_number
            sheet.Name = sheet_name
            
            t.Commit()
            
            return routes.make_response(data={
                "success": True,
                "sheet_id": str(sheet.Id),
                "sheet_number": sheet.SheetNumber
            })
        except Exception as e:
            logger.error("Sheet creation error: " + str(e))
            return routes.make_response(data={"success": False, "error": str(e)}, status=500)
```

### Bước 2: Đăng ký Route trong `startup.py`
Mở `startup.py` và gọi hàm đăng ký:
```python
from revit_mcp.sheet_routes import register_sheet_routes
# Trong hàm register_routes(api):
register_sheet_routes(api)
```

### Bước 3: Định nghĩa MCP Tool tương ứng trong `tools/`
Tạo hoặc mở file trong thư mục `tools/sheet_tools.py`:
```python
from mcp.server.fastmcp import Context
from typing import Dict, Any

def register_sheet_tools(mcp, revit_post):
    @mcp.tool()
    async def create_revit_sheet(sheet_number: str, sheet_name: str, ctx: Context = None) -> Dict[str, Any]:
        """Tạo một trang in (ViewSheet) mới trong mô hình Revit"""
        payload = {"number": sheet_number, "name": sheet_name}
        return await revit_post("/sheets/create/", payload, ctx=ctx)
```
Sau đó đăng ký vào `tools/__init__.py` và `main.py`.

---

## 3. Các Lưu Ý Tương Thích IronPython 2.7 $\leftrightarrow$ CPython

1. **Chuỗi Ký Tự & Unicode**:
   - Luôn thêm `# -*- coding: UTF-8 -*-` ở đầu file `.py` trong `revit_mcp/`.
   - Trong IronPython 2.7, dùng `str(val)` hoặc `.format()` thay cho f-strings (f-strings chỉ dùng ở CPython phía `main.py` và `tools/`).
2. **Kiểu Dữ Liệu Số Nguyên Lớn (`ElementId`)**:
   - Khi trả về ID phần tử qua JSON, luôn chuyển thành chuỗi: `str(elem.Id)`.
3. **Transaction Context**:
   - Tất cả các Route sửa đổi mô hình phải nằm trong luồng chính và bọc bởi `DB.Transaction(doc, "Name")`.
