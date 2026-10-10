"""应用配置持久化（JSON 文件）。

Web 界面的「模型配置」与「数据源配置」写入 config/settings.json。
该文件含 LLM 密钥，已加入 .gitignore，绝不入库。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "llm": {
        "provider": "deepseek",   # deepseek | qwen
        "api_key": "",
        "model": "",              # 留空则用 provider 默认模型
        "base_url": "",           # 留空则用 provider 默认端点
    },
    "datasource": {
        "platform": "巨量千川",
        "mode": "合成数据（演示）",   # 合成数据（演示） | 真实 API
        "data_file": str(PROJECT_ROOT / "data" / "synthetic_daily.parquet"),
        "api": {
            "app_id": "",
            "secret": "",
            "access_token": "",
            "refresh_token": "",
            "base_url": "https://ad.oceanengine.com",
            "days": 60,
        },
    },
    "export": {
        "dir": str(PROJECT_ROOT / "exports"),
    },
    "alert": {
        "interval_hours": 0,   # 定时扫描间隔（小时），0 = 关闭
        "targets": [],         # 推送目标列表 [{name, channel, webhook_url, enabled}]
    },
}


def load_settings() -> dict:
    """读取配置，未配置的项回落到默认值。"""
    data: dict = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    merged = {k: dict(v) for k, v in DEFAULTS.items()}
    for section in merged:
        if isinstance(data.get(section), dict):
            merged[section].update(data[section])
    return merged


def save_settings(settings: dict) -> dict:
    """整份覆盖写回。调用方应先 load 再改再 save。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return settings


def apply_llm_to_env() -> None:
    """把配置页的 LLM 配置写入环境变量（供 client.chat 使用）。"""
    s = load_settings().get("llm", {})
    mapping = {
        "LLM_PROVIDER": "provider",
        "LLM_API_KEY": "api_key",
        "LLM_MODEL": "model",
        "LLM_BASE_URL": "base_url",
    }
    for env_key, setting_key in mapping.items():
        val = s.get(setting_key)
        if val:
            os.environ[env_key] = val
