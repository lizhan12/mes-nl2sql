"""FewShot 旧数据迁移脚本。

将旧版 FewShot 节点（无 archive_key）迁移为结构化版本，
按 question 提取 archive_key / object_entity / action_type / domain 写回 Neo4j。
"""

import asyncio
import json

from neo4j import AsyncGraphDatabase

from src.graph.entity_lexicon import build_archive_key, extract_structural_entities

NEO4J_URI = "bolt://192.168.0.238:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"


async def migrate():
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    async with driver.session() as session:
        # 获取所有 FewShot 节点
        result = await session.run(
            """
            MATCH (f:FewShot)
            RETURN f.id AS id, f.question AS question, f.full_text AS full_text,
                   f.archive_key AS archive_key, f.scenario AS scenario
            ORDER BY f.id
            """
        )
        records = [rec async for rec in result]
        print(f"共找到 {len(records)} 个 FewShot 节点")

        migrated = 0
        skipped = 0
        conflicts: list[dict] = []
        archive_map: dict[str, list[dict]] = {}

        for rec in records:
            question = rec["question"] or ""
            existing_key = rec["archive_key"]

            # 提取结构化实体
            structural = extract_structural_entities(question)
            new_key = build_archive_key(structural)

            if not new_key or not structural["object_entity"]:
                print(f"  [SKIP] 无法提取实体: {question[:60]}")
                skipped += 1
                continue

            if existing_key and existing_key == new_key:
                skipped += 1
                continue

            # 检测冲突
            if new_key in archive_map:
                archive_map[new_key].append({
                    "id": rec["id"],
                    "question": question,
                    "scenario": rec["scenario"],
                })
            else:
                archive_map[new_key] = [{
                    "id": rec["id"],
                    "question": question,
                    "scenario": rec["scenario"],
                }]

            # 写回 Neo4j
            await session.run(
                """
                MATCH (f:FewShot {id: $id})
                SET f.archive_key = $archive_key,
                    f.object_entity = $object_entity,
                    f.action_type = $action_type,
                    f.domain = $domain
                """,
                {
                    "id": rec["id"],
                    "archive_key": new_key,
                    "object_entity": structural["object_entity"],
                    "action_type": structural["action_type"],
                    "domain": structural["domain"],
                },
            )
            migrated += 1
            print(f"  [OK] {rec['id']}: {question[:50]} -> {new_key}")

        # 检测冲突
        for key, items in archive_map.items():
            if len(items) > 1:
                conflicts.append({
                    "archive_key": key,
                    "items": items,
                    "reason": f"{len(items)} 条记录归为同一 archive_key，请人工核实 SQL 是否需要合并",
                })

        print(f"\n迁移完成: {migrated} 个节点已更新, {skipped} 个跳过")
        if conflicts:
            print(f"\n发现 {len(conflicts)} 个冲突:")
            for c in conflicts:
                print(f"  {c['archive_key']}: {c['reason']}")
                for item in c["items"]:
                    print(f"    - {item['id']}: {item['question'][:60]}")
            # 写入冲突报告
            report_path = "scripts/migration_conflicts.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(conflicts, f, ensure_ascii=False, indent=2)
            print(f"\n冲突报告已写入: {report_path}")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(migrate())
