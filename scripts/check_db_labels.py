"""查询数据库中所有节点标签"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    result = session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
    labels = [record["label"] for record in result]

    print("数据库中的所有节点标签:")
    for label in labels:
        # 查询该标签的节点数量
        count_result = session.run(f"MATCH (n:{label}) RETURN count(n) as cnt")
        cnt = count_result.single()["cnt"]
        print(f"  {label}: {cnt} 个节点")

    print()

    # 检查是否有 EvalFewShot 相关标签
    eval_labels = [l for l in labels if "eval" in l.lower()]
    if eval_labels:
        print(f"包含 'eval' 的标签: {eval_labels}")
    else:
        print("未找到包含 'eval' 的标签")

    # 检查所有 FewShot 相关标签
    fewshot_labels = [l for l in labels if "fewshot" in l.lower() or "few" in l.lower()]
    print(f"包含 'fewshot' 的标签: {fewshot_labels}")
