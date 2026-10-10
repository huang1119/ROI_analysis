"""测试 src/llm/client.py：LLM 客户端（不发起真实网络请求）。"""
import io
import urllib.error

import pytest

from src.llm import client as client_mod
from src.llm.client import available, chat, get_config


def test_get_config_defaults_to_deepseek(monkeypatch):
    for var in ["LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]:
        monkeypatch.delenv(var, raising=False)
    cfg = get_config()
    assert cfg["provider"] == "deepseek"
    assert cfg["model"] == "deepseek-chat"
    assert "api.deepseek.com" in cfg["base_url"]


def test_get_config_qwen(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg = get_config()
    assert cfg["model"] == "qwen-plus"
    assert "dashscope" in cfg["base_url"]


def test_available_false_without_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert available() is False


def test_chat_raises_without_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        chat([{"role": "user", "content": "hi"}])


def _fake_resp(payload: bytes):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return payload

    return FakeResp()


def test_chat_returns_content(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    payload = b'{"choices":[{"message":{"content":"\u4f60\u597d"}}]}'
    monkeypatch.setattr(client_mod.urllib.request, "urlopen",
                        lambda req, timeout: _fake_resp(payload))
    assert chat([{"role": "user", "content": "hi"}]) == "你好"


def test_chat_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def _boom(req, timeout):
        raise urllib.error.HTTPError(
            url="http://x", code=401, msg="Unauthorized",
            hdrs={}, fp=io.BytesIO(b'{"error":"bad key"}'),
        )

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", _boom)
    with pytest.raises(RuntimeError, match="401"):
        chat([{"role": "user", "content": "hi"}])


def test_chat_raises_on_malformed_response(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(client_mod.urllib.request, "urlopen",
                        lambda req, timeout: _fake_resp(b'{"unexpected": true}'))
    with pytest.raises(RuntimeError, match="响应格式异常"):
        chat([{"role": "user", "content": "hi"}])
