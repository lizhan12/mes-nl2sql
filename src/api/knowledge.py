"""知识库表结构管理接口：表 CRUD、LLM 抽取、批量添加、检索、同步。"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from src.core.config import settings
from src.models.schemas import (
    FewShotSearchItem,
    FieldSearchItem,
    GraphEdgeCreate,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RuntimeRuleSearchItem,
    SchemaSearchItem,
    StructuralEntities,
    SyncFromNeo4jResponse,
    TableBatchAddRequest,
    TableBatchAddResponse,
    TableExtractRequest,
    TableExtractResponse,
    TableKnowledgeDetail,
    TableKnowledgeSummary,
    TableKnowledgeUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge")


@router.get("/tables", response_model=list[TableKnowledgeSummary])
async def list_knowledge_tables(module: str = "", search: str = ""):
    """列出知识库中所有表的摘要信息。

    支持按模块过滤和表名搜索。
    """
    from src.services.knowledge_service import load_all_tables

    tables = await load_all_tables()
    if module:
        tables = [t for t in tables if t["module"] == module]
    if search:
        search_lower = search.lower()
        tables = [t for t in tables if search_lower in t["table_name"].lower()]
    return [TableKnowledgeSummary(**t) for t in tables]


@router.post("/tables/extract", response_model=TableExtractResponse)
async def extract_table_structure(request: TableExtractRequest):
    """使用 LLM 从原始文本中抽取表结构定义。"""
    from src.services.knowledge_service import extract_tables_from_text

    result = await asyncio.to_thread(extract_tables_from_text, request.raw_text)
    tables = [TableKnowledgeUpdate(**t) for t in result.get("tables", [])]
    relations = [GraphEdgeCreate(**r) for r in result.get("relations", [])]
    return TableExtractResponse(tables=tables, relations=relations)


@router.post("/tables/batch-add", response_model=TableBatchAddResponse)
async def batch_add_knowledge_tables(request: TableBatchAddRequest):
    """批量添加表定义到知识库，同时创建关联关系。"""
    from src.services.knowledge_service import update_table
    from src.services.neo4j_graph import add_edge as neo4j_add_edge

    table_names: list[str] = []
    errors: list[str] = []

    # 去重：同名表只保留最后一个（覆盖语义）
    seen: dict[str, int] = {}
    for i, t in enumerate(request.tables):
        seen[t.table_name] = i
    unique_indices = sorted(seen.values())
    unique_tables = [request.tables[i] for i in unique_indices]

    for table_data in unique_tables:
        try:
            ok = await update_table(table_data.table_name, table_data.model_dump())
            if ok:
                table_names.append(table_data.table_name)
        except Exception as exc:
            errors.append(f"表 {table_data.table_name} 添加失败: {exc}")
            logger.warning("批量添加表 %s 失败: %s", table_data.table_name, exc)

    relation_count = 0
    for rel in request.relations:
        try:
            await neo4j_add_edge(
                rel.from_table,
                rel.to_table,
                {
                    "from_field": rel.from_field,
                    "to_field": rel.to_field,
                    "join": rel.join_condition,
                    "join_type": rel.join_type,
                    "desc": rel.description,
                    "confidence": rel.confidence,
                    "note": rel.note,
                },
            )
            relation_count += 1
        except Exception as exc:
            errors.append(f"关系 {rel.from_table}→{rel.to_table} 添加失败: {exc}")
            logger.warning("批量添加关系 %s→%s 失败: %s", rel.from_table, rel.to_table, exc)

    message = f"成功添加 {len(table_names)} 张表、{relation_count} 条关系"
    if errors:
        message += f"，{len(errors)} 项失败"

    return TableBatchAddResponse(
        table_names=table_names,
        relation_count=relation_count,
        message=message,
    )


@router.get("/tables/{table_name}", response_model=TableKnowledgeDetail)
async def get_knowledge_table(table_name: str):
    """获取单张表的完整知识库详情。"""
    from src.services.knowledge_service import get_table

    detail = await get_table(table_name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不在知识库中")
    return TableKnowledgeDetail(**detail)


@router.put("/tables/{table_name}")
async def update_knowledge_table(table_name: str, data: TableKnowledgeUpdate):
    """更新知识库中的表定义，同时同步到 txt 文件和 Neo4j。"""
    from src.services.knowledge_service import update_table

    ok = await update_table(table_name, data.model_dump())
    if not ok:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不在知识库中")
    return {"message": f"表 {data.table_name} 更新成功", "table_name": data.table_name}


@router.get("/tables/{table_name}/columns")
async def get_table_columns_from_db(table_name: str):
    """从数据库获取表的真实列名列表（含类型和注释信息）。"""
    from src.services.db_pool import execution_connection

    with execution_connection() as conn, conn.cursor() as cur:
        # 先检查表是否存在
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table_name,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在或无法获取列信息")
        cur.execute(
            """
            SELECT
                c.column_name,
                c.data_type,
                pg_catalog.col_description(
                    (SELECT oid FROM pg_class WHERE relname = %s),
                    c.ordinal_position
                ) AS column_comment
            FROM information_schema.columns c
            WHERE c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            (table_name, table_name),
        )
        return [
            {"name": r["column_name"], "type": r["data_type"], "comment": r["column_comment"] or ""}
            for r in cur.fetchall()
        ]


