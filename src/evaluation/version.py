"""版本标签（design.md §8.8）：commit_hash + prompt/skills/tools hash + model。

用于实验 run_name，供新旧版本对比时区分「改了提示词/换了模型/加了工具」。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ..llm.client import get_config as llm_get_config
from ..llm.supplementary import TOOL_SCHEMAS
from ..skills import load_skills

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _sha8(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def commit_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, cwd=PROJECT_ROOT,
        )
        return out.stdout.strip()[:8] or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def skills_hash() -> str:
    return _sha8(json.dumps(load_skills(), ensure_ascii=False, sort_keys=True))


def tools_hash() -> str:
    return _sha8(json.dumps(TOOL_SCHEMAS, ensure_ascii=False, sort_keys=True))


def compute_version() -> dict:
    return {
        "commit": commit_hash(),
        "model": (llm_get_config().get("model") or "none"),
        "skills": skills_hash(),
        "tools": tools_hash(),
    }


def version_label() -> str:
    v = compute_version()
    model = (v["model"] or "none").replace("-", "_")
    return f"{v['commit']}-{model}-{v['skills']}-{v['tools']}"
