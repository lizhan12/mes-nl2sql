"""基于实际表结构创建指标视图。"""
import psycopg

from src.core.config import settings

url = settings.execution_database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
conn = psycopg.connect(url)
conn.autocommit = True
cur = conn.cursor()

# 先检查关联表是否存在
print("=== 检查关联表 ===")
for t in ["t_bd_pdline", "t_bd_part", "t_bd_supplier", "t_bd_defect", "t_wms_warehouse", "t_ems_equipment", "t_wms_wo_material_bill_detail"]:
    try:
        cur.execute(f"SELECT 1 FROM {t} LIMIT 0")
        print(f"  {t}: OK")
    except Exception as exc:
        print(f"  {t}: MISSING ({exc})")

conn.close()
