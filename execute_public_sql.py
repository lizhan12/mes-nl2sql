"""执行 public.sql 到 PostgreSQL 数据库。"""

import re
import time
from pathlib import Path

import psycopg

DB_URL = "postgresql://postgres:123456@125.122.155.135:7432/postgres"
SQL_PATH = Path(__file__).parent / "public.sql"


def split_sql(content: str) -> list[str]:
    """按分号分割 SQL 语句，处理字符串和注释。"""
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(content)

    while i < n:
        ch = content[i]

        if in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            current.append(ch)
            if ch == "*" and i + 1 < n and content[i + 1] == "/":
                current.append(content[i + 1])
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if not in_single and not in_double:
            if ch == "-" and i + 1 < n and content[i + 1] == "-":
                current.append(ch)
                in_line_comment = True
                i += 1
                continue
            if ch == "/" and i + 1 < n and content[i + 1] == "*":
                current.append(ch)
                in_block_comment = True
                i += 1
                continue
            if ch == "'":
                in_single = True
                current.append(ch)
            elif ch == '"':
                in_double = True
                current.append(ch)
            elif ch == ";":
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
            else:
                current.append(ch)
        elif in_single:
            current.append(ch)
            if ch == "'":
                # 检查是否是转义的单引号 ''
                if i + 1 < n and content[i + 1] == "'":
                    current.append(content[i + 1])
                    i += 1
                else:
                    in_single = False
        elif in_double:
            current.append(ch)
            if ch == '"':
                in_double = False

        i += 1

    # 剩余部分
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def main() -> None:
    print(f"读取 SQL 文件: {SQL_PATH}")
    content = SQL_PATH.read_text(encoding="utf-8")
    file_size_mb = len(content.encode("utf-8")) / (1024 * 1024)
    print(f"文件大小: {file_size_mb:.1f} MB")

    print("分割 SQL 语句...")
    statements = split_sql(content)
    # 过滤纯空/纯注释语句
    statements = [s for s in statements if not re.match(r"^\s*(--|/\*).*", s, re.DOTALL) and s.strip()]
    print(f"解析到 {len(statements)} 条 SQL 语句")

    print(f"连接数据库: {DB_URL.replace('123456', '****')}")
    conn = psycopg.connect(DB_URL, autocommit=True)
    conn.execute("SET client_encoding TO 'UTF8'")

    success = 0
    failed = 0
    skipped = 0
    start_time = time.time()

    for idx, stmt in enumerate(statements, start=1):
        # 跳过 SET 配置语句（通常不需要）
        first_word = stmt.strip().split(None, 1)[0].upper() if stmt.strip() else ""
        trimmed = stmt.strip()

        try:
            conn.execute(stmt)
            # 简洁输出
            if idx % 500 == 0 or idx == len(statements):
                elapsed = time.time() - start_time
                print(
                    f"  进度: {idx}/{len(statements)} | 成功: {success} 失败: {failed} 跳过: {skipped} | 耗时: {elapsed:.0f}s",
                    flush=True,
                )
            success += 1
        except Exception as exc:
            err_msg = str(exc)
            # 某些错误可以忽略（如已存在的对象）
            if any(kw in err_msg.lower() for kw in ["already exists", "duplicate", "does not exist", "cannot drop"]):
                skipped += 1
                if idx % 500 == 0 or idx == len(statements):
                    elapsed = time.time() - start_time
                    print(
                        f"  进度: {idx}/{len(statements)} | 成功: {success} 失败: {failed} 跳过: {skipped} | 耗时: {elapsed:.0f}s",
                        flush=True,
                    )
            else:
                failed += 1
                preview = trimmed[:120].replace("\n", " ")
                print(f"  [{idx}] 错误: {err_msg[:150]}", flush=True)
                print(f"       SQL: {preview}...", flush=True)

    elapsed = time.time() - start_time
    print(f"\n执行完成！成功: {success} | 失败: {failed} | 跳过: {skipped} | 总耗时: {elapsed:.0f}s")

    conn.close()


if __name__ == "__main__":
    main()
