"""MES 指标注册表。

定义所有可用的指标视图元数据，包括别名映射、参数定义、歧义术语等。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.config import settings


@dataclass
class ParamDef:
    """指标参数定义（槽位）。

    每个参数对应一个槽位，槽位类型决定提取方式：
      - time:           时间范围提取
      - pdline_name:    产线名称（数据库匹配）
      - process_name:   工序名称（数据库匹配）
      - supplier_name:  供应商名称（数据库匹配）
      - part_no:        料号（正则匹配）
      - equipment_name: 设备名称（数据库匹配）
      - warehouse_name: 仓库名称（数据库匹配）
    """

    name: str  # 参数名（如 date, pdline, part_no）
    type: str  # 槽位类型
    column: str  # 视图中的列名
    match: str = "="  # 匹配方式：= / ILIKE / >=
    required: bool = False
    description: str = ""
    default: str = ""  # 非必填槽位的默认值（None 表示查全部）
    prompt: str = ""  # 追问提示文本


@dataclass
class MetricDef:
    """指标定义。"""

    metric_id: str  # M001, M004, ...
    view_name: str  # v_m004_yield_rate
    name: str  # 中文名称
    category: str  # production / quality / warehouse / equipment
    description: str  # 指标说明
    aliases: list[str] = field(default_factory=list)  # 别名列表
    params: list[ParamDef] = field(default_factory=list)  # 参数定义
    default_limit: int = field(default_factory=lambda: settings.default_limit)
    status: str = "confirmed"  # confirmed / pending
    note: str = ""

    @property
    def sql_template(self) -> str:
        """生成该指标的基础查询模板。"""
        return f"SELECT * FROM {self.view_name}"


# ── 别名 → 指标 ID 精确映射 ─────────────────────────────────────────
# 按 key 长度降序排列，匹配时优先长词
TERM_ALIAS_MAP: dict[str, str] = {
    # 生产类
    "工单计划达成率": "M002",
    "工单日产量": "M001",
    "工单平均周期": "M006",
    "在制工单数": "M003",
    "首次通过率": "M005",
    "过站良品率": "M004",
    "直通率": "M004",
    "达成率": "M002",
    "完工率": "M002",
    "日产量": "M001",
    "周期时间": "M006",
    "良品率": "M004",
    "正品率": "M004",  # "正品率"=良品率
    "通过率": "M004",
    "在制": "M003",
    "日产": "M001",
    "WIP": "M003",
    "FPY": "M005",
    "yield rate": "M004",
    "yield": "M004",
    "cycle time": "M006",
    # 生产口语化
    "产量": "M001",
    "良率": "M004",
    "产出": "M001",
    "完工": "M002",
    "产了多少": "M001",
    "做了多少": "M001",
    "干了多少": "M001",
    "干得怎么样": "M001",
    "干得咋样": "M001",
    "生产情况": "M001",
    "产出情况": "M001",
    "搞了多少": "M001",
    "质量那块": "M004",
    "过了多少": "M001",
    # 质量类
    "来料合格率": "M007",
    "巡检合格率": "M008",
    "成品合格率": "M009",
    "来料检验": "M007",
    "制程检验": "M008",
    "成品检验": "M009",
    "不良统计": "M010",
    "不良类型": "M010",
    "IQC合格率": "M007",
    "IPQC合格率": "M008",
    "FQC合格率": "M009",
    "TOP缺陷": "M010",
    "IQC": "M007",
    "IPQC": "M008",
    "FQC": "M009",
    # 质量口语化
    "来料": "M007",
    "巡检": "M008",
    "成品": "M009",
    "不良": "M010",
    "缺陷": "M010",
    "不良品": "M010",
    "不良分析": "M010",
    "不好的": "M010",  # "不好的"→不良统计
    # 质量英文
    "pass": "M005",   # "pass" → FPY/首次通过率
    # 库存类
    "采购到货": "M014",
    "到货准时率": "M014",
    "库存快照": "M011",
    "实时库存": "M011",
    "物料领用": "M012",
    "当日领料": "M012",
    "领料量": "M012",
    "库存": "M011",
    # 库存口语化
    "领料": "M012",
    "领了多少": "M012",
    "到货": "M014",
    "到料": "M014",
    "库存查询": "M011",
    "库存情况": "M011",
    "存货": "M011",
    # 设备类
    "点检完成率": "M017",
    "设备点检": "M017",
    "设备故障": "M015",
    "维修时长": "M016",
    "平均维修": "M016",
    "故障次数": "M015",
    "MTTR": "M016",
    # 设备口语化
    "故障": "M015",
    "坏了": "M015",
    "停机": "M015",
    "点检": "M017",
    "维修": "M016",
    "MTBF": "M015",
    "设备情况": "M015",
    "设备状态": "M015",
    "设备": "M015",
    # 常见错别字映射
    "在治": "M003",
    "良平": "M004",
    "再制": "M003",
    "故章": "M015",
    "点捡": "M017",
    "产两": "M001",
    "两率": "M004",
}

# ── 歧义术语（需要追问用户澄清）─────────────────────────────────────
AMBIGUOUS_TERMS: dict[str, list[str]] = {
    "合格率": ["M004", "M007", "M008", "M009"],
    "合格": ["M007", "M008", "M009"],  # "合格"可能指来料/IPQC/成品，需追问
    "不良率": ["M004", "M010"],
    "质量": ["M004", "M005", "M007", "M008", "M009", "M010"],
}

# ── 指标参数定义（槽位） ────────────────────────────────────────────
METRIC_PARAMS: dict[str, list[ParamDef]] = {
    "M001": [  # 工单日产量
        ParamDef("date", "time", "统计日期", match=">=", default="近7天", prompt="您要查哪个时间段的产量？"),
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的产量？"),
        ParamDef("part_no", "part_no", "料号", prompt="您要查哪个料号的产量？"),
    ],
    "M002": [  # 工单计划达成率
        ParamDef("date", "time", "统计日期", match=">=", default="近7天", prompt="您要查哪个时间段的达成率？"),
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的达成率？"),
    ],
    "M003": [  # 在制工单数
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的在制工单？"),
        ParamDef("part_no", "part_no", "料号", prompt="您要查哪个料号的在制工单？"),
    ],
    "M004": [  # SN过站良品率
        ParamDef("date", "time", "统计日期", match=">=", default="近7天", prompt="您要查哪个时间段的良品率？"),
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的良品率？"),
        ParamDef("node", "process_name", "工序名称", match="ILIKE", prompt="您要查哪道工序的良品率？"),
    ],
    "M005": [  # 首次通过率FPY
        ParamDef("date", "time", "统计日期", match=">=", default="近7天", prompt="您要查哪个时间段的FPY？"),
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的FPY？"),
        ParamDef("node", "process_name", "工序名称", match="ILIKE", prompt="您要查哪道工序的FPY？"),
    ],
    "M006": [  # 工单平均周期时间
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的周期时间？"),
    ],
    "M007": [  # IQC来料合格率
        ParamDef("supplier", "supplier_name", "供应商名称", match="ILIKE", prompt="您要查哪个供应商的来料合格率？"),
        ParamDef("part_no", "part_no", "料号", prompt="您要查哪个料号的来料合格率？"),
    ],
    "M008": [  # IPQC巡检合格率
        ParamDef("date", "time", "统计日期", match=">=", default="近7天", prompt="您要查哪个时间段的巡检合格率？"),
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的巡检合格率？"),
    ],
    "M009": [  # FQC成品合格率
        ParamDef("part_no", "part_no", "料号", prompt="您要查哪个料号的成品合格率？"),
    ],
    "M010": [  # TOP N 不良类型
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的不良类型？"),
    ],
    "M011": [  # 实时库存快照
        ParamDef("warehouse", "warehouse_name", "仓库名称", match="ILIKE", prompt="您要查哪个仓库的库存？"),
        ParamDef("part_no", "part_no", "料号", prompt="您要查哪个料号的库存？"),
    ],
    "M012": [  # 当日领料量
        ParamDef("date", "time", "领料日期", match=">=", default="近7天", prompt="您要查哪个时间段的领料量？"),
        ParamDef("pdline", "pdline_name", "产线名称", match="ILIKE", prompt="您要查哪条产线的领料量？"),
        ParamDef("part_no", "part_no", "物料料号", prompt="您要查哪个料号的领料量？"),
    ],
    "M014": [  # 采购到货准时率
        ParamDef("supplier", "supplier_name", "供应商名称", match="ILIKE", prompt="您要查哪个供应商的到货准时率？"),
    ],
    "M015": [  # 设备月故障次数
        ParamDef("equipment", "equipment_name", "设备名称", match="ILIKE", prompt="您要查哪台设备的故障次数？"),
    ],
    "M016": [  # MTTR 平均维修时长
        ParamDef("equipment", "equipment_name", "设备名称", match="ILIKE", prompt="您要查哪台设备的维修时长？"),
    ],
    "M017": [  # 设备点检完成率
        ParamDef("equipment", "equipment_name", "设备名称", match="ILIKE", prompt="您要查哪台设备的点检完成率？"),
    ],
}

# ── 指标定义 ──────────────────────────────────────────────────────
ALL_METRICS: list[MetricDef] = [
    MetricDef(
        metric_id="M001",
        view_name="v_m001_wo_daily_output",
        name="工单日产量",
        category="production",
        description="按产线/料号统计每日工单数量和计划数量",
        aliases=["工单日产量", "日产", "日产量"],
        params=METRIC_PARAMS["M001"],
        status="pending",
        note="[待确认] actual_qty字段含义",
    ),
    MetricDef(
        metric_id="M002",
        view_name="v_m002_wo_achievement",
        name="工单计划达成率",
        category="production",
        description="按产线统计完工率",
        aliases=["工单计划达成率", "达成率", "完工率"],
        params=METRIC_PARAMS["M002"],
    ),
    MetricDef(
        metric_id="M003",
        view_name="v_m003_wip_count",
        name="在制工单数",
        category="production",
        description="统计当前在制工单数量和计划总量",
        aliases=["在制工单数", "在制", "WIP"],
        params=METRIC_PARAMS["M003"],
    ),
    MetricDef(
        metric_id="M004",
        view_name="v_m004_yield_rate",
        name="SN过站良品率",
        category="production",
        description="按产线/工序统计过站测试良品率，取每个SN最后一条结果",
        aliases=["良品率", "过站良品率", "通过率", "直通率"],
        params=METRIC_PARAMS["M004"],
    ),
    MetricDef(
        metric_id="M005",
        view_name="v_m005_fpy",
        name="首次通过率FPY",
        category="production",
        description="按产线/工序统计首次测试即通过的比率",
        aliases=["首次通过率", "FPY"],
        params=METRIC_PARAMS["M005"],
    ),
    MetricDef(
        metric_id="M006",
        view_name="v_m006_wo_cycle_time",
        name="工单平均周期时间",
        category="production",
        description="按产线统计工单从下达到完工的平均周期",
        aliases=["工单平均周期", "周期时间"],
        params=METRIC_PARAMS["M006"],
        status="pending",
        note="[待确认] 完工时间字段名",
    ),
    MetricDef(
        metric_id="M007",
        view_name="v_m007_iqc_rate",
        name="IQC来料合格率",
        category="quality",
        description="按供应商/料号统计IQC来料检验合格率",
        aliases=["IQC合格率", "来料合格率", "来料检验"],
        params=METRIC_PARAMS["M007"],
    ),
    MetricDef(
        metric_id="M008",
        view_name="v_m008_ipqc_rate",
        name="IPQC巡检合格率",
        category="quality",
        description="按产线统计IPQC巡检合格率",
        aliases=["IPQC合格率", "巡检合格率", "制程检验"],
        params=METRIC_PARAMS["M008"],
    ),
    MetricDef(
        metric_id="M009",
        view_name="v_m009_fqc_rate",
        name="FQC成品合格率",
        category="quality",
        description="按料号统计FQC成品检验合格率",
        aliases=["FQC合格率", "成品合格率", "成品检验"],
        params=METRIC_PARAMS["M009"],
    ),
    MetricDef(
        metric_id="M010",
        view_name="v_m010_top_defects",
        name="TOP N 不良类型",
        category="quality",
        description="按产线统计不良类型排名",
        aliases=["不良类型", "不良统计", "TOP缺陷"],
        params=METRIC_PARAMS["M010"],
    ),
    MetricDef(
        metric_id="M011",
        view_name="v_m011_stock",
        name="实时库存快照",
        category="warehouse",
        description="按仓库/料号统计当前库存（含正常/冻结/不良品）",
        aliases=["库存", "库存快照", "实时库存"],
        params=METRIC_PARAMS["M011"],
    ),
    MetricDef(
        metric_id="M012",
        view_name="v_m012_daily_issue",
        name="当日领料量",
        category="warehouse",
        description="按产线/料号统计每日领料量",
        aliases=["领料量", "当日领料", "物料领用"],
        params=METRIC_PARAMS["M012"],
    ),
    MetricDef(
        metric_id="M014",
        view_name="v_m014_po_ontime",
        name="采购到货准时率",
        category="warehouse",
        description="按供应商统计月度到货批次",
        aliases=["采购到货", "到货准时率"],
        params=METRIC_PARAMS["M014"],
        status="pending",
        note="[待确认] 期望到货时间字段",
    ),
    MetricDef(
        metric_id="M015",
        view_name="v_m015_equipment_failure",
        name="设备月故障次数",
        category="equipment",
        description="按设备统计月度报修和故障次数",
        aliases=["设备故障", "故障次数"],
        params=METRIC_PARAMS["M015"],
    ),
    MetricDef(
        metric_id="M016",
        view_name="v_m016_mttr",
        name="平均维修时长MTTR",
        category="equipment",
        description="按设备统计月度平均维修时长",
        aliases=["MTTR", "维修时长", "平均维修"],
        params=METRIC_PARAMS["M016"],
        status="pending",
        note="[待确认] repair_end_time字段",
    ),
    MetricDef(
        metric_id="M017",
        view_name="v_m017_inspection_rate",
        name="设备点检完成率",
        category="equipment",
        description="按设备统计月度点检完成率",
        aliases=["点检完成率", "设备点检"],
        params=METRIC_PARAMS["M017"],
        status="pending",
        note="[待确认] check_status字段值",
    ),
]

# 指标 ID → MetricDef 快速查找
METRIC_BY_ID: dict[str, MetricDef] = {m.metric_id: m for m in ALL_METRICS}


def get_metric(metric_id: str) -> MetricDef | None:
    """根据指标 ID 获取指标定义。"""
    return METRIC_BY_ID.get(metric_id)


def list_metrics(category: str = "") -> list[MetricDef]:
    """列出所有指标，可按分类过滤。"""
    if not category:
        return ALL_METRICS
    return [m for m in ALL_METRICS if m.category == category]
