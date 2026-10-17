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
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import auth as auth_mod
from src import topics as topics_mod
from src.accounts import load_accounts, save_accounts
from src.alerting.scanner import scan_all
from src.alerting.scheduler import reschedule, start_scheduler, stop_scheduler
from src.alerting.webhook import push_to_target
from src.data.loader import load_dataframe
from src.data.oceanengine import OceanEngineClient
from src.diagnosis.engine import diagnose
from src.llm.client import available, chat
from src.llm.report import generate_report
from src.llm.router import find_account as router_find_account, llm_route, route_message
from src.llm.supplementary import TOOL_SCHEMAS
from src.settings import DEFAULTS, apply_llm_to_env, load_settings, save_settings
from src.sessions_store import replace_user_sessions, sessions_for
from src.observability import flush, record_fallback, record_topic, trace
from src.evaluation.dashboard import aggregate_signals, recent_experiments
from src.skills import DEFAULT_SKILLS, load_skills, save_skills
from src.web.pdf import generate_report_pdf

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _asset_version() -> str:
    """静态资源版本号（取 static/ 下最新修改时间），用于 ?v= 缓存失效。"""
    try:
        latest = max((p.stat().st_mtime for p in STATIC_DIR.glob("*") if p.is_file()), default=0)
        return str(int(latest))
    except OSError:
        return "0"


def _serve_html(name: str) -> HTMLResponse:
    """返回页面并注入资源版本号；no-cache 避免浏览器缓存住旧 HTML。"""
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", _asset_version()),
                        headers={"Cache-Control": "no-cache"})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()
    flush()


app = FastAPI(title="电商广告 ROI 异常诊断", lifespan=lifespan)

