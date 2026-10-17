"""Langfuse 可观测性埋点（未配置时全 no-op，不影响业务）。

配置优先级：环境变量 > config/settings.json 的 langfuse 段
    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL（LANGFUSE_HOST 为旧名，已弃用）
    或 settings.json: {"langfuse": {"enabled": true, "public_key": ..., "secret_key": ..., "host": ...}}
默认 host：https://cloud.langfuse.com（Langfuse Cloud EU，SDK 默认）

埋点层次：
    trace      对话/任务级（trace）：session/user/route/account 等领域标签
    generation LLM 调用级（generation）：模型、token、耗时、错误
    span       工具调用级（span/tool）：工具名、参数、返回状态

脱敏（design.md §8.10）：account_id 哈希；文本正则脱敏（身份证/手机号/长数字=订单号）。
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

try:  # langfuse 未安装时降级为 no-op
    from langfuse import Langfuse, propagate_attributes

    _LANGFUSE_AVAILABLE = True
except Exception:  # noqa: BLE001
    _LANGFUSE_AVAILABLE = False
    Langfuse = None  # type: ignore[assignment]
    propagate_attributes = None  # type: ignore[assignment]

DEFAULT_HOST = "https://cloud.langfuse.com"

# 脱敏正则：先身份证(18) → 再手机号(11) → 最后其他长数字（订单号等）
_RE_ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_RE_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_RE_LONGNUM = re.compile(r"(?<!\d)\d{11,}(?!\d)")

_ACCOUNT_KEYS = {"account_id", "advertiser_id"}

_client: Optional["Langfuse"] = None
_initialized = False


def _env_config() -> dict:
    return {
        "public_key": os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        "secret_key": os.environ.get("LANGFUSE_SECRET_KEY", ""),
        # 规范变量为 LANGFUSE_BASE_URL；LANGFUSE_HOST 为弃用旧名
        "host": os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST", ""),
    }


def _settings_config() -> dict:
    try:
        from ..settings import load_settings

        return load_settings().get("langfuse", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def get_config() -> dict:
    """返回生效的 Langfuse 配置（环境变量优先于 settings.json）。"""
    env = _env_config()
    if env["public_key"] and env["secret_key"]:
        return {
            "enabled": True,
            "public_key": env["public_key"],
            "secret_key": env["secret_key"],
            "host": env["host"] or DEFAULT_HOST,
        }
    s = _settings_config()
    if s.get("enabled") and s.get("public_key") and s.get("secret_key"):
        return {
            "enabled": True,
            "public_key": s["public_key"],
            "secret_key": s["secret_key"],
            "host": s.get("host") or DEFAULT_HOST,
        }
    return {"enabled": False, "public_key": "", "secret_key": "", "host": DEFAULT_HOST}


def is_configured() -> bool:
    return get_config()["enabled"]


def is_enabled() -> bool:
    return is_configured()


def get_client():
    """惰性初始化 Langfuse 客户端；未配置或不可用时返回 None。"""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    if not _LANGFUSE_AVAILABLE:
        _client = None
        return None
    cfg = get_config()
    if not cfg["enabled"]:
        _client = None
        return None
    try:
        kwargs = {"public_key": cfg["public_key"], "secret_key": cfg["secret_key"]}
        if cfg["host"]:
            kwargs["host"] = cfg["host"]
        _client = Langfuse(**kwargs)
    except Exception:  # noqa: BLE001
        _client = None
    return _client


# ---------------------------------------------------------------- 脱敏
def redact_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = _RE_ID.sub("[身份证]", text)
    text = _RE_PHONE.sub("[手机号]", text)
    text = _RE_LONGNUM.sub("[长数字]", text)
    return text


def hash_account_id(account_id: str) -> str:
    if not account_id:
        return account_id
    return hashlib.sha256(str(account_id).encode("utf-8")).hexdigest()[:12]


def sanitize(obj: Any) -> Any:
    """递归脱敏：账户字段哈希、字符串正则脱敏、容器递归。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _ACCOUNT_KEYS and isinstance(v, str):
                out[k] = hash_account_id(v)
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [sanitize(x) for x in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


# ---------------------------------------------------------------- 埋点句柄
def _safe_attr(v):
    """Langfuse 一等属性（user_id/session_id/tags）要求 US-ASCII 且 ≤200 字符，
    非法值会被静默丢弃；这里主动清洗，避免“设了但没生效”。"""
    if v is None:
        return None
    s = str(v).encode("ascii", errors="ignore").decode("ascii")[:200]
    return s or None


class _Noop:
    def update(self, *a, **k):
        return self

    def score(self, *a, **k):
        return None

    def score_trace(self, *a, **k):
        return None

    @property
    def trace_id(self):
        return None


class _Obs:
    def __init__(self, obs, client):
        self._obs = obs
        self._client = client

    def update(self, **kwargs):
        for key in ("input", "output", "metadata"):
            if key in kwargs and kwargs[key] is not None:
                kwargs[key] = sanitize(kwargs[key])
        self._obs.update(**kwargs)
        return self

    def score(self, name, value, **kwargs):
        self._obs.score(name=name, value=value, **kwargs)

    def score_trace(self, name, value, **kwargs):
        self._obs.score_trace(name=name, value=value, **kwargs)

    @property
    def trace_id(self):
        return self._client.get_current_trace_id()


# ---------------------------------------------------------------- 埋点入口
@contextmanager
def trace(
    name: str,
    *,
    input=None,
    output=None,
    metadata: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list] = None,
    environment: Optional[str] = None,
) -> Iterator[_Obs]:
    """任务级 trace。session/user/tags 走 trace 属性，metadata 为领域维度。"""
    client = get_client()
    if client is None:
        yield _Noop()
        return
    meta = {k: str(v)[:200] for k, v in (metadata or {}).items() if v is not None}
    safe_tags = [t for t in (_safe_attr(x) for x in (tags or [])) if t] or None
    with propagate_attributes(
        user_id=_safe_attr(user_id),
        session_id=_safe_attr(session_id),
        tags=safe_tags,
        environment=_safe_attr(environment),
        metadata=meta,
    ):
        with client.start_as_current_observation(
            name=name,
            as_type="span",
            input=sanitize(input),
            output=sanitize(output) if output is not None else None,
            end_on_exit=True,
        ) as obs:
            yield _Obs(obs, client)


