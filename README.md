# 电商广告 ROI 异常诊断 Agent

把「运营去各平台查数据 + 凭经验判断 ROI 为什么掉」的工作流交给 AI。

MVP 聚焦 **巨量千川（抖音电商）的 ROAS 异常诊断**：确定性计算保证「算得准、可复现」，LLM 负责「说得像人话、给出可执行的建议」。

> 完整设计共识见 [`design.md`](design.md)。

## 功能一览

- 💬 **对话式诊断**：像聊天一样问「为什么美妆旗舰店的 ROI 下降了」，agent 理解意图、跑诊断、回复大白话报告（支持追问、打字机输出、Markdown 渲染）
- 📊 **结构化诊断**：漏斗偏离图、根因打分、素材下钻，定位到具体素材
- 🔍 **全账户扫描**：一键扫所有账户，挑出异常账户
- 🧠 **可配置 Skill 知识库**：教 agent「什么情况下调哪个工具」，可导入/编辑自己的策略
- 🏪 **账户管理**：一个数据源（一套 API 凭据）下管理多个店铺账户
- 🔌 **真实 API 入口**：巨量千川 Marketing API 客户端 + 数据源切换 + 测试连接
- 📄 **报告导出**：PDF（含图表）/ Markdown，导出目录可自定义
- ⏰ **定时告警推送**：可配置扫描间隔，多群（飞书/钉钉/企微）推送

## 项目架构设计

### 分层架构

```
┌────────────────────────────────────────────────────────────────┐
│                         接入层                                    │
│    Web 界面（对话 / 诊断 / 扫描 / 配置） · CLI 脚本 · 定时任务       │
└───────────────────────────────┬────────────────────────────────┘
                                │ HTTP / 函数调用
┌───────────────────────────────▼────────────────────────────────┐
│                       编排层（Agent）                             │
│    意图路由（chat_api） · 工具调用循环（agent） · 报告生成          │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                     诊断引擎（确定性核心）                          │
│    证据层(baseline) → 推理层(scoring) → 决策层                   │
│    漏斗分解 · z-score 偏离检测 · 赋分制 · 单因/多因判定            │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                           数据层                                  │
│    合成数据 · 千川 API(oceanengine) · 账户 · 技能 · 配置持久化      │
└────────────────────────────────────────────────────────────────┘
```

### 核心设计原则

1. **确定性事实层 + LLM 解释层分离**
   漏斗分解、z-score、赋分制全是确定性代码——可复现、可单元测试。LLM 只负责编排和用大白话解释结果，**不参与计算**，避免幻觉"算错账"。

2. **多因时按需取证，不全查**
   赋分制无法区分多个候选根因时，agent 依据可配置的 Skill（触发条件 → 调哪个工具 → 证实/排除条件）**只查候选相关的数据**，再判断每个候选是否成立。

3. **可配置优先**
   LLM、数据源、账户、技能、告警全部可配置；运营能导入自己的诊断策略，而不是改代码。

### 数据流

```
用户提问「为什么 XX 的 ROI 掉了」
   → chat_api 意图路由 → 匹配账户
   → diagnose()：数据 → 证据层(漏斗分解+z-score) → 推理层(赋分) → 决策层
   → 单因：直接出报告；多因：agent 按 Skill 调工具取证 → 判断
   → generate_report()：大白话报告（LLM / 模板兜底）
   → 返回前端（Markdown 渲染 + ECharts 图表）
```

### 模块职责

