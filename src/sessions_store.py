"""对话会话持久化：存 config/sessions.json（服务端，不随浏览器丢失）。"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_PATH = PROJECT_ROOT / "config" / "sessions.json"


def load_sessions() -> list[dict]:
    if SESSIONS_PATH.exists():
        try:
            data = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_sessions(sessions: list[dict]) -> None:
    SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_PATH.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
