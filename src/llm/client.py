"""极简 OpenAI 兼容 LLM 客户端（零第三方依赖，标准库实现）。

支持 DeepSeek / Qwen(阿里云百炼兼容模式) 等任何 OpenAI 兼容端点。
配置全部走环境变量，绝不把 key 写进代码：

    LLM_PROVIDER    deepseek（默认）| qwen
    LLM_API_KEY     （必填）
    LLM_BASE_URL    可选，覆盖默认端点
    LLM_MODEL       可选，覆盖默认模型
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _load_dotenv() -> None:
    """自动加载项目根目录或 src/ 下的 .env（不覆盖已存在的环境变量）。

    支持 `KEY=value` 格式，忽略空行与 # 注释，value 可选引号。
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [os.path.join(root, ".env"), os.path.join(root, "src", ".env")]
    for path in candidates:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")  # 去除首尾空白与可选引号
                if key and key not in os.environ:
                    os.environ[key] = value


_load_dotenv()

DEFAULT_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
}


def get_config() -> dict:
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    default = DEFAULT_PROVIDERS.get(provider, DEFAULT_PROVIDERS["deepseek"])
    return {
        "provider": provider,
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "base_url": os.environ.get("LLM_BASE_URL", default["base_url"]),
        "model": os.environ.get("LLM_MODEL", default["model"]),
    }


def available() -> bool:
    return bool(get_config()["api_key"])


def _post(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> dict:
    """调用 OpenAI 兼容 /chat/completions，返回 assistant message 字典。"""
    cfg = get_config()
    if not cfg["api_key"]:
        raise RuntimeError("未配置 LLM_API_KEY 环境变量")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM 请求失败 HTTP {e.code}: {detail[:500]}") from e

    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"LLM 响应格式异常: {json.dumps(data, ensure_ascii=False)[:500]}") from e


def chat_raw(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> dict:
    """返回完整 assistant message（可能含 tool_calls），供 agent 循环使用。"""
    return _post(messages, tools=tools, temperature=temperature, max_tokens=max_tokens, timeout=timeout)


def chat(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> str:
    """调用 LLM，返回 assistant 文本内容。"""
    msg = _post(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    return msg.get("content") or ""
