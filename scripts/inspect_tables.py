"""检查实际数据库表结构，用于修复视图定义。"""
import psycopg

from src.core.config import settings

url = settings.execution_database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
conn = psycopg.connect(url)

# 需要检查的表
tables = [
    "t_pd_wo",
    "t_qm_inspect_info",
    "t_pd_sn_defect",
    "t_wms_stock",
    "t_wms_wo_material_bill",
    "t_ems_repair_request",
    "t_ems_chk_doc",
]

for t in tables:
    print(f"\n=== {t} ===")
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{t}' ORDER BY ordinal_position")
        for row in cur.fetchall():
            print(f"  {row[0]:30s} {row[1]}")
    except Exception as exc:
        print(f"  ERROR: {exc}")
    cur.close()

conn.close()
