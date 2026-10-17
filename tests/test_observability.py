"""测试 src/observability：脱敏、配置优先级、未配置时 no-op。"""
import src.observability as obs
import src.observability.client as obs_client
from src.observability import (
    flush,
    generation,
    get_config,
    hash_account_id,
    record_fallback,
    redact_text,
    sanitize,
    shutdown,
    span,
    trace,
)


def _clear_langfuse_env(monkeypatch):
    for v in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HOST"]:
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------- 脱敏
def test_redact_phone_id_longnum():
    assert redact_text("打 13812345678 联系") == "打 [手机号] 联系"
    assert redact_text("身份证 110101199001011234 号") == "身份证 [身份证] 号"
    assert redact_text("订单号 2025010112345678 请查") == "订单号 [长数字] 请查"


def test_safe_attr_strips_non_ascii_and_truncates():
    from src.observability.client import _safe_attr
    assert _safe_attr("u-abc") == "u-abc"
    assert _safe_attr("用户") is None
    assert _safe_attr("u-中文abc") == "u-abc"
    assert _safe_attr(None) is None
    assert len(_safe_attr("x" * 300)) == 200


def test_hash_account_id_deterministic_and_short():
    assert hash_account_id("") == ""
    assert hash_account_id("A001") == hash_account_id("A001")
    assert hash_account_id("A001") != "A001"
    assert len(hash_account_id("A001")) == 12


def test_sanitize_hashes_account_and_redacts_text():
    out = sanitize({"account_id": "A001", "note": "电话 13812345678"})
    assert out["account_id"] == hash_account_id("A001")
    assert "13812345678" not in out["note"]


def test_sanitize_recurses_into_lists():
    out = sanitize([{"advertiser_id": "A002"}, {"msg": "id 110101199001011234"}])
    assert out[0]["advertiser_id"] == hash_account_id("A002")
    assert "[身份证]" in out[1]["msg"]


# ---------------------------------------------------------------- 配置
def test_get_config_disabled_by_default(monkeypatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setattr(obs_client, "_settings_config", lambda: {})
    assert get_config()["enabled"] is False
    assert obs.is_enabled() is False


def test_get_config_env_priority_over_settings(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://example.com")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setattr(obs_client, "_settings_config",
                        lambda: {"enabled": True, "public_key": "x", "secret_key": "y", "host": "z"})
    cfg = get_config()
    assert cfg["enabled"] is True
    assert cfg["public_key"] == "pk"
    assert cfg["host"] == "https://example.com"


def test_get_config_default_host_is_cloud(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setattr(obs_client, "_settings_config", lambda: {})
    assert get_config()["host"] == "https://cloud.langfuse.com"


def test_get_config_prefers_base_url_over_deprecated_host(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://base.example")
    monkeypatch.setenv("LANGFUSE_HOST", "https://old.example")
    monkeypatch.setattr(obs_client, "_settings_config", lambda: {})
    assert get_config()["host"] == "https://base.example"


def test_get_config_settings_fallback(monkeypatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setattr(obs_client, "_settings_config",
                        lambda: {"enabled": True, "public_key": "pk2", "secret_key": "sk2",
                                 "host": "https://selfhost.example"})
    cfg = get_config()
    assert cfg["enabled"] is True
    assert cfg["public_key"] == "pk2"
    assert cfg["host"] == "https://selfhost.example"


# ---------------------------------------------------------------- no-op
def test_all_noop_when_disabled(monkeypatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setattr(obs_client, "_settings_config", lambda: {})
    monkeypatch.setattr(obs_client, "_client", None)
    monkeypatch.setattr(obs_client, "_initialized", False)

    with trace("t") as t:
        assert t.trace_id is None
        t.update(metadata={"x": "y"})
    with generation("g") as g:
        g.update(output="hi")
    with span("s") as s:
        s.update()
    record_fallback("keyword_miss")  # 不抛异常
    flush()
    shutdown()
