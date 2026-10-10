"""根因库：赋分制的质量上限。

每类根因定义：
  - evidence：它会导致哪些证据因子偏离、偏离方向（up/down）、权重
  - extra_data：确认该根因通常还需补充哪些数据
  - suggestion：典型调整建议模板
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvidencePattern:
    factor: str      # 证据因子名（见 baseline.FUNNEL_FACTORS + 结构集中度/消耗规模）
    direction: str   # "up" 或 "down"
    weight: float    # 权重，越大越关键


@dataclass(frozen=True)
class RootCause:
    id: str
    name: str
    description: str
    evidence: tuple[EvidencePattern, ...]
    extra_data: str
    suggestion: str


ROOT_CAUSES: list[RootCause] = [
    RootCause(
        id="RC01",
        name="素材疲劳/衰退",
        description="主力素材投放过久，点击率与转化率同步下滑",
        evidence=(
            EvidencePattern("CTR", "down", 2.0),
            EvidencePattern("CVR", "down", 2.0),
        ),
        extra_data="分素材 CTR/CVR 趋势、素材首次投放日期",
        suggestion="停投衰退素材，预算转移到新素材/新计划",
    ),
    RootCause(
        id="RC02",
        name="出价/预算调整",
        description="出价抬高导致 CPM 上升、展示效率下降，或预算上调导致消耗激增",
        evidence=(
            EvidencePattern("展示效率", "down", 3.0),
            EvidencePattern("消耗规模", "up", 0.5),
        ),
        extra_data="出价/预算变更记录、分时段 CPM",
        suggestion="回调出价或检查预算上限，避免低效曝光",
    ),
    RootCause(
        id="RC03",
        name="落地页/直播间承接差",
        description="点击后转化与下单环节掉链子（直播间话术/页面体验）",
        evidence=(
            EvidencePattern("CVR", "down", 2.0),
            EvidencePattern("下单率", "down", 2.0),
        ),
        extra_data="直播间停留/互动、落地页跳出率",
        suggestion="优化承接话术/页面加载/主播转化能力",
    ),
    RootCause(
        id="RC04",
        name="商品/价格问题",
        description="客单价下降或下单率下降（涨价、差评、库存、选品问题）",
        evidence=(
            EvidencePattern("客单价", "down", 2.0),
            EvidencePattern("下单率", "down", 2.0),
        ),
        extra_data="商品价格/库存/评价、竞品价格",
        suggestion="检查定价与选品，处理差评与库存",
    ),
    RootCause(
        id="RC05",
        name="大盘/竞争变化",
        description="行业大盘竞争加剧，CPM 上升、CTR 被稀释（全维度同步、较温和）",
        evidence=(
            EvidencePattern("展示效率", "down", 1.5),
            EvidencePattern("CTR", "down", 1.0),
        ),
        extra_data="行业大盘 CPM/CTR 基准、竞品投放量",
        suggestion="识别为外部因素，可错峰投放或观察",
    ),
    RootCause(
        id="RC06",
        name="大促前后效应",
        description="大促/节假日导致的短期转化波动（周期性，非故障）",
        evidence=(),
        extra_data="营销日历、历史同期数据",
        suggestion="识别为周期性波动，谨慎干预",
    ),
    RootCause(
        id="RC07",
        name="流量质量下降",
        description="点击率正常但转化率下降（人群包/流量来源质量变差）",
        evidence=(
            EvidencePattern("CVR", "down", 2.0),
        ),
        extra_data="人群包/流量来源分布、分定向 CVR",
        suggestion="收紧定向、排除低质流量位",
    ),
    RootCause(
        id="RC08",
        name="结构风险/过度集中",
        description="单一素材/计划消耗占比过高，账户风险集中",
        evidence=(
            EvidencePattern("结构集中度", "up", 2.5),
        ),
        extra_data="各素材/计划消耗占比时序",
        suggestion="分散预算，控制单一素材占比上限",
    ),
]


ROOT_CAUSE_BY_ID = {rc.id: rc for rc in ROOT_CAUSES}
