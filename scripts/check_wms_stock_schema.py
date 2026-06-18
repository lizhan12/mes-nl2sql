"""查询 t_wms_stock 表的实际字段结构。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.db_pool import execution_connection

with execution_connection() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 't_wms_stock'
        ORDER BY ordinal_position
    """)
    rows = cur.fetchall()
    print("t_wms_stock 表字段:")
    for row in rows:
        print(f"  {row['column_name']:30s} {row['data_type']}")
