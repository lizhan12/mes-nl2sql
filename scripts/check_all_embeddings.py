"""检查所有节点的向量化状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 检查 FewShot 节点
    result = session.run("""
        MATCH (f:FewShot)
        RETURN 
            f.id as id,
            f.scenario as scenario,
            f.question as question,
            CASE WHEN f.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
        ORDER BY f.id
    """)

    records = list(result)
    print("=== FewShot 节点 ===")
    print(f"总数: {len(records)}")
    no_emb = sum(1 for r in records if r['embedding_status'] == '无向量化')
    print(f"无向量化: {no_emb}, 有向量化: {len(records) - no_emb}")
    print()

    # 检查 RuntimeRule 节点
    result = session.run("""
        MATCH (r:RuntimeRule)
        RETURN 
            r.normalized_question as id,
            r.question as question,
            CASE WHEN r.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
        ORDER BY r.normalized_question
    """)

    records = list(result)
    print("=== RuntimeRule 节点 ===")
    print(f"总数: {len(records)}")
    no_emb = sum(1 for r in records if r['embedding_status'] == '无向量化')
    print(f"无向量化: {no_emb}, 有向量化: {len(records) - no_emb}")
    if no_emb > 0:
        print("\n无向量化的 RuntimeRule:")
        for r in records:
            if r['embedding_status'] == '无向量化':
                print(f"  - {r['id'][:50]}...")
    print()

    # 检查 Table 节点
    result = session.run("""
        MATCH (t:Table)
        RETURN 
            t.name as id,
            CASE WHEN t.schema_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
    """)

    records = list(result)
    print("=== Table 节点 ===")
    print(f"总数: {len(records)}")
    no_emb = sum(1 for r in records if r['embedding_status'] == '无向量化')
    print(f"无向量化: {no_emb}, 有向量化: {len(records) - no_emb}")
