"""意图路由（从 web 层抽出，便于评测与复用）。

路由规则（顺序即优先级）：
    1. 含扫描类关键词              → scan
    2. 命中账户 ID / 名称 / 别名   → diagnose（含轻量模糊匹配：容忍错字、少字）
    3. 含账户列表类关键词          → list
    4. 其余                        → chat 兜底：
         LLM 可用 → keyword_miss；LLM 不可用 → no_llm_available

词表是硬编码常量（改这里即可生效）；账户别名写在 config/accounts.json 的 aliases。
"""
from __future__ import annotations

import difflib

# 扫描（全账户体检）
SCAN_KEYWORDS = (
    "扫描", "扫一遍", "扫一下", "体检", "全量",
    "所有账户", "全部账户", "所有店铺", "全部店铺",
    "所有广告主", "全部广告主",
)

# 账户列表（只列举，不跑诊断）
LIST_KEYWORDS = (
    "账户", "账号", "列表", "有哪些",
    "多少个账户", "几个账户", "账户列表",
)

# 模糊匹配阈值：账户名被问题覆盖的比例下限 / 至少匹配到的字符数
FUZZY_THRESHOLD = 0.6
FUZZY_MIN_CHARS = 2


def _names_of(account: dict) -> list[str]:
    """账户的候选叫法：名称 + 别名（ID 单独处理，不参与模糊匹配）。"""
    names = [account.get("advertiser_name") or ""]
    names += [a for a in (account.get("aliases") or []) if a]
    return [n for n in names if n]


def _coverage(name: str, question: str) -> tuple[float, int]:
    """账户名在问题里被覆盖的比例 + 实际匹配到的字符数（容忍错字/少字）。"""
    n = name.lower()
    if not n:
        return 0.0, 0
    chars = sum(b.size for b in
                difflib.SequenceMatcher(None, n, question).get_matching_blocks())
    return chars / len(n), chars


def find_account(question: str, accounts: list[dict]) -> str | None:
    """先精确（ID/名称/别名子串），再模糊（字符覆盖 ≥ 阈值）。

    多个账户并列第一时视为有歧义，返回 None（不猜，避免诊断错账户）。
    """
    q = (question or "").lower()
    if not q:
        return None

    # 1) 精确子串
    for a in accounts:
        keys = [a.get("advertiser_id") or ""] + _names_of(a)
        if any(k and k.lower() in q for k in keys):
            return a["advertiser_id"]

    # 2) 模糊
    candidates: list[tuple[float, str]] = []
    for a in accounts:
        best = 0.0
        best_chars = 0
        for name in _names_of(a):
            score, chars = _coverage(name, q)
            if score > best:
                best, best_chars = score, chars
        if best >= FUZZY_THRESHOLD and best_chars >= FUZZY_MIN_CHARS:
            candidates.append((best, a["advertiser_id"]))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None  # 并列 → 有歧义
    return candidates[0][1]


VALID_ROUTES = ("diagnose", "scan", "list", "chat")


def _parse_route(raw: str, accounts: list[dict], labels: list[str] | None = None) -> dict | None:
    """从模型输出里解析路由 JSON（含聊天时的话题）；任何不确定都返回 None。"""
    import json
    import re

    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    route = data.get("route")
    if route not in VALID_ROUTES:
        return None
    out: dict = {"route": route}
    if route == "diagnose":
        aid = data.get("account_id")
        if aid not in {a["advertiser_id"] for a in accounts}:
            return None          # 账户非法 → 不敢乱诊断
        out["account_id"] = aid
    if route == "chat":
        topic = data.get("topic")
        out["topic"] = topic if topic in (labels or []) else "未归类"
        # 词表没覆盖到时，保留 LLM 自己起的标签（用于发现新需求）
        new_topic = data.get("new_topic")
        if out["topic"] == "未归类" and isinstance(new_topic, str) and new_topic.strip():
            out["new_topic"] = new_topic.strip()[:12]
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            out["detail"] = detail.strip()[:40]
    return out


def llm_route(msg: str, accounts: list[dict], topics: list[dict] | None = None) -> dict | None:
    """LLM 二次路由 + 缺口归因（一次调用同时给出 route 和 topic）。

    返回 {route, account_id?, topic?, detail?} 或 None（不可用/不可信）。
    - 只允许 diagnose/scan/list/chat
    - diagnose 的账户必须来自给定列表
    - route=chat 时给出 topic（限定在既有话题词表内，保证可聚合）
    """
    from ..topics import UNCLASSIFIED, load_topics
    from .client import available, chat

    if not available():
        return None
    topic_list = topics if topics is not None else load_topics()
    labels = [t["label"] for t in topic_list if t.get("label")] + [UNCLASSIFIED]
    account_lines = "\n".join(
        f"- {a['advertiser_id']} {a['advertiser_name']}" for a in accounts
    ) or "（无）"
    system = (
        "你是意图分类器。判断用户这句话属于哪类操作，只输出 JSON，不要解释。\n"
        "可选 route：\n"
        "- diagnose：询问某个账户/店铺的 ROI 或投放数据异常（必须指定账户）\n"
        "- scan：要求检查/扫描全部账户\n"
        "- list：要求列出可用账户\n"
        "- chat：以上都不是（闲聊、选品、天气、写文案等产品当前做不到的）\n"
        f"可用账户：\n{account_lines}\n"
        "若 route=chat：\n"
        f"  1) 先看能否归入已有话题（topic），只能从这些里选：{'、'.join(labels)}\n"
        "  2) 都不合适就 topic 用「未归类」，并给 new_topic：你自己起一个简短分类名"
        "（2-6 字，同一类问题请始终用同一个名字）\n"
        "  3) 另给 detail：一句话概括用户想问什么（不超过 20 字）\n"
        "输出示例：\n"
        '{"route":"chat","account_id":null,"topic":"天气/无关查询","detail":"查今天天气"}\n'
        '{"route":"chat","account_id":null,"topic":"未归类","new_topic":"私域运营","detail":"问怎么提升私域转化"}\n'
        '{"route":"diagnose","account_id":"A001"}\n'
        "route=diagnose 时 account_id 必须是上面 ID 之一；不确定就选 chat。"
    )
    try:
        raw = chat(
            [{"role": "system", "content": system}, {"role": "user", "content": msg}],
            temperature=0,
            max_tokens=160,
        )
    except Exception:  # noqa: BLE001
        return None
    return _parse_route(raw, accounts, labels)


def route_message(msg: str, *, accounts: list[dict], llm_available: bool) -> dict:
    """返回路由决策 dict：{route, account_id?, fallback_type?}。"""
    if any(k in msg for k in SCAN_KEYWORDS):
        return {"route": "scan"}

    account_id = find_account(msg, accounts)
    if account_id:
        return {"route": "diagnose", "account_id": account_id}

    if any(k in msg for k in LIST_KEYWORDS):
        return {"route": "list"}

    if llm_available:
        return {"route": "chat", "fallback_type": "keyword_miss"}
    return {"route": "chat", "fallback_type": "no_llm_available"}
