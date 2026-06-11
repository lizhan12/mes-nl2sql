"""检查关联表结构。"""
import psycopg

from src.core.config import settings

url = settings.execution_database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
conn = psycopg.connect(url)

tables = [
    "t_bd_pdline",
    "t_bd_part",
    "t_bd_supplier",
    "t_bd_defect",
    "t_wms_warehouse",
    "t_ems_equipment",
    "t_wms_wo_material_bill_detail",
]

for t in tables:
    print(f"\n=== {t} ===")
    cur = conn.cursor()
    cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{t}' ORDER BY ordinal_position")
    for row in cur.fetchall():
        print(f"  {row[0]:30s} {row[1]}")
    cur.close()

conn.close()
