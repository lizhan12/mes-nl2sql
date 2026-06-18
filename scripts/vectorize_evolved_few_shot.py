"""为缺失向量化的 EvolvedFewShot 节点补全 embedding。"""
from src.services.vector_store import build_neo4j_evolved_few_shot_store

print("开始补全 EvolvedFewShot 向量化...")
store = build_neo4j_evolved_few_shot_store(force_rebuild=False)

if store:
    print("向量化补全完成")
else:
    print("无数据或补全失败")
