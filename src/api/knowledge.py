"""知识库表结构管理接口：表 CRUD、LLM 抽取、批量添加、检索、同步。"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from src.models.schemas import (
    EvolvedFewShotSearchItem,
    FewShotSearchItem,
    FieldSearchItem,
    GraphEdgeCreate,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RuntimeRuleSearchItem,
    SchemaSearchItem,
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
    from src.graph.nodes import _get_table_columns

    cols = _get_table_columns(table_name)
    if cols is None:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在或无法获取列信息")
    from src.services.db_pool import execution_connection

    with execution_connection() as conn, conn.cursor() as cur:
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
    """知识库检索：同时检索表结构库、SQL 示例库和字段级索引。"""
    import src.graph.nodes as nodes
    from src.services.vector_store import (
        keyword_search_schema,
        search_few_shot_with_meta,
        search_fields,
        search_schema_with_meta,
    )

    schema_store = nodes._schema_store
    few_shot_store = nodes._few_shot_store
    if not schema_store or not few_shot_store:
        raise HTTPException(status_code=503, detail="向量库尚未初始化，请稍后重试")

    search_types = request.search_types
    threshold = request.similarity_threshold
    top_k = request.top_k

    schema_results: list[SchemaSearchItem] = []
    few_shot_results: list[FewShotSearchItem] = []
    field_results: list[FieldSearchItem] = []
    runtime_rule_results: list[RuntimeRuleSearchItem] = []
    evolved_few_shot_results: list[EvolvedFewShotSearchItem] = []
    keyword_tables: list[str] = []

    async def _do_search():
        nonlocal schema_results, few_shot_results, field_results, keyword_tables
        nonlocal runtime_rule_results, evolved_few_shot_results

        if "schema" in search_types:
            docs_with_scores = await search_schema_with_meta(
                schema_store, request.query, k=top_k, similarity_threshold=threshold
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
            docs = await search_few_shot_with_meta(few_shot_store, request.query, k=top_k)
            for doc in docs:
                meta = doc.metadata
                few_shot_results.append(
                    FewShotSearchItem(
                        scenario=meta.get("scenario", ""),
                        question=meta.get("question", ""),
                        full_text=meta.get("full_text", doc.page_content),
                        score=0.0,
                    )
                )

        if "fields" in search_types:
            try:
                fields = await search_fields(request.query, k=top_k, threshold=threshold)
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
                runtime_rule_store = nodes._runtime_rule_store
                if runtime_rule_store:
                    from src.services.vector_store import search_runtime_rules

                    rules = await search_runtime_rules(runtime_rule_store, request.query, k=top_k, threshold=threshold)
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
            try:
                evolved_few_shot_store = nodes._evolved_few_shot_store
                if evolved_few_shot_store:
                    docs_with_scores = await evolved_few_shot_store.similarity_search_with_score(request.query, k=top_k)
                    for doc, score in docs_with_scores:
                        if score >= threshold:
                            meta = doc.metadata
                            evolved_few_shot_results.append(
                                EvolvedFewShotSearchItem(
                                    full_text=meta.get("full_text", doc.page_content),
                                    scenario=meta.get("scenario", ""),
                                    question=meta.get("question", ""),
                                    score=round(score, 4),
                                )
                            )
                else:
                    logger.warning("进化 few-shot 向量库未初始化，跳过向量检索")
            except Exception as e:
                logger.warning("进化 few-shot 检索失败: %s", e)

        keyword_tables = keyword_search_schema(request.query, top_n=10)

    await _do_search()

    return KnowledgeSearchResult(
        query=request.query,
        schema_results=schema_results,
        few_shot_results=few_shot_results,
        field_results=field_results,
        keyword_tables=keyword_tables,
        runtime_rule_results=runtime_rule_results,
        evolved_few_shot_results=evolved_few_shot_results,
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
