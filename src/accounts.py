"""账户管理：平台下的广告主（每个 = 一个店铺/账户）。

层级关系：
  数据源配置（app_id/secret/token）= 怎么连上平台（1 套）
  账户管理（advertiser）= 连上后拉哪些店铺的数据（N 个）

存 config/accounts.json；默认是合成数据里的两个演示账户。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_PATH = PROJECT_ROOT / "config" / "accounts.json"

DEFAULT_ACCOUNTS = [
    {"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"},
    {"advertiser_id": "A002", "advertiser_name": "服饰旗舰店"},
]


def load_accounts() -> list[dict]:
    if ACCOUNTS_PATH.exists():
        try:
            data = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return [dict(a) for a in DEFAULT_ACCOUNTS]


def save_accounts(accounts: list[dict]) -> None:
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_PATH.write_text(
        json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
