"""删除重复的 efs_* EvolvedFewShot 节点"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # 删除 efs_* 节点
    result = session.run("""
        MATCH (f:EvolvedFewShot)
        WHERE f.id STARTS WITH 'efs_'
        DELETE f
        RETURN count(f) as deleted_count
    """)

    record = result.single()
    deleted = record['deleted_count'] if record else 0

    print(f"已删除 {deleted} 个重复的 efs_* 节点")

    # 验证剩余节点
    result = session.run("""
        MATCH (f:EvolvedFewShot)
        RETURN f.id as id, 
               CASE WHEN f.question_embedding IS NOT NULL THEN '有向量化' ELSE '无向量化' END as status
        ORDER BY f.id
    """)

    print("\n剩余 EvolvedFewShot 节点:")
    for record in result:
        print(f"  {record['id']}: {record['status']}")
