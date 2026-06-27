"""
state.py — จัดการ state ของ pdf_generated แบบ local
แทนที่จะเขียนลง JSON บน Drive mount (ช้า)
เก็บไว้ใน /app/uan/slip-processor/generated_log.json แทน

format:
{
  "2026/JUN/24/บุคคล": {
    "IMG_5876": {"pdf_file": "...", "amount": 350},
    ...
  }
}
"""

import json
from pathlib import Path
from config.config import CODE_DIR

STATE_PATH = Path(CODE_DIR) / "data" / "generated_log.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def mark_generated(state: dict, year: str, month: str, day: str,
                   subfolder: str, slips: list[dict], pdf_path: str):
    """บันทึกว่า slip กลุ่มนี้ gen PDF แล้ว"""
    key = f"{year}/{month}/{day}/{subfolder}"
    if key not in state:
        state[key] = {}
    for s in slips:
        stem = Path(s.get("dest_file", s.get("source_file", ""))).stem
        state[key][stem] = {
            "pdf_file": pdf_path,
            "amount":   s.get("amount", 0),
        }


def is_generated(state: dict, year: str, month: str, day: str,
                 subfolder: str, slip: dict) -> bool:
    """เช็คว่า slip นี้เคย gen ไปแล้วไหม"""
    key  = f"{year}/{month}/{day}/{subfolder}"
    stem = Path(slip.get("dest_file", slip.get("source_file", ""))).stem
    return stem in state.get(key, {})


def reset_state(state: dict, path_filter: str) -> int:
    """
    Reset state ตาม path filter
    เช่น path_filter = "2026" / "2026/JUN" / "2026/JUN/24"
    """
    keys_to_delete = [k for k in state if path_filter in k]
    for k in keys_to_delete:
        del state[k]
    return len(keys_to_delete)
