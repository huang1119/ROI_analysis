"""极简登录鉴权（纯标准库，零新依赖）。

- 密码：pbkdf2_hmac(sha256) 加盐哈希，格式 `pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>`
- 会话：HMAC-SHA256 签名的 Cookie（`base64url(payload).base64url(sig)`），带过期时间
- 用户：config/settings.json 的 `auth.users = [{username, password_hash, role}]`
  未配置时回退到内置默认管理员（admin / admin123，role=developer）

角色：developer（可用对话 + 评测看板）；user（仅对话页）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from functools import lru_cache

PBKDF2_ITERS = 120_000
COOKIE_NAME = "roi_session"
DEFAULT_SECRET = "insecure-dev-secret-change-me"


# ---------------------------------------------------------------- 密码
def hash_password(password: str, *, salt: bytes | None = None, iters: int = PBKDF2_ITERS) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return f"pbkdf2_sha256${iters}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError, TypeError):
        return False


# ---------------------------------------------------------------- 会话签名
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(username: str, role: str, secret: str, *, hours: int = 24) -> str:
    payload = {"u": username, "r": role, "exp": int(time.time()) + int(hours) * 3600}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return _b64e(raw) + "." + _b64e(sig)


def parse_session(token: str, secret: str) -> dict | None:
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64d(raw_b64)
        sig = _b64d(sig_b64)
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(raw)
        if int(data.get("exp", 0)) < time.time():
            return None
        return {"username": data.get("u"), "role": data.get("r")}
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 配置 / 用户
def _auth_cfg() -> dict:
    try:
        from .settings import load_settings

        return load_settings().get("auth", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def auth_enabled() -> bool:
    return bool(_auth_cfg().get("enabled", True))


def session_secret() -> str:
    return _auth_cfg().get("secret") or os.environ.get("AUTH_SECRET") or DEFAULT_SECRET


def session_hours() -> int:
    try:
        return int(_auth_cfg().get("session_hours", 24))
    except (TypeError, ValueError):
        return 24


@lru_cache(maxsize=1)
def default_users() -> tuple[dict, ...]:
    """未在 settings.json 配置用户时的内置默认管理员。"""
    return (
        {"username": "admin", "password_hash": hash_password("admin123"),
         "role": "developer"},
    )


def load_users() -> list[dict]:
    users = _auth_cfg().get("users") or []
    return list(users) if users else list(default_users())


def authenticate(username: str, password: str) -> dict | None:
    for u in load_users():
        if u.get("username") == username and verify_password(password, u.get("password_hash", "")):
            return {"username": u["username"], "role": u.get("role", "user")}
    return None


# ---------------------------------------------------------------- 注册
_USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,20}")


def valid_username(username: str) -> bool:
    """用户名仅允许 ASCII 字母/数字/._-，3-20 位（Langfuse user_id 要求 ASCII）。"""
    return bool(username and _USERNAME_RE.fullmatch(username))


def username_exists(username: str) -> bool:
    return any(u.get("username") == username for u in load_users())


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE_RE = re.compile(r"1[3-9]\d{9}")


def _save_users(users: list[dict]) -> None:
    from .settings import load_settings, save_settings

    settings = load_settings()
    cfg = dict(settings.get("auth") or {})
    cfg["users"] = users
    settings["auth"] = cfg
    save_settings(settings)


def _users_for_write() -> list[dict]:
    """待写入的用户列表（首写时把内置默认管理员一起落盘，保住开发者入口）。"""
    users = [dict(u) for u in (_auth_cfg().get("users") or [])]
    return users or [dict(u) for u in default_users()]


def add_user(username: str, password: str, role: str = "user") -> dict:
    """注册新用户并落盘（角色固定为 user，不可自助成为 developer）。"""
    if not valid_username(username):
        raise ValueError("用户名需 3-20 位字母/数字/._-")
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")
    users = _users_for_write()
    if any(u.get("username") == username for u in users):
        raise ValueError("用户名已存在")
    users.append({"username": username, "password_hash": hash_password(password), "role": role})
    _save_users(users)
    return {"username": username, "role": role}


# ---------------------------------------------------------------- 账号管理
def public_profile(username: str) -> dict | None:
    """返回可对外展示的资料（不含哈希）。"""
    for u in load_users():
        if u.get("username") == username:
            return {
                "username": u["username"],
                "role": u.get("role", "user"),
                "email": u.get("email", ""),
                "phone": u.get("phone", ""),
            }
    return None


def update_password(username: str, old_password: str, new_password: str) -> None:
    if len(new_password or "") < 6:
        raise ValueError("新密码至少 6 位")
    users = _users_for_write()
    for u in users:
        if u.get("username") == username:
            if not verify_password(old_password, u.get("password_hash", "")):
                raise ValueError("当前密码不正确")
            u["password_hash"] = hash_password(new_password)
            _save_users(users)
            return
    raise ValueError("用户不存在")


def update_username(old_username: str, new_username: str) -> dict:
    """改用户名；返回新身份（调用方需重签会话 Cookie）。"""
    if not valid_username(new_username):
        raise ValueError("用户名需 3-20 位字母/数字/._-")
    users = _users_for_write()
    if any(u.get("username") == new_username for u in users):
        raise ValueError("用户名已存在")
    for u in users:
        if u.get("username") == old_username:
            u["username"] = new_username
            _save_users(users)
            return {"username": new_username, "role": u.get("role", "user")}
    raise ValueError("用户不存在")


def update_profile(username: str, *, email: str | None = None, phone: str | None = None) -> dict:
    """绑定/修改邮箱、手机号（本版本直接写入，未接真实验证码）。"""
    users = _users_for_write()
    for u in users:
        if u.get("username") == username:
            if email is not None:
                email = (email or "").strip()
                if email and not _EMAIL_RE.fullmatch(email):
                    raise ValueError("邮箱格式不正确")
                u["email"] = email
            if phone is not None:
                phone = (phone or "").strip()
                if phone and not _PHONE_RE.fullmatch(phone):
                    raise ValueError("手机号格式不正确")
                u["phone"] = phone
            _save_users(users)
            return {"email": u.get("email", ""), "phone": u.get("phone", "")}
    raise ValueError("用户不存在")


# ---------------------------------------------------------------- 请求态
def current_user(request) -> dict | None:
    if request is None:
        return None
    try:
        token = request.cookies.get(COOKIE_NAME)
    except Exception:  # noqa: BLE001
        return None
    if not token:
        return None
    return parse_session(token, session_secret())
