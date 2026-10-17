"""测试 src/evaluation：结构化 task、Code Evaluator、黄金集、本地 runner。"""
from src.evaluation.evaluators import (
    deviated_stage_match,
    fallback_matches,
    root_cause_match,
    route_matches,
    tool_called,
)
from src.evaluation.golden_set import GOLDEN_ITEMS
from src.evaluation.runner import run_local
from src.evaluation.task import (
    run_chat_task,
    run_diagnosis_task,
    run_task,
    top_deviated_stage,
    top_root_cause,
)
from src.evaluation.version import version_label
from src.observability import record_fallback, record_tool_call

ACCOUNTS = [
    {"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"},
    {"advertiser_id": "A002", "advertiser_name": "服饰旗舰店"},
]


# ---------------------------------------------------------------- task 结构化输出
def test_task_a001_structured(demo_df):
    out = run_diagnosis_task(demo_df, "A001", with_report=False)
    assert out["task_type"] == "diagnosis"
    assert out["account_id"] == "A001"
    assert out["decision"] == "multiple"
    assert out["root_cause"] == "RC08"          # 结构集中（cost×2.2）
    assert out["deviated_stage"] == "CVR"        # cvr×0.45 是最大漏斗偏离
    assert out["answer"] == ""                   # 未跑 LLM
    assert out["fallback_type"] is None
    assert out["evidence"] and out["evidence"][0]["factor"] == "消耗规模"


def test_task_a002_structured(demo_df):
    out = run_diagnosis_task(demo_df, "A002", with_report=False)
    assert out["decision"] == "single"
    assert out["root_cause"] == "RC02"           # 出价/成本上浮（cpm×1.5）
    assert out["deviated_stage"] == "展示效率"


def test_top_root_cause_handles_empty():
    assert top_root_cause({"scores": __import__("pandas").DataFrame()}) is None


def test_top_deviated_stage_ignores_non_funnel_factors(demo_df):
    from src.diagnosis.engine import diagnose
    r = diagnose(demo_df, "A001")
    stage = top_deviated_stage(r)
    assert stage in {"展示效率", "CTR", "CVR", "下单率", "客单价"}


def test_task_captures_tool_calls_and_fallback(demo_df):
    """task 通过录制器捕获 agent 工具调用与兜底事件（design.md §8.8）。"""
    def fake_report(result, df):
        record_tool_call("cost_share_trend", {"creative_id": "CRT-101"}, {"判定": "上升"}, "ok")
        record_fallback("deterministic_fallback")
        return "报告"

    out = run_diagnosis_task(demo_df, "A001", report_fn=fake_report)
    assert [tc["name"] for tc in out["tool_calls"]] == ["cost_share_trend"]
    assert out["fallback_type"] == "deterministic_fallback"


# ---------------------------------------------------------------- 对话路由 / 兜底
def test_run_chat_task_fallback_when_no_keyword():
    out = run_chat_task("帮我写一首关于春天的诗", accounts=ACCOUNTS, llm_available=True)
    assert out["task_type"] == "chat"
    assert out["route"] == "chat"
    assert out["fallback_type"] == "keyword_miss"   # 关键词未命中 → LLM 兜底
    assert out["topic"] == "闲聊/无关"              # 缺口归因：问题被归到哪个话题


def test_run_chat_task_no_llm_available():
    out = run_chat_task("帮我写一首关于春天的诗", accounts=ACCOUNTS, llm_available=False)
    assert out["fallback_type"] == "no_llm_available"


def test_run_chat_task_routes_to_diagnose():
    out = run_chat_task("为什么美妆旗舰店的ROI下降了", accounts=ACCOUNTS, llm_available=True)
    assert out["route"] == "diagnose"
    assert out["account_id"] == "A001"
    assert out["fallback_type"] is None