@contextmanager
def generation(
    name: str,
    *,
    model: Optional[str] = None,
    input=None,
    metadata: Optional[dict] = None,
    model_parameters: Optional[dict] = None,
) -> Iterator[_Obs]:
    """LLM 调用级 generation。"""
    client = get_client()
    if client is None:
        yield _Noop()
        return
    with client.start_as_current_observation(
        name=name,
        as_type="generation",
        model=model,
        model_parameters=model_parameters,
        input=sanitize(input),
        metadata=sanitize(metadata) if metadata is not None else None,
        end_on_exit=True,
    ) as obs:
        yield _Obs(obs, client)


@contextmanager
def span(
    name: str,
    *,
    input=None,
    metadata: Optional[dict] = None,
    as_type: str = "span",
) -> Iterator[_Obs]:
    """工具/步骤级 span（as_type 可选 span/tool/agent/...）。"""
    client = get_client()
    if client is None:
        yield _Noop()
        return
    with client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=sanitize(input),
        metadata=sanitize(metadata) if metadata is not None else None,
        end_on_exit=True,
    ) as obs:
        yield _Obs(obs, client)


# ---------------------------------------------------------------- 事件录制器
# 供回归 task 捕获执行过程中的工具调用与兜底事件（design.md §8.8 task 结构化输出）。
# contextvar 保证同一线程内 start/stop 配对，且不跨请求污染。
_recorder_ctx: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "observability_recorder", default=None
)


def start_recording() -> None:
    """开始录制（安装一个空列表）；任务开始前调用。"""
    _recorder_ctx.set([])


def stop_recording() -> list:
    """停止录制并返回事件列表；任务结束后调用。"""
    events = _recorder_ctx.get() or []
    _recorder_ctx.set(None)
    return events


def _record_event(event: dict) -> None:
    rec = _recorder_ctx.get()
    if rec is not None:
        rec.append(event)


def record_tool_call(name: str, args: dict, result: Any, status: str) -> None:
    """录制一次工具调用（供 agent 循环调用）。"""
    _record_event({
        "type": "tool_call",
        "name": name,
        "arguments": args,
        "result": result,
        "status": status,
    })


# ---------------------------------------------------------------- 评分 / 收尾
def record_fallback(fallback_type: str) -> None:
    """记录兜底类型（design.md §8.5）。

    1. 无条件写入事件录制器（供回归 task 结构化输出）；
    2. 若当前有 Langfuse trace，再打一条 CATEGORICAL 分数便于聚合。
    """
    _record_event({"type": "fallback", "value": fallback_type})
    client = get_client()
    if client is None:
        return
    if not client.get_current_trace_id():
        return
    client.score_current_trace(
        name="fallback_type",
        value=fallback_type,
        data_type="CATEGORICAL",
        comment="命中兜底",
    )


def record_topic(topic: str) -> None:
    """记录兜底归因话题（design.md §8.2）：CATEGORICAL 分数，便于按话题聚合。"""
    _record_event({"type": "topic", "value": topic})
    client = get_client()
    if client is None:
        return
    if not client.get_current_trace_id():
        return
    client.score_current_trace(
        name="topic",
        value=topic,
        data_type="CATEGORICAL",
        comment="兜底归因话题",
    )


def flush() -> None:
    """同步冲刷缓冲区（短命进程退出前调用，否则丢 trace）。"""
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass


def shutdown() -> None:
    """关闭客户端并重置（CLI 进程退出前调用）。"""
    global _client, _initialized
    if _client is not None:
        try:
            _client.shutdown()
        except Exception:  # noqa: BLE001
            pass
    _client = None
    _initialized = False
