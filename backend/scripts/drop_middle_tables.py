#!/usr/bin/env python3
"""删除三个中间表：project_scene_links / project_prop_links / project_costume_links。

背景：
    Phase 1.1 已在 scenes/props/costumes 表加上 project_id 字段；
    Phase 1.2 已从中间表回填 project_id；
    Phase 1.3 已切换 internal.py / file_usages.py / entity_existence.py /
    shot_assets.py 的查询路径到 asset.project_id 直读。
    故这三个中间表已无活跃读写，可以安全删除。

保留：
    - actors / actor_images / project_actor_links（处于观察期，不动）
    - 不修改任何 SQLAlchemy 模型或 schema 文件

幂等性：
    使用 DROP TABLE IF EXISTS，重复执行不会报错。

用法（在 backend 目录下执行，因 DATABASE_URL 中的 ./jellyfish.db 是相对路径）::

    .venv/Scripts/python.exe scripts/drop_middle_tables.py
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from app.config import settings


# 只删这三个中间表；project_actor_links 保留不动
DROP_TABLES: list[str] = [
    "project_scene_links",
    "project_prop_links",
    "project_costume_links",
]

# 预期保留的表（删除后这些必须仍然存在，作为健康检查）
KEEP_TABLES: list[str] = [
    "actors",
    "actor_images",
    "project_actor_links",
    "projects",
    "chapters",
    "scenes",
    "props",
    "costumes",
]


def _to_sync_url(url: str) -> str:
    """把 DATABASE_URL 转成同步驱动 URL。"""
    if url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + url.removeprefix("sqlite+aiosqlite:///")
    if url.startswith("mysql+aiomysql://"):
        return "mysql+pymysql://" + url.removeprefix("mysql+aiomysql://")
    return url


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": table},
    ).fetchone()
    return row is not None


def _row_count(conn, table: str) -> int:
    if not _table_exists(conn, table):
        return -1
    return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0])


def main() -> int:
    sync_url = _to_sync_url(settings.database_url)
    print(f"[DB] {sync_url}")
    engine = create_engine(sync_url, future=True)

    with engine.begin() as conn:
        # 启用外键约束，保证删除时引用一致性检查
        if sync_url.startswith("sqlite"):
            conn.execute(text("PRAGMA foreign_keys=ON"))

        # 删除前：报告各表行数（便于审计）
        print("\n=== 删除前状态 ===")
        for t in DROP_TABLES:
            if _table_exists(conn, t):
                print(f"[BEFORE] {t}: EXISTS, rows={_row_count(conn, t)}")
            else:
                print(f"[BEFORE] {t}: NOT EXISTS（已删除，跳过）")

        # 执行删除
        print("\n=== 执行 DROP TABLE ===")
        for t in DROP_TABLES:
            if _table_exists(conn, t):
                print(f"[DROP] {t}")
                conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
            else:
                print(f"[SKIP] {t}: 已不存在")

    # 验证：删除后查询表是否仍存在
    print("\n=== 删除后验证 ===")
    with engine.connect() as conn:
        for t in DROP_TABLES:
            exists = _table_exists(conn, t)
            status = "STILL EXISTS !!" if exists else "GONE [ok]"
            print(f"[VERIFY] {t}: {status}")

        print("\n=== 保留表健康检查 ===")
        all_keep_ok = True
        for t in KEEP_TABLES:
            exists = _table_exists(conn, t)
            if not exists:
                all_keep_ok = False
                print(f"[WARN] {t}: NOT EXISTS（不应缺失！）")
            else:
                print(f"[KEEP] {t}: EXISTS, rows={_row_count(conn, t)}")

    engine.dispose()
    print("\n[DONE] drop_middle_tables 完成")
    return 0 if all_keep_ok else 2


if __name__ == "__main__":
    sys.exit(main())