| 层 | 模块 | 职责 |
|---|---|---|
| 数据 | `data/schema.py` | 千川指标口径 + 漏斗分解公式 |
| 数据 | `data/synthetic.py` | 合成数据生成器（可注入异常，作 ground truth） |
| 数据 | `data/oceanengine.py` | 巨量千川 Marketing API 客户端 |
| 数据 | `data/loader.py` | 数据源加载（合成数据 / 真实 API 切换） |
| 诊断 | `diagnosis/baseline.py` | 证据层：漏斗偏离检测 + 维度下钻 |
| 诊断 | `diagnosis/root_causes.py` | 根因库（8 类根因 + 证据模式） |
| 诊断 | `diagnosis/scoring.py` | 推理层：赋分制 + 决策层 |
| 诊断 | `diagnosis/engine.py` | 诊断引擎编排 |
| LLM | `llm/client.py` | OpenAI 兼容客户端（DeepSeek/Qwen，支持 function calling） |
| LLM | `llm/agent.py` | 工具调用循环（多因时按 Skill 自主取证） |
| LLM | `llm/supplementary.py` | 取证工具（注册表 + schema） |
| LLM | `llm/report.py` | 报告生成（LLM 综合 + 模板兜底） |
| 告警 | `alerting/scanner.py` | 扫描全部账户筛异常 |
| 告警 | `alerting/webhook.py` | 多目标推送（飞书/钉钉/企微） |
| 告警 | `alerting/runner.py` | 扫描 + 推送的统一入口 |
| 告警 | `alerting/scheduler.py` | 内置定时调度（APScheduler） |
| 接入 | `web/app.py` | FastAPI 后端（REST API） |
| 接入 | `web/pdf.py` | PDF 报告生成（reportlab） |
| 配置 | `settings.py` / `accounts.py` / `skills.py` | 配置持久化（`config/*.json`） |

### 技术栈

- **后端**：Python 3.11+ · FastAPI · uvicorn · APScheduler
- **数据**：pandas · NumPy · pyarrow(Parquet) · DuckDB
- **前端**：原生 HTML/CSS/JS · ECharts（图表）· marked（Markdown 渲染）
- **导出**：reportlab（PDF，中文支持）
- **LLM**：DeepSeek / 通义千问（OpenAI 兼容协议）

## 工作原理

```
用户问"为什么 ROI 下降"
  ↓ 数据层：取千川数据（演示用合成数据 / 真实 API）
  ↓ 证据层：漏斗分解 = 展示/消耗 × CTR × CVR × 下单率 × 客单价，稳健 z-score 检测偏离
  ↓ 推理层：证据映射根因库，赋分制打分排序
  ↓ 决策层：分数悬殊 → 单因直答；分数接近 → 多因
  ↓ 多因：agent 按 Skill 的「触发条件」只查候选相关的数据，判断证实/排除
  ↓ 输出：大白话诊断报告 + 可执行调整建议
```

核心公式：

```
ROAS = 支付金额 / 消耗
     = (展示/消耗) × (点击/展示) × (转化/点击) × (订单/转化) × (支付金额/订单)
     = 展示效率 × CTR × CVR × 下单率 × 客单价
```

## 快速开始

```bash
# 1. 建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell（cmd 用 activate.bat）
pip install -r requirements.txt

# 2. 生成合成数据（含可注入的已知异常，作为 ground truth）
python -m src.data.synthetic

# 3. 启动 Web 应用（推荐）
python -m scripts.web
# 浏览器打开 http://127.0.0.1:8000
```

## Web 界面

顶部 4 个标签页，其中「配置」下含 5 个子页签：

| 页面 | 说明 |
|---|---|
| **对话** | 聊天式诊断入口，支持追问、导出命令、打字机输出、Markdown 渲染 |
| **诊断** | 选账户 → 诊断 → 结论 + 漏斗偏离图 + 根因打分 + 素材下钻 + 报告 |
| **扫描** | 一键扫全部账户，列出异常清单 |
| **配置 · 数据源** | 平台接入凭据（app_id/secret/token），与账户分离 |
| **配置 · 账户** | 增删改店铺/广告主（每个 = 一个账户） |
| **配置 · 模型** | LLM 服务商 / API Key / 模型，可「测试连接」 |
| **配置 · 技能** | 导入/编辑 skill（什么情况调哪个工具），存 `config/skills.json` |
| **配置 · 告警** | 多推送目标（群名称/渠道/webhook/启用）+ 扫描间隔 |

### 数据源 vs 账户（两个层级，别混淆）

```
开发者应用（app_id/secret）  ← 1 套，管"怎么连上平台"
   └─ access_token（可覆盖多个广告主）
        └─ 广告主/账户（advertiser_id）← N 个，每个 = 一个店铺
```

- **数据源** = 接入凭据（门禁卡，一张就够）
- **账户** = 平台下的多个广告主（店铺，N 家）

