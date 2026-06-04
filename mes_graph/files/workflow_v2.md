# MES NL2SQL — Dify工作流 v2（基于反思后的优化版）

## 与v1的核心差异

| 改动点 | v1 | v2 |
|--------|----|----|
| BFS算法 | 统一hop数=2 | 业务域感知，跨域cost=2 |
| 关系图 | 无置信度 | high/medium标记，7条待人工确认 |
| JOIN类型 | 全用JOIN | 按置信度自动选INNER/LEFT JOIN |
| 失败模式 | 静默失败 | 明确输出warning字段 |
| 意图输出 | 无域信息 | 新增intent_domains引导BFS方向 |
| 知识库chunk | 无枚举值 | 包含状态字段枚举值 |

---

## 工作流节点（共7个，新增域感知节点）

```
[开始]
  → [节点1: 意图理解+域识别]   ← 新增 intent_domains 输出
  → [节点2A: 表结构检索]        ← 并行
  → [节点2B: SQL示例检索]       ← 并行
  → [节点3: BFS域感知扩展]      ← 输入增加 intent_domains
  → [节点4: Schema组装]
  → [节点5: SQL生成]            ← Prompt增加枚举值+warning
  → [节点6: 安全+格式校验]
  → [节点7: 置信度提示输出]     ← 新增：有warning时提示用户核实
  → [结束]
```

---

## 节点1：意图理解（Prompt更新）

```
你是MES系统数据分析专家。分析用户问题，输出结构化查询意图。

MES业务域：
- production(t_pd_)：工单、SN追溯、过站、不良、计划
- quality(t_qm_)：IQC/IPQC/FQC检验、质量文件
- warehouse(t_wms_)：库存、入出库、领退料
- equipment(t_ems_)：设备台账、报修、保养、点检
- master(t_bd_)：料号、BOM、产线、工序（基础数据，几乎总是需要）

仅输出JSON，不加任何说明：
{
  "anchor_tables": [],
  "search_queries": ["查询词1","查询词2","查询词3"],
  "intent_domains": [],
  "time_range": "",
  "filters": [],
  "ambiguity": ""
}

规则：
- intent_domains：从 production/quality/warehouse/equipment/master 中选，可多选
- anchor_tables：只填100%确定的表名，不确定宁可留空
- search_queries：包含"用户没说但逻辑上必要"的词（如说"良品率"要补"合格数"）

用户问题：{{#sys.query#}}
```

---

## 节点3：BFS图扩展（代码节点）

粘贴 `dify_code_node_v2.py` 全部内容。

**输入变量**（新增 intent_domains_str）：
- `anchor_tables_str`：节点1输出的 anchor_tables（JSON转字符串）
- `retrieved_tables_str`：节点2A召回结果中提取的表名
- `intent_domains_str`：节点1输出的 intent_domains（如 "production,quality"）

**输出变量**：
- `expanded_tables`：扩展后表名
- `join_hints`：JOIN路径（含LEFT JOIN标记）
- `warning`：置信度警告（空字符串=无警告）

---

## 节点7：置信度提示输出（条件节点）

Dify支持IF/ELSE条件节点：

```
IF 节点6.warning != ""
  → 在最终回复里附加一段话：
    "⚠️ 注意：此查询涉及部分未经完全确认的表关联关系（{{warning}}），
     建议先在测试环境验证SQL结果的正确性。"
ELSE
  → 正常输出SQL
```

---

## 上线前必做：人工校验

运行系统之前，先把 `relation_checklist.md` 交给数据库开发人员或业务骨干，
逐行确认7条medium置信度关联是否正确。每确认一条，在代码节点GRAPH中把
对应edge的 `"confidence": "medium"` 改为 `"confidence": "high"`。

这是整个方案准确性最关键的一步，不能跳过。

---

## 成本方案对比（选型参考）

| 方案 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **本方案（RAG+BFS）** | 表多、预算敏感、需要精细控制 | 成本低、可解释、可调试 | 关系图需维护、冷启动召回差 |
| **全量Schema（长上下文模型）** | 表少(<100)或预算充足 | 无需关系图、实现简单 | 每次消耗大量token、慢、贵 |
| **Fine-tune专用模型** | 数据量大(>5000条NL-SQL对)、高频使用 | 准确率高、响应快 | 冷启动成本极高、需持续维护 |

如果你们的MES查询以高频固定报表为主（如"今日产量"每天问几百次），
建议对这类查询单独做**SQL模板缓存**：用户问题→匹配已知模板→直接填参数执行，
绕过LLM，响应时间从8秒降到<1秒，且100%准确。

