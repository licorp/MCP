@echo off
rem Double-click de cai dat / cap nhat Revit MCP tren may nay. Nho THOAT HAN Claude truoc.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
pause