@router.delete("/tables/{table_name}")
async def delete_knowledge_table(table_name: str):
    """删除知识库中的表定义，同时从本地文件和 Neo4j 中移除。"""
    from src.services.knowledge_service import delete_table

    ok = await delete_table(table_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")
    return {"message": f"表 {table_name} 已删除"}


@router.post("/search", response_model=KnowledgeSearchResult)
async def search_knowledge(request: KnowledgeSearchRequest):
    """知识库检索：同时检索表结构库、SQL 示例库和字段级索引。

    当 use_rerank=True 时，调用硅基流动 Rerank 模型（配置项 RERANK_MODEL）
    对各路向量召回结果按 query 重新打分并截断到 rerank_top_n。
    Rerank 失败时回退到原排序，保证检索可用性。

    FewShot 检索策略：
      1. 先提取结构化实体，构建 archive_key
      2. 尝试 archive_key 精确匹配（match_type='archive_key_exact'）
      3. 精确匹配失败时，回退向量检索（match_type='vector'）
    """
    from src.graph.entity_lexicon import build_archive_key, extract_structural_entities
    from src.services.neo4j_graph import find_few_shot_by_archive_key
    from src.services.vector_store import (
        get_schema_lookup,
        keyword_search_schema,
        keyword_search_schema_with_scores,
        rerank_documents,
        search_few_shot_with_meta,
        search_fields,
        search_schema_with_meta,
    )
    from src.utils.lifespan import get_few_shot_store, get_schema_store

    schema_store = get_schema_store()
    few_shot_store = get_few_shot_store()
    if not schema_store or not few_shot_store:
        raise HTTPException(status_code=503, detail="向量库尚未初始化，请稍后重试")

    # ── 结构化实体提取 ──
    structural = extract_structural_entities(request.query)
    archive_key = build_archive_key(structural)
    structural_entities = StructuralEntities(
        object_entity=structural.get("object_entity", ""),
        action_type=structural.get("action_type", ""),
        domain=structural.get("domain", ""),
        archive_key=archive_key,
    )

    search_types = request.search_types
    threshold = request.similarity_threshold
    top_k = request.top_k
    use_rerank = request.use_rerank
    rerank_top_n = request.rerank_top_n
    # Rerank 需要宽召回：向量检索多召回一些候选，给 rerank 足够空间精排
    recall_k = min(top_k * 3, 50) if use_rerank else top_k

    schema_results: list[SchemaSearchItem] = []
    few_shot_results: list[FewShotSearchItem] = []
    field_results: list[FieldSearchItem] = []
    runtime_rule_results: list[RuntimeRuleSearchItem] = []
    keyword_tables: list[str] = []

    def _fuse_keyword_to_schema(
        query: str,
        *,
        schema_results: list[SchemaSearchItem],
        keyword_tables: list[str],
    ) -> None:
        """将关键词匹配的表注入 schema_results 实现混合检索融合。

        策略：
        - 关键词已命中的表在 schema_results 中已存在 → 取 max(原分, 关键词分) 提升
        - 关键词命中的表不在 schema_results 中 → 从本地 lookup 查找完整 chunk，以关键词分新增
        - 融合后按 score 降序重排
        """
        if not keyword_tables:
            return

        # 获取带分数的关键词结果
        kw_scored = keyword_search_schema_with_scores(query, top_n=len(keyword_tables))
        if not kw_scored:
            return
        kw_scores: dict[str, float] = {tname: score for tname, _hits, score in kw_scored}

        # 现有 schema_results 中的表名集合
        existing_tables: set[str] = {it.table_name for it in schema_results}

        # 查本地 lookup 获取完整 chunk
        lookup = get_schema_lookup()

        # 第一步：对已在 schema_results 中的表，提升 score
        for item in schema_results:
            if item.table_name in kw_scores:
                item.score = round(max(item.score, kw_scores[item.table_name]), 4)

        # 第二步：对不在 schema_results 中的表，新增条目
        for tname, _hits, kw_score in kw_scored:
            if tname in existing_tables:
                continue
            chunk = lookup.get(tname, "")
            if not chunk:
                continue
            # 解析模块和业务含义
            module = ""
            business_meaning = ""
            for line in chunk.split("\n"):
                stripped = line.strip()
                if stripped.startswith("模块："):
                    module = stripped[len("模块："):].strip()
                elif stripped.startswith("业务含义："):
                    business_meaning = stripped[len("业务含义："):].strip()
            schema_results.append(
                SchemaSearchItem(
                    table_name=tname,
                    module=module,
                    business_meaning=business_meaning,
                    full_text=chunk,
                    score=kw_score,
                )
            )

        # 第三步：按 score 降序重排
        schema_results.sort(key=lambda it: it.score, reverse=True)

    async def _do_search():
        nonlocal schema_results, few_shot_results, field_results, keyword_tables
        nonlocal runtime_rule_results

        if "schema" in search_types:
            docs_with_scores = await search_schema_with_meta(
                schema_store, request.query, k=recall_k, similarity_threshold=threshold
            )
            for doc, score in docs_with_scores:
                meta = doc.metadata
                schema_results.append(
                    SchemaSearchItem(
                        table_name=meta.get("table_name", ""),
                        module=meta.get("module", ""),
                        business_meaning=meta.get("business_meaning", ""),
                        full_text=meta.get("full_text", doc.page_content),
                        score=round(score, 4),
                    )
                )

        if "few_shot" in search_types:
            # ── archive_key 精确匹配优先 ──
            exact_match_found = False
            if structural_entities.object_entity and structural_entities.action_type:
                exact = await find_few_shot_by_archive_key(archive_key)
                if exact:
                    few_shot_results.append(
                        FewShotSearchItem(
                            scenario=exact.get("scenario", ""),
                            question=exact.get("question", ""),
                            full_text=exact.get("full_text", ""),
                            score=1.0,  # 精确匹配分数为 1.0
                            match_type="archive_key_exact",
                            archive_key=archive_key,
                            object_entity=structural_entities.object_entity,
                            action_type=structural_entities.action_type,
                            domain=structural_entities.domain,
                        )
                    )
                    exact_match_found = True
                    logger.info("FewShot archive_key 精确匹配: %s", archive_key)

            # ── 向量检索（精确匹配失败或补充召回）─
            docs = await search_few_shot_with_meta(few_shot_store, request.query, k=recall_k)
            for doc in docs:
                meta = doc.metadata
                # 如果精确匹配已找到，跳过相同的结果
                if exact_match_found and meta.get("archive_key") == archive_key:
                    continue
                # similarity_search_with_relevance_scores 返回 (doc, relevance_score)
                raw_score = doc.metadata.get("_score", 0.0) if hasattr(doc, "metadata") else 0.0
                few_shot_results.append(
                    FewShotSearchItem(
                        scenario=meta.get("scenario", ""),
                        question=meta.get("question", ""),
                        full_text=meta.get("full_text", doc.page_content),
                        score=round(raw_score, 4) if raw_score else 0.0,
                        match_type="vector",
                        archive_key=meta.get("archive_key", ""),
                        object_entity=meta.get("object_entity", ""),
                        action_type=meta.get("action_type", ""),
                        domain=meta.get("domain", ""),
                    )
                )

        if "fields" in search_types:
            try:
                fields = await search_fields(request.query, k=recall_k, threshold=threshold)
                for f in fields:
                    field_results.append(
                        FieldSearchItem(
                            table_name=f.get("table_name", ""),
                            field_name=f.get("field_name", ""),
                            type=f.get("type", ""),
                            comment=f.get("comment", ""),
                            score=round(f.get("score", 0.0), 4),
                        )
                    )
            except Exception as e:
                logger.warning("字段级检索失败（可能向量索引未初始化）: %s", e)

        if "runtime_rule" in search_types:
            try:
                from src.utils.lifespan import get_runtime_rule_store

                runtime_rule_store = get_runtime_rule_store()
                if runtime_rule_store:
                    from src.services.vector_store import search_runtime_rules

                    rules = await search_runtime_rules(runtime_rule_store, request.query, k=recall_k, threshold=threshold)
                    for rule in rules:
                        runtime_rule_results.append(
                            RuntimeRuleSearchItem(
                                question=rule.get("question", ""),
                                normalized_question=rule.get("normalized_question", ""),
                                preferred_main_table=rule.get("preferred_main_table", ""),
                                required_tables=rule.get("required_tables", []),
                                required_joins=rule.get("required_joins", []),
                                source=rule.get("source", ""),
                                score=round(rule.get("score", 0.0), 4),
                            )
                        )
                else:
                    logger.warning("运行时规则向量库未初始化，跳过向量检索")
            except Exception as e:
                logger.warning("运行时规则检索失败: %s", e)

        if "evolved_few_shot" in search_types:
            # 合并到 few_shot 检索（使用统一的 few_shot_store）
            pass

        keyword_tables = keyword_search_schema(request.query, top_n=10)

        # ── 关键词结果融合到 schema_results ──
        # 将 keyword 命中的表注入 schema_results：已存在则加权提升 score，不存在则新增条目。
        # 融合后的 schema_results 一起进入后续 rerank 精排，实现真正的混合检索+融合排序。
        _fuse_keyword_to_schema(
            request.query,
            schema_results=schema_results,
            keyword_tables=keyword_tables,
        )

        # ── Rerank 重排 ──
        # 对融合后的 schema_results 及其他各路结果做 rerank
        # 注意：archive_key_exact 匹配的结果不参与 rerank，保持 score=1.0
        if use_rerank:
            await _apply_rerank(
                request.query,
                schema_results=schema_results,
                few_shot_results=few_shot_results,
                field_results=field_results,
                runtime_rule_results=runtime_rule_results,
                top_n=rerank_top_n,
            )

    async def _apply_rerank(
        query: str,
        *,
        schema_results: list[SchemaSearchItem],
        few_shot_results: list[FewShotSearchItem],
        field_results: list[FieldSearchItem],
        runtime_rule_results: list[RuntimeRuleSearchItem],
        top_n: int | None,
    ) -> None:
        """对各路结果独立调用 rerank，按新分数降序并截断到 top_n。

        注意：FewShot 中 match_type='archive_key_exact' 的结果不参与 rerank，保持 score=1.0。
        """

        # few_shot / runtime_rule：评估"查询语义相似度"而非"文档相关性"
        _SIM_INSTRUCT = (
            "Given a query, determine if the following query is semantically "
            "similar and asks about the same type of information"
        )

        async def _rerank_and_apply(
            items: list, text_fn, score_attr: str = "score",
            exclude_match_type: str | None = None,
            *,
            vllm_instruct: str | None = None,
        ) -> None:
            if not items:
                return
            # 分离需要 rerank 和不需要 rerank 的结果
            if exclude_match_type:
                exact_items = [it for it in items if getattr(it, "match_type", "") == exclude_match_type]
                rerank_items = [it for it in items if getattr(it, "match_type", "") != exclude_match_type]
            else:
                exact_items = []
                rerank_items = items

            if not rerank_items:
                return

            texts = [text_fn(it) for it in rerank_items]
            try:
                ranked = await rerank_documents(query, texts, top_n=top_n, vllm_instruct=vllm_instruct)
            except Exception as exc:
                logger.warning("rerank 失败（%s），保留原排序: %s", score_attr, exc)
                return
            # ranked 已按新分降序；截断到 keep_idx 顺序并写回新分
            new_score_map = dict(ranked)
            reordered = [rerank_items[i] for i, _ in ranked]
            for new_pos, (orig_idx, _) in enumerate(ranked):
                setattr(reordered[new_pos], score_attr, round(new_score_map[orig_idx], 4))
            # 合并：精确匹配结果在前（score=1.0），rerank 结果在后
            items.clear()
            items.extend(exact_items)
            items.extend(reordered)

        # 表结构：rerank 文本只用 business_meaning + 适用场景（从 full_text 末尾）
        # 关键经验：Qwen3-Reranker 是生成式 rerank，对长文本+字段噪音敏感。
        # full_text 里"关键字段：(几十个字段名/类型)"对语义匹配无贡献，反而压低真相关分数。
        # 截断到 _RERANK_TEXT_MAX = 300 字上限。
        def _schema_rerank_text(it) -> str:
            parts: list[str] = []
            bm = (it.business_meaning or "").strip()
            if bm:
                parts.append(bm)
            ft = it.full_text or ""
            # 提取表名/模块（首两行）
            for line in ft.split("\n")[:2]:
                if line.startswith("表名") or line.startswith("模块"):
                    parts.append(line)
            # 提取适用场景（位于关键字段块之后，是短小的人类描述）
            if "适用场景" in ft:
                idx = ft.find("适用场景")
                scenario = ft[idx : idx + 200].strip()
                if scenario and scenario not in parts:
                    parts.append(scenario)
            return "\n".join(parts)[:300]

        await _rerank_and_apply(schema_results, _schema_rerank_text)
        # SQL 示例：使用 question + scenario，archive_key_exact 结果不参与 rerank
        # 注意：few_shot 是"相似查询"匹配，用相似度 instruct 替代默认的文档相关性 instruct
        await _rerank_and_apply(
            few_shot_results,
            lambda it: f"Question: {it.question} | Category: {it.scenario or ''}".strip()[:300],
            exclude_match_type="archive_key_exact",
            vllm_instruct=_SIM_INSTRUCT,
        )
        # 字段级：表名.字段名 + 注释；默认 instruct（文档相关性）适用
        await _rerank_and_apply(
            field_results,
            # 加入表格上下文帮助 rerank 判断
            lambda it: f"[{it.table_name}] {it.field_name}: {it.comment}".strip()[:200],
        )
        # 运行时规则：question + normalized_question；同样用相似度 instruct
        await _rerank_and_apply(
            runtime_rule_results,
            lambda it: f"Rule: {it.question} | Desc: {it.normalized_question or ''}".strip()[:300],
            vllm_instruct=_SIM_INSTRUCT,
        )
        # 进化 few-shot：已合并到 few_shot_results

    await _do_search()

    return KnowledgeSearchResult(
        query=request.query,
        embedding_model=settings.embedding_model,
        rerank_model=settings.rerank_model if request.use_rerank else "",
        structural_entities=structural_entities,
        schema_results=schema_results,
        few_shot_results=few_shot_results,
        field_results=field_results,
        keyword_tables=keyword_tables,
        runtime_rule_results=runtime_rule_results,
    )


@router.post("/sync-from-neo4j", response_model=SyncFromNeo4jResponse)
async def sync_knowledge_from_neo4j():
    """将 Neo4j 中的表结构、SQL 示例、关系图数据同步回本地文件。

    直接覆盖 data/mes_knowledge_base.txt、data/dify_few_shot.txt、data/mes_relation_graph.json。
    """
    from src.services.knowledge_service import sync_from_neo4j

    result = await sync_from_neo4j()
    return SyncFromNeo4jResponse(**result)


@router.get("/download-synced-files")
async def download_synced_files():
    """下载已同步到本地的知识库文件内容，供浏览器下载。"""
    from pathlib import Path

    data_dir = Path("data")
    files = {
        "mes_knowledge_base.txt": data_dir / "mes_knowledge_base.txt",
        "dify_few_shot.txt": data_dir / "dify_few_shot.txt",
        "mes_relation_graph.json": data_dir / "mes_relation_graph.json",
    }
    result = {}
    for name, path in files.items():
        if path.exists():
            result[name] = path.read_text(encoding="utf-8")
        else:
            result[name] = ""
    return {"files": result}
