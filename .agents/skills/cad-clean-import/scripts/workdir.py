# -*- coding: utf-8 -*-
"""
Thư mục làm việc chung cho file trung gian (dump CAD, LISP/SCR tạm, JSON trích xuất, DXF tạm...).
KHÔNG ghi file sinh ra lên Desktop hay thư mục đang chạy lệnh.
Mặc định: <extension>/.agents/cache ; đổi bằng biến môi trường PDF2BIM_WORK_DIR.
"""
import os

_DEFAULT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "cache"))


def work_dir():
    d = os.environ.get("PDF2BIM_WORK_DIR") or _DEFAULT
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def work_path(name):
    """Đường dẫn file trung gian trong thư mục làm việc (dấu '\\' của Windows)."""
    return os.path.join(work_dir(), name)


def lisp_path(name):
    """Như work_path nhưng dùng '/' để nhúng vào chuỗi AutoLISP (open ... "w")."""
    return work_path(name).replace("\\", "/")