# ---------------------------------------------------------------- 鉴权中间件
PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/auth/register", "/favicon.ico"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """登录门禁：全局需登录；/eval 族需 developer 角色。

    - 公开：/login、/api/auth/login、/static/*
    - 关闭鉴权（auth.enabled=false）时全部放行
    - 未登录访问页面重定向 /login，访问 API 返回 401
    """
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    if not auth_mod.auth_enabled():
        return await call_next(request)

    user = auth_mod.current_user(request)
    if path == "/eval" or path.startswith("/api/eval/"):
        if user and user.get("role") == "developer":
            request.state.user = user
            return await call_next(request)
        if path.startswith("/api/"):
            code = 401 if user is None else 403
            msg = "未登录" if user is None else "需要开发者权限"
            return JSONResponse({"detail": msg}, status_code=code)
        return RedirectResponse("/login" if user is None else "/")

    if user is None:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "未登录"}, status_code=401)
        return RedirectResponse("/login")
    request.state.user = user
    return await call_next(request)


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
    session_id: str | None = None   # 可选：会话 ID，用于 Langfuse session 分组
    user_id: str | None = None      # 可选：用户 ID，用于 Langfuse user 分组


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
def _current_username(request: Request) -> str:
    """会话归属账号；关闭鉴权/未登录时回落到 admin。"""
    user = auth_mod.current_user(request) if request is not None else None
    return (user or {}).get("username") or "admin"


def _llm_router_enabled() -> bool:
    """是否启用 LLM 二次路由（settings.json：router.llm_fallback）。"""
    return bool(load_settings().get("router", {}).get("llm_fallback", True))


@app.get("/api/sessions")
def get_sessions(request: Request):
    return {"sessions": sessions_for(_current_username(request))}


@app.put("/api/sessions")
def put_sessions(body: SessionsIn, request: Request):
    return {"sessions": replace_user_sessions(_current_username(request), body.sessions)}


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
    return router_find_account(question, load_accounts())


@app.post("/api/chat")
def chat_api(body: ChatIn, request: Request = None):
    """对话入口：理解意图，路由到诊断/扫描/账户列表，或 LLM 兜底。"""
    msg = body.message.strip()
    if not msg:
        return {"type": "chat", "content": "请告诉我你想做什么，例如：为什么美妆旗舰店的ROI下降了？"}

    df = get_df()
    apply_llm_settings()
    accounts = load_accounts()

    # Langfuse user_id 优先取登录用户（服务端可信），否则回落请求体/本地
    _user = auth_mod.current_user(request) if request is not None else None
    user_id = (_user or {}).get("username") or body.user_id or "local"

    with trace(
        "chat",
        input={"message": msg, "history": body.history},
        session_id=body.session_id,
        user_id=user_id,
    ) as t:
        decision = route_message(msg, accounts=accounts, llm_available=available())
        route = decision["route"]
        route_source = "keyword"
        llm_decision = None
        llm_topic = None
        llm_detail = None
        llm_new_topic = None

        # LLM 二次路由：仅当关键词路由落到 chat 兜底时试一次（多一次调用，判定不可信则不采用）
        if (route == "chat" and decision.get("fallback_type") == "keyword_miss"
                and _llm_router_enabled()):
            llm_decision = llm_route(msg, accounts)
            if llm_decision and llm_decision["route"] != "chat":
                decision = llm_decision
                route = llm_decision["route"]
                route_source = "llm"   # 仅当 LLM 真正改写了路由才算 llm 负责
            elif llm_decision:
                # LLM 也认为该走 chat → 直接用它给的话题（省掉第二套关键词分类）
                llm_topic = llm_decision.get("topic")
                llm_detail = llm_decision.get("detail")
                llm_new_topic = llm_decision.get("new_topic")

        route_meta = {"route_source": route_source}
        if llm_decision is not None:
            route_meta["llm_route"] = llm_decision["route"]

        # 扫描意图
        if route == "scan":
            results = scan_all(df)
            if not results:
                content = "扫描完成，未发现异常账户。"
            else:
                lines = [f"扫描完成，共 {df['advertiser_id'].nunique()} 个账户，发现 {len(results)} 个异常："]
                for r in results:
                    top = r["scores"].iloc[0]["name"] if len(r["scores"]) else "未知"
                    lines.append(f"- {r['account_name']}（{r['account_id']}）：首要根因 {top}")
                content = "\n".join(lines)
            t.update(metadata={**route_meta, "route": "scan"})
            return {"type": "scan", "content": content}

        # 诊断意图
        if route == "diagnose":
            account_id = decision["account_id"]
            r = diagnose(df, account_id)
            serialized = serialize_result(r, df)   # 含 report/evidence/scores/drilldowns
            serialized["type"] = "diagnose"
            serialized["content"] = serialized.pop("report")
            t.update(metadata={**route_meta, "route": "diagnose", "account_id": account_id})
            return serialized

        # 账户列表意图
        if route == "list":
            content = "当前可用账户：\n" + "\n".join(
                f"- {a['advertiser_name']}（{a['advertiser_id']}）" for a in accounts
            )
            t.update(metadata={**route_meta, "route": "list"})
            return {"type": "chat", "content": content}

        # 兜底（chat）
        fallback_type = decision.get("fallback_type")
        topic = (llm_topic if llm_topic and llm_topic != topics_mod.UNCLASSIFIED
                 else topics_mod.classify(msg))          # 缺口归因：用户到底在问什么
        meta = {**route_meta, "route": "chat", "fallback_type": fallback_type, "topic": topic}
        if llm_detail:
            meta["topic_detail"] = llm_detail
        if llm_new_topic and topic == topics_mod.UNCLASSIFIED:
            # 闭集也没归上 → 保留 LLM 自己起的标签，供发现新需求
            meta["new_topic"] = llm_new_topic
        t.update(metadata=meta)
        record_fallback(fallback_type)
        record_topic(topic)

        if fallback_type == "keyword_miss":
            account_txt = "、".join(f"{a['advertiser_name']}({a['advertiser_id']})" for a in accounts)
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


# ---------------------------------------------------------------- 登录鉴权
class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class UsernameIn(BaseModel):
    new_username: str


class ProfileIn(BaseModel):
    email: str | None = None
    phone: str | None = None


def _set_session_cookie(response: Response, username: str, role: str) -> None:
    hours = auth_mod.session_hours()
    token = auth_mod.make_session(username, role, auth_mod.session_secret(), hours=hours)
    response.set_cookie(auth_mod.COOKIE_NAME, token, max_age=hours * 3600,
                        httponly=True, samesite="lax", path="/")


def _require_user(request: Request) -> dict:
    user = auth_mod.current_user(request)
    if user is None:
        raise HTTPException(401, "未登录")
    return user


@app.get("/login")
def login_page():
    return _serve_html("login.html")


@app.post("/api/auth/login")
def auth_login(body: LoginIn, response: Response):
    user = auth_mod.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(401, "用户名或密码错误")
    _set_session_cookie(response, user["username"], user["role"])
    return user


@app.post("/api/auth/register")
def auth_register(body: RegisterIn, response: Response):
    """注册新用户（角色固定 user），成功后自动登录。"""
    try:
        user = auth_mod.add_user(body.username.strip(), body.password, role="user")
    except ValueError as e:
        raise HTTPException(409 if "已存在" in str(e) else 400, str(e))
    _set_session_cookie(response, user["username"], user["role"])
    return user


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(auth_mod.COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    return _require_user(request)


# ---------------------------------------------------------------- 账号管理
@app.get("/api/account/me")
def account_me(request: Request):
    prof = auth_mod.public_profile(_require_user(request)["username"])
    if prof is None:
        raise HTTPException(404, "用户不存在")
    return prof


@app.post("/api/account/password")
def account_password(body: PasswordIn, request: Request):
    try:
        auth_mod.update_password(_require_user(request)["username"],
                                 body.old_password, body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/account/username")
def account_username(body: UsernameIn, request: Request, response: Response):
    try:
        new = auth_mod.update_username(_require_user(request)["username"],
                                       body.new_username.strip())
    except ValueError as e:
        raise HTTPException(409 if "已存在" in str(e) else 400, str(e))
    _set_session_cookie(response, new["username"], new["role"])  # 会话含用户名，需重签
    return {"ok": True, "username": new["username"]}


@app.post("/api/account/profile")
def account_profile(body: ProfileIn, request: Request):
    try:
        return auth_mod.update_profile(_require_user(request)["username"],
                                       email=body.email, phone=body.phone)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- 评测看板（自建聚合视图，design.md §8.9）
# 访问控制由 auth_middleware 负责：仅 developer 角色可进
@app.get("/api/eval/signals")
def eval_signals():
    """缺口信号聚合：兜底次数、工具失败分布、route 分布。"""
    return aggregate_signals()


@app.get("/api/eval/experiments")
def eval_experiments():
    """最近实验（黄金集跑批）列表。"""
    return recent_experiments()


@app.get("/eval")
def eval_page():
    return _serve_html("eval.html")


# ---------------------------------------------------------------- 静态页面
@app.get("/")
def index():
    return _serve_html("index.html")


@app.middleware("http")
async def static_no_cache(request: Request, call_next):
    """静态资源每次回源校验，避免浏览器（如 Edge）长期用旧样式。"""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
