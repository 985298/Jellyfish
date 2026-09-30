#!/usr/bin/env python3
"""一次性回填 scenes/props/costumes 的 project_id（从中间表推导）。

背景：
    Phase 1.1 已在 ORM 模型上为 scenes/props/costumes 增加 nullable project_id
    字段，但项目使用 create_all 建表，不会自动 ALTER 已有表。本脚本对已有
    SQLite 库补加该列，并依据 project_*_links 中间表回填 project_id。

用法（在 backend 目录下执行，因 DATABASE_URL 中的 ./jellyfish.db 是相对路径）::

    .venv/Scripts/python.exe scripts/backfill_project_id.py

幂等性：
    - 列已存在则跳过 ALTER。
    - UPDATE 取 MIN(project_id) 作为归属，重复执行结果一致。
    - 多次运行不会报错、不会引入脏数据。

多项目歧义：
    当一个资产被多个项目链接时，project_id 取 MIN(project_id) 作为确定归属，
    并在日志中报告所有歧义资产，便于人工复核。无链接的游离资产保留 NULL。
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from app.config import settings


# (目标表, 资产外键列名, 中间表名)
TARGETS: list[tuple[str, str, str]] = [
    ("scenes", "scene_id", "project_scene_links"),
    ("props", "prop_id", "project_prop_links"),
    ("costumes", "costume_id", "project_costume_links"),
]


def _to_sync_url(url: str) -> str:
    """把 DATABASE_URL 转成同步驱动 URL。"""
    if url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + url.removeprefix("sqlite+aiosqlite:///")
    if url.startswith("mysql+aiomysql://"):
        return "mysql+pymysql://" + url.removeprefix("mysql+aiomysql://")
    return url


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _index_exists(conn, table: str, index_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA index_list({table})")).fetchall()
    return any(row[1] == index_name for row in rows)


def _ensure_project_id_column(conn, table: str) -> None:
    """若目标表缺少 project_id 列则补加（幂等）。"""
    if _column_exists(conn, table, "project_id"):
        print(f"[SKIP] {table}: project_id 列已存在，跳过 ALTER")
        return
    # SQLite ALTER TABLE ADD COLUMN 不支持完整的外键 ON DELETE 子句语义，
    # 这里只加普通列；新建库通过 create_all 会带完整 FK，已存在库以本列为准。
    # 注意：DDL 不接受绑定参数作为标识符，表名为内部常量，直接拼接安全。
    print(f"[ALTER] {table}: ADD COLUMN project_id VARCHAR(64)")
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN project_id VARCHAR(64)"))
    index_name = f"ix_{table}_project_id"
    if not _index_exists(conn, table, index_name):
        print(f"[INDEX] {table}: CREATE INDEX {index_name}")
        conn.execute(text(f"CREATE INDEX {index_name} ON {table} (project_id)"))


def _report_ambiguous(conn, table: str, asset_col: str, link_table: str) -> None:
    """报告被多个项目链接的资产（仅提示，不阻断）。"""
    rows = conn.execute(
        text(
            f"SELECT {asset_col}, COUNT(DISTINCT project_id) AS cnt, "
            f"GROUP_CONCAT(DISTINCT project_id) AS pids "
            f"FROM {link_table} GROUP BY {asset_col} HAVING cnt > 1"
        )
    ).fetchall()
    for row in rows:
        print(
            f"[WARN] {table}.{asset_col}={row[0]} 关联到 {row[1]} 个项目 "
            f"({row[2]})，取 MIN(project_id) 作为归属"
        )


def _report_orphans(conn, table: str, asset_col: str, link_table: str) -> None:
    """报告无任何项目链接的游离资产（project_id 将保持 NULL）。"""
    rows = conn.execute(
        text(
            f"SELECT id FROM {table} WHERE id NOT IN "
            f"(SELECT DISTINCT {asset_col} FROM {link_table} WHERE {asset_col} IS NOT NULL)"
        )
    ).fetchall()
    orphans = [r[0] for r in rows]
    if orphans:
        print(f"[INFO] {table}: {len(orphans)} 个游离资产无链接，project_id 保持 NULL -> {orphans}")
    else:
        print(f"[INFO] {table}: 无游离资产")


def _backfill_table(conn, table: str, asset_col: str, link_table: str) -> int:
    """回填单个表的 project_id，返回匹配行数。"""
    sql = text(
        f"UPDATE {table} SET project_id = "
        f"(SELECT MIN(l.project_id) FROM {link_table} l WHERE l.{asset_col} = {table}.id) "
        f"WHERE EXISTS (SELECT 1 FROM {link_table} l WHERE l.{asset_col} = {table}.id)"
    )
    result = conn.execute(sql)
    matched = result.rowcount or 0
    print(f"[UPDATE] {table}: 匹配 {matched} 行（含幂等覆盖）")
    return matched


def _report_distribution(conn, table: str) -> None:
    """回填后查询 project_id 分布，便于核对。"""
    rows = conn.execute(
        text(
            f"SELECT COALESCE(project_id, '<NULL>') AS pid, COUNT(*) AS cnt "
            f"FROM {table} GROUP BY project_id ORDER BY cnt DESC"
        )
    ).fetchall()
    print(f"[DIST] {table}: " + ", ".join(f"{r[0]}={r[1]}" for r in rows))


def main() -> int:
    sync_url = _to_sync_url(settings.database_url)
    print(f"[DB] {sync_url}")
    engine = create_engine(sync_url, future=True)

    with engine.begin() as conn:
        # 启用外键约束（仅对新事务有效；ALTER 已有列的 FK 不强校验，但保留语义）
        if sync_url.startswith("sqlite"):
            conn.execute(text("PRAGMA foreign_keys=ON"))

        for table, asset_col, link_table in TARGETS:
            print(f"\n=== {table} (via {link_table}.{asset_col}) ===")
            _ensure_project_id_column(conn, table)
            _report_ambiguous(conn, table, asset_col, link_table)
            _report_orphans(conn, table, asset_col, link_table)
            _backfill_table(conn, table, asset_col, link_table)
            _report_distribution(conn, table)

    engine.dispose()
    print("\n[DONE] backfill_project_id 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
