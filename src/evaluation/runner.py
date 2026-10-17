"""实验 runner：Langfuse 在线跑批，或本地离线跑批（无凭据/CI 时）。

两者输出统一的 summary：
    {
      "run_name": str,
      "pass_rate": {evaluator_name: 0.0~1.0},
      "per_item": [{account_id, evaluations: [{name, value, comment}]}, ...],
    }
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ..observability import get_client

TaskFn = Callable[..., Any]
EvaluatorFn = Callable[..., dict]


def _item_field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _label(output: Any, item_input: Any) -> str:
    if isinstance(item_input, dict):
        return (item_input.get("account_id") or item_input.get("question")
                or (output or {}).get("task_type") or "item")
    return (output or {}).get("account_id") or "item"


def _eval_fields(e: Any) -> tuple[str, Any, Optional[str]]:
    if isinstance(e, dict):
        return e.get("name"), e.get("value"), e.get("comment")
    return getattr(e, "name", None), getattr(e, "value", None), getattr(e, "comment", None)


def _summarize(run_name: str, per_item: list[dict]) -> dict:
    agg: dict[str, list[float]] = {}
    for it in per_item:
        for ev in it["evaluations"]:
            name = ev["name"]
            val = ev["value"]
            if name is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                num = 0.0
            agg.setdefault(name, []).append(num)
    pass_rate = {k: round(sum(v) / len(v), 3) for k, v in agg.items() if v}
    return {"run_name": run_name, "pass_rate": pass_rate, "per_item": per_item}


def run_local(items: list[dict], task: TaskFn, evaluators: list[EvaluatorFn]) -> dict:
    """离线跑批：不依赖 Langfuse，逐条执行 task + evaluator。"""
    per_item: list[dict] = []
    for item in items:
        output = task(item=item)
        evals: list[dict] = []
        for ev_fn in evaluators:
            r = ev_fn(
                input=_item_field(item, "input"),
                output=output,
                expected_output=_item_field(item, "expected_output"),
                metadata=_item_field(item, "metadata"),
            )
            evals.extend(r if isinstance(r, list) else [r])
        per_item.append({
            "label": _label(output, _item_field(item, "input")),
            "evaluations": [dict(e) if not isinstance(e, dict) else e for e in evals],
        })
    return _summarize("local", per_item)


def run_langfuse(
    items: list[dict],
    task: TaskFn,
    evaluators: list[EvaluatorFn],
    *,
    name: str = "roi-diagnosis",
    run_name: Optional[str] = None,
) -> dict:
    """Langfuse 在线跑批：自动追踪每条执行并记分，可进 UI 对比。"""
    client = get_client()
    if client is None:
        return run_local(items, task, evaluators)

    exp = client.run_experiment(
        name=name,
        run_name=run_name,
        data=items,
        task=task,
        evaluators=evaluators,
    )
    per_item: list[dict] = []
    for it in exp.item_results:
        output = it.output
        evals = [_eval_fields(e) for e in (it.evaluations or [])]
        per_item.append({
            "label": _label(output, _item_field(it.item, "input")),
            "evaluations": [
                {"name": n, "value": v, "comment": c} for n, v, c in evals
            ],
        })
    return _summarize(run_name or "langfuse", per_item)


def run(
    items: list[dict],
    task: TaskFn,
    evaluators: list[EvaluatorFn],
    *,
    name: str = "roi-diagnosis",
    run_name: Optional[str] = None,
) -> dict:
    """统一入口：配置了 Langfuse 就在线跑，否则离线跑。"""
    if get_client() is not None:
        return run_langfuse(items, task, evaluators, name=name, run_name=run_name)
    return run_local(items, task, evaluators)
