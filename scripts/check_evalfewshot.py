"""检查 EvalFewShot 节点状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 查询所有标签
    result = session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
    labels = [record["label"] for record in result]

    print("数据库中的所有标签:")
    for label in labels:
        print(f"  - {label}")

    print("\n" + "="*60)

    # 检查是否存在 EvalFewShot
    if "EvalFewShot" in labels:
        print("\n找到 EvalFewShot 标签，检查节点状态...")
        result = session.run("""
            MATCH (n:EvalFewShot)
            RETURN 
                n.id as id,
                n.scenario as scenario,
                n.question as question,
                CASE WHEN n.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
            ORDER BY n.id
        """)

        records = list(result)
        print(f"\nEvalFewShot 节点总数: {len(records)}")
        print("-"*80)

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

        print("-"*80)
        print(f"无向量化的节点数: {no_embedding_count}")
        print(f"有向量化的节点数: {len(records) - no_embedding_count}")
    else:
        print("\n数据库中不存在 EvalFewShot 标签")
        print("可能您指的是 FewShot？")
