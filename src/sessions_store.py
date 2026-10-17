"""对话会话持久化：存 config/sessions.json（服务端，不随浏览器丢失）。

会话按**账号**隔离：每条会话带 `user` 字段（登录用户名）。
历史遗留的无 user 会话视为 admin 的（保持向后兼容，不被其他账号看到）。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_PATH = PROJECT_ROOT / "config" / "sessions.json"

LEGACY_OWNER = "admin"


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


def _owner(session: dict) -> str:
    return session.get("user") or LEGACY_OWNER


def sessions_for(username: str) -> list[dict]:
    """只返回属于该账号的会话。"""
    return [s for s in load_sessions() if _owner(s) == username]


def replace_user_sessions(username: str, sessions: list[dict]) -> list[dict]:
    """只替换该账号的会话，其他账号的原样保留（避免相互覆盖）。"""
    others = [s for s in load_sessions() if _owner(s) != username]
    mine = []
    for s in sessions:
        item = dict(s)
        item["user"] = username
        mine.append(item)
    save_sessions(others + mine)
    return mine
