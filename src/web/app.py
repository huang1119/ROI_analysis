"""Web 应用后端（FastAPI）。

提供四类能力：
  - 静态页面（index.html / css / js）
  - 模型配置：读写 LLM provider/api_key/model/base_url
  - 数据源配置：读写平台与数据文件
  - 诊断 / 扫描：复用确定性诊断引擎 + LLM 报告生成
"""
from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.accounts import load_accounts, save_accounts
from src.alerting.scanner import scan_all
from src.alerting.scheduler import reschedule, start_scheduler, stop_scheduler
from src.alerting.webhook import push_to_target
from src.data.loader import load_dataframe
from src.data.oceanengine import OceanEngineClient
from src.diagnosis.engine import diagnose
from src.llm.client import available, chat
from src.llm.report import generate_report
from src.llm.supplementary import TOOL_SCHEMAS
from src.settings import DEFAULTS, apply_llm_to_env, load_settings, save_settings
from src.sessions_store import load_sessions, save_sessions
from src.skills import DEFAULT_SKILLS, load_skills, save_skills
from src.web.pdf import generate_report_pdf

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="电商广告 ROI 异常诊断", lifespan=lifespan)


# ---------------------------------------------------------------- 数据访问
def get_df() -> pd.DataFrame:
    try:
        return load_dataframe(load_settings())
    except (FileNotFoundError, RuntimeError, OceanEngineError) as e:
        raise HTTPException(500, str(e))


def apply_llm_settings() -> None:
    """Web 界面的模型配置优先：写入环境变量供 client.chat() 使用。"""
    apply_llm_to_env()