def test_run_task_dispatches_by_input(demo_df):
    diag = run_task(demo_df, {"account_id": "A001"}, accounts=ACCOUNTS, with_report=False)
    assert diag["task_type"] == "diagnosis"
    scan = run_task(demo_df, {"question": "扫描一下所有账户"}, accounts=ACCOUNTS, llm_available=True)
    assert scan["task_type"] == "chat" and scan["route"] == "scan"


def test_run_task_question_that_routes_to_diagnosis_runs_diagnosis(demo_df):
    """线上转化的 question 用例，路由到诊断就真跑诊断（可重放）。"""
    out = run_task(demo_df, {"question": "为什么美妆旗舰店的ROI下降了"},
                   accounts=ACCOUNTS, llm_available=True, with_report=False)
    assert out["task_type"] == "diagnosis"
    assert out["account_id"] == "A001"
    assert out["root_cause"] == "RC08"


# ---------------------------------------------------------------- Code Evaluator
def test_root_cause_match_pass():
    assert root_cause_match(output={"root_cause": "RC08"},
                            expected_output={"root_cause": "RC08"})["value"] == 1


def test_root_cause_match_fail_with_comment():
    ev = root_cause_match(output={"root_cause": "RC03"}, expected_output={"root_cause": "RC08"})
    assert ev["value"] == 0 and "RC08" in ev["comment"] and "RC03" in ev["comment"]


def test_evaluator_skips_when_not_declared():
    """未声明断言 → 中性通过（不再误判为 0）。"""
    assert root_cause_match(output={"root_cause": "RC08"})["value"] == 1
    assert route_matches(output={"route": "chat"})["value"] == 1


def test_route_matches_evaluator():
    assert route_matches(output={"route": "chat"}, expected_output={"route": "chat"})["value"] == 1
    assert route_matches(output={"route": "scan"}, expected_output={"route": "chat"})["value"] == 0


def test_fallback_matches_evaluator():
    assert fallback_matches(output={"fallback_type": None},
                            expected_output={"fallback_type": None})["value"] == 1
    assert fallback_matches(output={"fallback_type": "keyword_miss"},
                            expected_output={"fallback_type": None})["value"] == 0
    assert fallback_matches(output={"fallback_type": "keyword_miss"},
                            expected_output={"fallback_type": "keyword_miss"})["value"] == 1


def test_tool_called_evaluator():
    ok = tool_called(output={"tool_calls": [{"name": "cost_share_trend"}]},
                     expected_output={"expected_tool": "cost_share_trend"})
    assert ok["value"] == 1
    fail = tool_called(output={"tool_calls": [{"name": "live_room_metrics"}]},
                       expected_output={"expected_tool": "cost_share_trend"})
    assert fail["value"] == 0


# ---------------------------------------------------------------- 黄金集
def test_golden_items_shape():
    assert len(GOLDEN_ITEMS) == 3
    for it in GOLDEN_ITEMS:
        assert it["input"] and it["expected_output"] and it["metadata"]
    fallback = [it for it in GOLDEN_ITEMS if "question" in it["input"]]
    assert fallback and fallback[0]["expected_output"]["fallback_type"] == "keyword_miss"


# ---------------------------------------------------------------- 本地 runner
def test_run_local_full_pass(demo_df):
    def task(*, item, **kwargs):
        return run_task(demo_df, item["input"], accounts=ACCOUNTS,
                        llm_available=True, with_report=False)

    summary = run_local(
        GOLDEN_ITEMS, task,
        [root_cause_match, deviated_stage_match, route_matches, fallback_matches],
    )
    assert summary["run_name"] == "local"
    assert summary["pass_rate"]["root_cause_match"] == 1.0
    assert summary["pass_rate"]["deviated_stage_match"] == 1.0
    assert summary["pass_rate"]["fallback_matches"] == 1.0
    assert summary["pass_rate"]["route_matches"] == 1.0
    assert len(summary["per_item"]) == 3


# ---------------------------------------------------------------- 版本标签
def test_version_label_has_four_segments():
    parts = version_label().split("-")
    assert len(parts) == 4 and all(parts)
