"""测试 src/llm/agent.py：agent 工具调用循环。"""
from src.llm import agent


def test_run_agent_calls_tools_then_concludes(monkeypatch):
    calls = []
    responses = [
        {"content": None, "tool_calls": [{
            "id": "1", "type": "function",
            "function": {"name": "foo", "arguments": '{"x": 1}'},
        }]},
        {"content": "最终报告"},
    ]
    monkeypatch.setattr(agent, "chat_raw", lambda messages, tools=None: responses.pop(0))

    def execute(name, args):
        calls.append((name, args))
        return {"ok": True}

    out = agent.run_agent("sys", "ctx", tools=[{"type": "function", "function": {"name": "foo"}}], execute=execute)
    assert out == "最终报告"
    assert calls == [("foo", {"x": 1})]


def test_run_agent_forces_conclusion_after_max_rounds(monkeypatch):
    def fake_chat_raw(messages, tools=None):
        return {"content": None, "tool_calls": [{
            "id": "1", "type": "function",
            "function": {"name": "foo", "arguments": "{}"},
        }]}

    monkeypatch.setattr(agent, "chat_raw", fake_chat_raw)
    monkeypatch.setattr(agent, "chat", lambda messages: "强制结论")

    out = agent.run_agent("sys", "ctx", tools=[{"type": "function", "function": {"name": "foo"}}],
                          execute=lambda n, a: {}, max_rounds=2)
    assert out == "强制结论"


def test_run_agent_handles_bad_tool_arguments(monkeypatch):
    responses = [
        {"content": None, "tool_calls": [{
            "id": "1", "type": "function",
            "function": {"name": "foo", "arguments": "not-json"},
        }]},
        {"content": "报告"},
    ]
    monkeypatch.setattr(agent, "chat_raw", lambda messages, tools=None: responses.pop(0))
    out = agent.run_agent("sys", "ctx", tools=[{"type": "function", "function": {"name": "foo"}}],
                          execute=lambda n, a: {"note": "args 解析失败时用空参数"})
    assert out == "报告"
