"""查询数据库中所有节点类型及其向量化状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 查询所有节点类型
    result = session.run("""
        MATCH (n)
        RETURN DISTINCT labels(n) AS labels, count(n) AS count
        ORDER BY labels
    """)

    print("数据库中的节点类型：")
    print("-" * 60)
    for record in result:
        labels = record['labels']
        count = record['count']
        label_str = ', '.join(labels) if labels else '(无标签)'
        print(f"{label_str:40} {count} 个")

    print("\n" + "=" * 60)

    # 检查可能的变体名称
    variants = ['EvalFewShot', 'FewShot', 'RuntimeRule']

    for variant in variants:
        result = session.run(f"""
            MATCH (n:{variant})
            RETURN 
                count(n) AS total,
                count(CASE WHEN n.question_embedding IS NOT NULL THEN 1 END) AS with_embedding,
                count(CASE WHEN n.question_embedding IS NULL THEN 1 END) AS without_embedding
        """)

        record = result.single()
        if record and record['total'] > 0:
            print(f"\n{variant} 节点统计：")
            print(f"  总数: {record['total']}")
            print(f"  有向量化: {record['with_embedding']}")
            print(f"  无向量化: {record['without_embedding']}")
