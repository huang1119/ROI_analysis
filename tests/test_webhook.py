"""测试 src/alerting/webhook.py：多目标告警推送。"""
import pytest

from src.alerting import webhook as webhook_mod
from src.alerting.webhook import get_targets, push, push_to_target


def _settings(monkeypatch, targets):
    monkeypatch.setattr(webhook_mod, "load_settings", lambda: {"alert": {"targets": targets}})


def test_get_targets_empty(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    _settings(monkeypatch, [])
    assert get_targets() == []


def test_get_targets_filters_disabled_and_empty(monkeypatch):
    _settings(monkeypatch, [
        {"name": "A", "channel": "feishu", "webhook_url": "http://a", "enabled": True},
        {"name": "B", "channel": "feishu", "webhook_url": "http://b", "enabled": False},
        {"name": "C", "channel": "feishu", "webhook_url": "", "enabled": True},
    ])
    targets = get_targets()
    assert [t["name"] for t in targets] == ["A"]


def test_get_targets_env_fallback(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "http://env")
    monkeypatch.setenv("ALERT_CHANNEL", "dingtalk")
    _settings(monkeypatch, [])
    targets = get_targets()
    assert len(targets) == 1
    assert targets[0]["channel"] == "dingtalk"


def test_push_to_target_without_url(monkeypatch, capsys):
    assert push_to_target("hi", {"name": "X", "channel": "feishu", "webhook_url": ""}) is False
    assert "hi" in capsys.readouterr().out


def test_push_to_target_unknown_channel():
    with pytest.raises(ValueError, match="不支持的告警渠道"):
        push_to_target("hi", {"channel": "foobar", "webhook_url": "http://x"})


def test_push_to_target_success(monkeypatch):
    class FakeResp:
        status = 200

        def read(self):
            return b'{"code": 0}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(webhook_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp())
    assert push_to_target("hi", {"channel": "feishu", "webhook_url": "http://x"}) is True


def test_push_to_target_detects_api_error(monkeypatch):
    class FakeResp:
        status = 200

        def read(self):
            return b'{"code": 19001, "msg": "invalid webhook"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(webhook_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp())
    assert push_to_target("hi", {"channel": "feishu", "webhook_url": "http://x"}) is False


def test_push_broadcasts_to_all_enabled(monkeypatch):
    class FakeResp:
        status = 200

        def read(self):
            return b'{"code": 0}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(webhook_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp())
    _settings(monkeypatch, [
        {"name": "A", "channel": "feishu", "webhook_url": "http://a", "enabled": True},
        {"name": "B", "channel": "dingtalk", "webhook_url": "http://b", "enabled": True},
    ])
    assert push("hi") == 2
