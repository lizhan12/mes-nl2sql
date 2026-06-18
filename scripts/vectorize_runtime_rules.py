"""为 RuntimeRule 节点生成向量化"""
from src.services.neo4j_graph import _get_driver
from src.services.vector_store import _get_embeddings

driver = _get_driver()
embeddings = _get_embeddings()

print("开始为 RuntimeRule 节点生成向量化...")

with driver.session() as session:
    # 查询所有没有向量化的 RuntimeRule
    result = session.run("""
        MATCH (r:RuntimeRule)
        WHERE r.question_embedding IS NULL
        RETURN r.normalized_question as nq,
               r.question as question,
               r.preferred_main_table as main_table,
               r.required_tables as req_tables,
               r.required_joins as req_joins
    """)

    records = list(result)
    print(f"找到 {len(records)} 个需要向量化的 RuntimeRule")

    if not records:
        print("所有 RuntimeRule 都已向量化")
    else:
        # 准备文本用于 embedding
        texts = []
        for r in records:
            # 使用问题文本作为 embedding 内容
            text = f"问题：{r['question']}"
            texts.append(text)

        print(f"正在生成 {len(texts)} 个 embedding...")
        vectors = embeddings.embed_documents(texts)

        # 更新数据库
        updated = 0
        for i, r in enumerate(records):
            session.run("""
                MATCH (r:RuntimeRule {normalized_question: $nq})
                SET r.question_embedding = $embedding
            """, {
                "nq": r['nq'],
                "embedding": vectors[i]
            })
            updated += 1
            print(f"  已更新: {r['question'][:50]}...")

        print(f"\n成功更新 {updated} 个 RuntimeRule 的向量化")

# 验证结果
with driver.session() as session:
    result = session.run("""
        MATCH (r:RuntimeRule)
        RETURN count(r) as total,
               count(CASE WHEN r.question_embedding IS NOT NULL THEN 1 END) as with_emb
    """)
    record = result.single()
    print(f"\n验证: 总计 {record['total']} 个, 有向量化 {record['with_emb']} 个")
