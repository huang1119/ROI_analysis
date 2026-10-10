"""告警推送：支持多个推送目标（群），每个目标一个 webhook。

目标结构：{"name": 群名称, "channel": feishu/dingtalk/wecom, "webhook_url": ..., "enabled": bool}
push() 会广播到所有启用的目标；无目标时打印到控制台。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..settings import load_settings

# 各渠道的文本消息体格式
_CHANNEL_BODY = {
    "feishu": lambda text: {"msg_type": "text", "content": {"text": text}},
    "dingtalk": lambda text: {"msgtype": "text", "text": {"content": text}},
    "wecom": lambda text: {"msgtype": "text", "text": {"content": text}},
}


def get_targets() -> list[dict]:
    """返回所有已启用的推送目标；兼容旧的环境变量配置（无 targets 时回退）。"""
    s = load_settings().get("alert", {})
    targets = s.get("targets") or []
    enabled = [t for t in targets if t.get("enabled", True) and t.get("webhook_url")]
    if enabled:
        return enabled
    # 向后兼容：环境变量
    if os.environ.get("ALERT_WEBHOOK_URL"):
        return [{
            "name": os.environ.get("ALERT_NAME", "环境变量渠道"),
            "channel": os.environ.get("ALERT_CHANNEL", "feishu").lower(),
            "webhook_url": os.environ.get("ALERT_WEBHOOK_URL"),
            "enabled": True,
        }]
    return []


def push_to_target(text: str, target: dict) -> bool:
    """推送到单个目标。返回是否通过 webhook 发出成功。"""
    channel = (target.get("channel") or "console").lower()
    webhook_url = target.get("webhook_url", "")

    if channel == "console" or not webhook_url:
        print(text)
        return False

    if channel not in _CHANNEL_BODY:
        raise ValueError(f"不支持的告警渠道: {channel}")

    body = json.dumps(_CHANNEL_BODY[channel](text)).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=body, method="POST", headers={
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if raw:
                try:
                    data = json.loads(raw)
                    # 飞书用 code、钉钉/企微用 errcode；非 0 都算失败
                    if data.get("code", 0) != 0 or data.get("errcode", 0) != 0:
                        print(f"[告警推送失败] {target.get('name', channel)}: {data}")
                        return False
                except json.JSONDecodeError:
                    pass
            return resp.status == 200
    except urllib.error.URLError as e:
        print(f"[告警推送失败] {target.get('name', channel)}: {e}")
        return False


def push(text: str) -> int:
    """推送到所有启用的目标。返回成功推送数（无目标时打印控制台并返回 0）。"""
    targets = get_targets()
    if not targets:
        print(text)
        return 0
    sent = 0
    for t in targets:
        if push_to_target(text, t):
            sent += 1
    return sent