> 注意：合成数据模式只有 A001/A002 两个演示账户有数据；新增账户需切到「真实 API」模式拉真实数据才有。

## 配置说明

### LLM（配置 → 模型）

不配置也能跑（走模板兜底报告）。配置后走真实 LLM：

```bash
# DeepSeek（默认）
export LLM_API_KEY="sk-xxxx"
# 通义千问（阿里云百炼兼容模式）
export LLM_PROVIDER=qwen
```

也可在「配置 → 模型」页面直接填，存 `config/settings.json`（已 gitignore，key 不入库）。
配置优先级：**模型配置页 > 环境变量/.env > 默认**。

### 告警推送（配置 → 告警）

- **多推送目标**：每个群一个 webhook，带群名称、渠道、启用开关、独立测试
- **扫描间隔**：关闭 / 每小时 / 每 6 小时 / 每天 / 每 3 天 / 每 7 天（应用运行时自动扫+推）

> 内置定时扫描只在 Web 应用运行期间生效；应用关闭可改由 Windows 任务计划 / cron 跑 `python -m scripts.scan`。

## 命令行工具

```bash
python -m scripts.ask "为什么美妆旗舰店的ROI下降了"   # CLI 对话诊断
python -m scripts.diagnose_demo                        # 看确定性中间结果
python -m scripts.scan                                 # 扫描 + 推送
```

## 项目结构

```
├── design.md                 # 设计文档（共识落盘）
├── src/
│   ├── settings.py           # 应用配置持久化（config/settings.json）
│   ├── accounts.py           # 账户管理（config/accounts.json）
│   ├── skills.py             # Skill 知识库（config/skills.json）
│   ├── sessions_store.py     # 对话会话持久化（config/sessions.json）
│   ├── data/
│   │   ├── schema.py         # 千川指标口径 + 漏斗分解公式
│   │   ├── synthetic.py      # 合成数据生成器（可注入异常）
│   │   ├── oceanengine.py    # 巨量千川 API 客户端
│   │   └── loader.py         # 数据源加载（合成/真实 API 切换）
│   ├── diagnosis/
│   │   ├── baseline.py       # 证据层：漏斗偏离检测 + 维度下钻
│   │   ├── root_causes.py    # 根因库
│   │   ├── scoring.py        # 推理层：赋分制 + 决策层
│   │   └── engine.py         # 诊断引擎编排
│   ├── llm/
│   │   ├── client.py         # OpenAI 兼容 LLM 客户端（DeepSeek/Qwen）
│   │   ├── agent.py          # agent 工具调用循环
│   │   ├── supplementary.py  # 取证工具（多因时按 skill 查数据）
│   │   └── report.py         # 报告生成（LLM 综合 + 模板兜底）
│   ├── alerting/
│   │   ├── scanner.py        # 检测层：扫描全部账户筛异常
│   │   ├── webhook.py        # 多目标推送（飞书/钉钉/企微）
│   │   ├── runner.py         # 扫描 + 推送统一入口
│   │   └── scheduler.py      # 内置定时调度（APScheduler）
│   └── web/
│       ├── app.py            # FastAPI 后端
│       ├── pdf.py            # PDF 报告生成（reportlab）
│       └── static/           # 前端（HTML/CSS/JS + ECharts + marked）
├── scripts/
│   ├── web.py                # 启动 Web 应用
│   ├── ask.py                # CLI 对话入口
│   ├── diagnose_demo.py      # 确定性诊断演示
│   └── scan.py               # 检测告警脚本
├── tests/                    # 单元测试
└── data/                     # 生成的合成数据
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest                 # 全部测试（当前 90 个）
pytest --cov=src       # 附带覆盖率（~93%）
```

## 已知限制与二期

- **合成数据只有 2 个演示账户有数据**，新增账户需真实 API
- **真 API 字段待核对**：端点/指标名按公开文档整理，接入时对照 open.oceanengine.com 官方文档（需企业资质）
- **行业大盘数据是 mock**：根因库中「大盘/竞争」的取证工具目前返回模拟数据
- 二期：电商罗盘对账（广告归因成交 vs 店铺真实成交）、ML 基线（Prophet）、打包 exe
