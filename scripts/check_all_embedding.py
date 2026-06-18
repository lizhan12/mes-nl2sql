"""检查所有节点的向量化状态"""
from src.services.neo4j_graph import _get_driver

driver = _get_driver()

with driver.session() as session:
    # EvolvedFewShot
    result = session.run("""
        MATCH (f:EvolvedFewShot)
        RETURN f.id as id, f.question as question,
               CASE WHEN f.question_embedding IS NOT NULL THEN 'Y' ELSE 'N' END as has_emb
    """)
    records = list(result)
    print(f"=== EvolvedFewShot ({len(records)} nodes) ===")
    for r in records:
        print(f"  {r['id']}: embedding={r['has_emb']} question={r['question'][:50]}")

    # RuntimeRule
    result = session.run("""
        MATCH (r:RuntimeRule)
        RETURN r.normalized_question as nq, r.question as question,
               CASE WHEN r.question_embedding IS NOT NULL THEN 'Y' ELSE 'N' END as has_emb
    """)
    records = list(result)
    print(f"\n=== RuntimeRule ({len(records)} nodes) ===")
    for r in records:
        print(f"  embedding={r['has_emb']} question={r['question'][:50]}")

    # FewShot
    result = session.run("""
        MATCH (f:FewShot)
        RETURN f.id as id,
               CASE WHEN f.question_embedding IS NOT NULL THEN 'Y' ELSE 'N' END as has_emb
    """)
    records = list(result)
    print(f"\n=== FewShot ({len(records)} nodes) ===")
    for r in records:
        print(f"  {r['id']}: embedding={r['has_emb']}")
