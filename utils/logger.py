"""
utils/logger.py — log พร้อม timestamp
ใช้แทน print() ทุกที่
"""

from datetime import datetime


def log(msg: str, end: str = "\n"):
    """print พร้อม timestamp เช่น 2026-06-28 12:18:00 - copy รูปมา local"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} - {msg}", end=end)
