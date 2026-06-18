"""检查 RuntimeRule 节点的向量化状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 查询所有 RuntimeRule 节点
    result = session.run("""
        MATCH (r:RuntimeRule)
        RETURN 
            r.normalized_question as normalized_question,
            r.question as question,
            r.preferred_main_table as preferred_main_table,
            CASE WHEN r.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
        ORDER BY r.normalized_question
    """)

    records = list(result)

    print(f"RuntimeRule 节点总数: {len(records)}")
    print("\n详细列表:")
    print("-" * 80)

    no_embedding_count = 0
    for record in records:
        status = record['embedding_status']
        if status == '无向量化':
            no_embedding_count += 1
        print(f"标准化问题: {record['normalized_question']}")
        print(f"  原始问题: {record['question']}")
        print(f"  主表: {record['preferred_main_table']}")
        print(f"  状态: {status}")
        print()

    print("-" * 80)
    print(f"无向量化的节点数: {no_embedding_count}")
    print(f"有向量化的节点数: {len(records) - no_embedding_count}")