def df_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → JSON 安全记录列表（numpy 类型转原生，NaN→null）。"""
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def serialize_result(r: dict, df: pd.DataFrame) -> dict:
    drilldowns = {
        k: df_records(v.head(5) if v is not None else None)
        for k, v in r["drilldowns"].items()
    }
    return {
        "account_id": r["account_id"],
        "account_name": r["account_name"],
        "recent_days": r["recent_days"],
        "baseline_days": r["baseline_days"],
        "evidence": df_records(r["evidence"]),
        "scores": df_records(r["scores"]),
        "decision": r["decision"]["mode"],
        "drilldowns": drilldowns,
        "report": generate_report(r, df),
    }


# ---------------------------------------------------------------- 请求体
class LLMConfigIn(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    model: str = ""
    base_url: str = ""


class DataSourceIn(BaseModel):
    platform: str = "巨量千川"
    mode: str = "合成数据（演示）"
    data_file: str = ""
    api: dict = {}


class ExportConfigIn(BaseModel):
    dir: str = ""


class AlertConfigIn(BaseModel):
    targets: list[dict] = []
    interval_hours: float = 0


class AlertTestIn(BaseModel):
    target: dict


class ExportIn(BaseModel):
    filename: str
    content: str
    dir: str = ""            # 可选：不填则用配置的导出目录
    format: str = "md"       # md | pdf
    images: list[dict] = []  # PDF 时嵌入的图表 [{name, data(base64)}]


class DiagnoseIn(BaseModel):
    account_id: str
    recent_days: int = 7
    baseline_days: int = 21


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


# ---------------------------------------------------------------- 配置 API
@app.get("/api/config/llm")
def get_llm_config():
    return load_settings()["llm"]


@app.put("/api/config/llm")
def put_llm_config(body: LLMConfigIn):
    settings = load_settings()
    settings["llm"] = body.model_dump()
    save_settings(settings)
    return settings["llm"]


@app.post("/api/config/llm/test")
def test_llm():
    """用当前配置发一条极小请求，验证 key 是否可用。"""
    apply_llm_settings()
    try:
        reply = chat([{"role": "user", "content": "请只回复两个字：正常"}], max_tokens=20)
        return {"ok": True, "reply": reply.strip()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/config/datasource")
def get_datasource_config():
    return load_settings()["datasource"]


@app.put("/api/config/datasource")
def put_datasource_config(body: DataSourceIn):
    settings = load_settings()
    settings["datasource"] = body.model_dump()
    save_settings(settings)
    return settings["datasource"]


@app.post("/api/config/datasource/test")
def test_datasource(body: DataSourceIn):
    """测试真实 API 连接（用提交的 api 配置）。"""
    api = body.api or {}
    client = OceanEngineClient(
        app_id=api.get("app_id", ""),
        secret=api.get("secret", ""),
        access_token=api.get("access_token", ""),
        refresh_token=api.get("refresh_token", ""),
        base_url=api.get("base_url", "https://ad.oceanengine.com"),
    )
    ok, msg = client.test_connection()
    return {"ok": ok, "message": msg}


# ---------------------------------------------------------------- 导出配置
@app.get("/api/config/export")
def get_export_config():
    return load_settings().get("export", {"dir": ""})


@app.put("/api/config/export")
def put_export_config(body: ExportConfigIn):
    settings = load_settings()
    settings["export"] = {"dir": body.dir}
    save_settings(settings)
    return settings["export"]


@app.get("/api/config/alert")
def get_alert_config():
    return load_settings().get("alert", {"targets": [], "interval_hours": 0})


@app.put("/api/config/alert")
def put_alert_config(body: AlertConfigIn):
    settings = load_settings()
    settings["alert"] = body.model_dump()
    save_settings(settings)
    reschedule()
    return settings["alert"]


@app.post("/api/config/alert/test")
def test_alert(body: AlertTestIn):
    """测试单个推送目标。"""
    t = body.target
    name = t.get("name") or t.get("channel") or "该渠道"
    if not t.get("webhook_url"):
        return {"ok": True, "message": f"「{name}」未填 webhook 地址，请先填写"}
    try:
        sent = push_to_target("【测试】ROI 诊断助手告警测试", t)
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": sent, "message": f"「{name}」推送成功" if sent else f"「{name}」推送失败，请检查 webhook 地址与网络"}


@app.post("/api/export")
def export_report(body: ExportIn):
    """导出报告为 Markdown 或 PDF（PDF 可嵌入图表图片）。"""
    export_dir = (body.dir or load_settings().get("export", {}).get("dir", "")).strip()
    if not export_dir:
        raise HTTPException(400, "未配置导出目录")
    os.makedirs(export_dir, exist_ok=True)

    name = os.path.basename(body.filename).strip() or "report.md"
    name = re.sub(r'[<>:"/\\|?*\r\n]', "_", name)

    if body.format == "pdf":
        if not name.lower().endswith(".pdf"):
            name = os.path.splitext(name)[0] + ".pdf"
        data = generate_report_pdf(body.content, body.images)
        path = os.path.join(export_dir, name)
        with open(path, "wb") as f:
            f.write(data)
    else:
        if not name.lower().endswith(".md"):
            name += ".md"
        path = os.path.join(export_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body.content)
    return {"ok": True, "path": path}


class SkillsIn(BaseModel):
    skills: list[dict]


@app.get("/api/skills")
def get_skills():
    return {
        "skills": load_skills(),
        "tools": [
            {"name": s["function"]["name"], "description": s["function"]["description"]}
            for s in TOOL_SCHEMAS
        ],
    }


@app.put("/api/skills")
def put_skills(body: SkillsIn):
    save_skills(body.skills)
    return {"skills": load_skills()}


@app.post("/api/skills/reset")
def reset_skills():
    save_skills([dict(s) for s in DEFAULT_SKILLS])
    return {"skills": load_skills()}


# ---------------------------------------------------------------- 诊断 / 扫描
@app.get("/api/accounts")
def list_accounts():
    return load_accounts()


class AccountsIn(BaseModel):
    accounts: list[dict]


class SessionsIn(BaseModel):
    sessions: list[dict]


@app.put("/api/accounts")
def put_accounts(body: AccountsIn):
    save_accounts(body.accounts)
    return load_accounts()


# ---------------------------------------------------------------- 对话会话
@app.get("/api/sessions")
def get_sessions():
    return {"sessions": load_sessions()}


@app.put("/api/sessions")
def put_sessions(body: SessionsIn):
    save_sessions(body.sessions)
    return {"sessions": load_sessions()}


@app.post("/api/diagnose")
def diagnose_api(body: DiagnoseIn):
    apply_llm_settings()
    df = get_df()
    if body.account_id not in set(df["advertiser_id"]):
        raise HTTPException(404, f"账户不存在：{body.account_id}")
    r = diagnose(df, body.account_id, body.recent_days, body.baseline_days)
    return serialize_result(r, df)


@app.post("/api/scan")
def scan_api():
    apply_llm_settings()
    df = get_df()
    results = scan_all(df)
    return {
        "scanned": int(df["advertiser_id"].nunique()),
        "anomalies": [serialize_result(r, df) for r in results],
    }


def find_account(question: str) -> str | None:
    """从提问中匹配账户名或 ID（基于账户配置，而非数据文件）。"""
    q = question.lower()
    for a in load_accounts():
        if a["advertiser_id"].lower() in q or a["advertiser_name"].lower() in q:
            return a["advertiser_id"]
    return None


@app.post("/api/chat")
def chat_api(body: ChatIn):
    """对话入口：理解意图，路由到诊断/扫描/账户列表，或 LLM 兜底。"""
    msg = body.message.strip()
    if not msg:
        return {"type": "chat", "content": "请告诉我你想做什么，例如：为什么美妆旗舰店的ROI下降了？"}

    df = get_df()

    # 扫描意图
    if "扫描" in msg:
        results = scan_all(df)
        if not results:
            content = "扫描完成，未发现异常账户。"
        else:
            lines = [f"扫描完成，共 {df['advertiser_id'].nunique()} 个账户，发现 {len(results)} 个异常："]
            for r in results:
                top = r["scores"].iloc[0]["name"] if len(r["scores"]) else "未知"
                lines.append(f"- {r['account_name']}（{r['account_id']}）：首要根因 {top}")
            content = "\n".join(lines)
        return {"type": "scan", "content": content}

    # 诊断意图：从提问中匹配账户
    account_id = find_account(msg)
    if account_id:
        apply_llm_settings()
        r = diagnose(df, account_id)
        serialized = serialize_result(r, df)   # 含 report/evidence/scores/drilldowns
        serialized["type"] = "diagnose"
        serialized["content"] = serialized.pop("report")
        return serialized

    # 账户列表意图
    if any(k in msg for k in ("账户", "账号", "列表", "有哪些")):
        content = "当前可用账户：\n" + "\n".join(
            f"- {a['advertiser_name']}（{a['advertiser_id']}）" for a in load_accounts()
        )
        return {"type": "chat", "content": content}

    # LLM 兜底（含历史，支持追问）
    apply_llm_settings()
    if available():
        account_txt = "、".join(f"{a['advertiser_name']}({a['advertiser_id']})" for a in load_accounts())
        system = (
            "你是电商广告 ROI 诊断助手。你能帮用户：\n"
            "1. 诊断某账户的 ROI 异常（需要账户名或ID）\n"
            "2. 扫描全部账户找异常\n"
            "3. 列出账户\n"
            f"当前可用账户：{account_txt}\n"
            "如果用户问题涉及诊断但没给账户，请引导他提供账户名。回答要简洁、大白话。"
        )
        messages = [{"role": "system", "content": system}] + body.history + [{"role": "user", "content": msg}]
        return {"type": "chat", "content": chat(messages)}

    return {
        "type": "chat",
        "content": "我暂时无法理解你的问题。你可以问：\n- 为什么XX的ROI下降了？\n- 扫描所有账户\n- 有哪些账户？",
    }


# ---------------------------------------------------------------- 静态页面
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
