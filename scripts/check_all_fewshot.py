"""检查所有 FewShot 相关节点的向量化状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 检查所有标签
    result = session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
    labels = [record["label"] for record in result]

    print("数据库中的所有标签:")
    for label in labels:
        print(f"  - {label}")

    print("\n" + "=" * 80)

    # 检查所有包含 "FewShot" 的标签
    fewshot_labels = [label for label in labels if "FewShot" in label]

    for label in fewshot_labels:
        print(f"\n检查 {label} 节点:")
        print("-" * 80)

        # 查询该标签的所有节点
        result = session.run(f"""
            MATCH (n:{label})
            RETURN 
                n.id as id,
                n.scenario as scenario,
                n.question as question,
                CASE WHEN n.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as embedding_status
            ORDER BY n.id
        """)

        records = list(result)
        print(f"{label} 节点总数: {len(records)}")

        no_embedding_count = 0
        for record in records:
            status = record['embedding_status']
            if status == '无向量化':
                no_embedding_count += 1
            print(f"  ID: {record['id']}")
            print(f"    场景: {record['scenario']}")
            print(f"    问题: {record['question'][:60]}...")
            print(f"    状态: {status}")
            print()

        print(f"  统计: {no_embedding_count} 个无向量化, {len(records) - no_embedding_count} 个有向量化")
