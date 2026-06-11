"""检查数据库中的视图创建情况。"""
import psycopg

from src.core.config import settings

url = settings.execution_database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
conn = psycopg.connect(url)
cur = conn.cursor()

# 列出已有视图
cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema = 'public' AND (table_name LIKE 'v_m%' OR table_name LIKE 'v_atom%') ORDER BY table_name")
rows = cur.fetchall()
existing = {r[0] for r in rows}
print(f"已存在视图 ({len(existing)}):")
for v in sorted(existing):
    print(f"  {v}")

# 期望的视图
expected = [
    "v_m001_wo_daily_output",
    "v_m002_wo_achievement",
    "v_m003_wip_count",
    "v_atom_sn_travel_result",
    "v_m004_yield_rate",
    "v_m005_fpy",
    "v_m006_wo_cycle_time",
    "v_m007_iqc_rate",
    "v_m008_ipqc_rate",
    "v_m009_fqc_rate",
    "v_m010_top_defects",
    "v_m011_stock",
    "v_m012_daily_issue",
    "v_m014_po_ontime",
    "v_m015_equipment_failure",
    "v_m016_mttr",
    "v_m017_inspection_rate",
]

missing = [v for v in expected if v not in existing]
print(f"\n缺失视图 ({len(missing)}):")
for v in missing:
    print(f"  {v}")

conn.close()
