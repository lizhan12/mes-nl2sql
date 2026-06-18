"""检查 EvalFewShot 节点状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 查询所有 EvalFewShot 节点
    result = session.run("""
        MATCH (f:EvalFewShot)
        RETURN 
            f.id as id,
            f.scenario as scenario,
            f.question as question,
            CASE WHEN f.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
        ORDER BY f.id
    """)

    records = list(result)

    print(f"EvalFewShot 节点总数: {len(records)}")
    print("\n详细列表:")
    print("-" * 80)

    no_embedding_count = 0
    for record in records:
        status = record['embedding_status']
        if status == '无向量化':
            no_embedding_count += 1
        print(f"ID: {record['id']}")
        print(f"  场景: {record['scenario']}")
        print(f"  问题: {record['question'][:50]}...")
        print(f"  状态: {status}")
        print()

    print("-" * 80)
    print(f"无向量化的节点数: {no_embedding_count}")
    print(f"有向量化的节点数: {len(records) - no_embedding_count}")
