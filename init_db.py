"""
init_db.py — 初始化 PostgreSQL 数据库（建表 + 启用 pgvector 扩展）。

用法:
    python init_db.py              # 初始化生产库（读取 .env / 环境变量）
    python init_db.py --sample     # 同时生成示例数据（用于 demo）

依赖:
    PostgreSQL 15+ 已安装 pgvector 扩展
    或通过 Docker 启动：docker compose up -d postgres
"""

from __future__ import annotations

import argparse
import io
import os
import sys

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import text

import config
import database

ALEMBIC_TABLE = "alembic_version"


def init_database(with_sample_data: bool = False):
    """创建 extensions / tables，执行完后验证。"""

    # Step 1: 启用 pgvector 扩展（需 superuser 或 CREATE 权限）
    print("[1/4] 启用 pgvector 扩展...")
    with database._get_engine().connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    print("  ✓ pgvector 扩展就绪")

    # Step 2: 创建表（ORM 映射）
    print("[2/4] 创建数据表 (documents / chunks)...")
    database.Base.metadata.create_all(bind=database._get_engine())
    print("  ✓ 表结构就绪")

    # Step 3: 验证
    print("[3/4] 验证表结构...")
    with database._get_engine().connect() as conn:
        result = conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name IN ('documents', 'chunks')
            ORDER BY table_name, ordinal_position;
        """))
        rows = result.fetchall()
        tables = {}
        for tbl, col in [(r[0], r[1]) for r in rows]:
            tables.setdefault(tbl, []).append(col)
        print(f"  ✓ documents  列数: {len(tables.get('documents', []))}")
        print(f"  ✓ chunks     列数: {len(tables.get('chunks', []))}")

        # 验证 pgvector 列类型
        vec_type = conn.execute(text("""
            SELECT attname, format_type(atttypid, atttypmod) AS col_type
            FROM pg_attribute
            WHERE attrelid = 'chunks'::regclass AND attnum > 0
        """)).fetchall()
        print("  ✓ chunks 向量列类型:")
        for name, ctype in vec_type:
            if "vector" in str(ctype):
                print(f"      {name}: {ctype}")

    print("  ✓ HNSW 索引验证:")
    with database._get_engine().connect() as conn:
        indexes = conn.execute(text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'chunks'
              AND indexdef LIKE '%hnsw%';
        """)).fetchall()
        if indexes:
            for idx_name, idx_def in indexes:
                print(f"      {idx_name}")
        else:
            print("      (HNSW 索引将在首次插入向量后自动创建)")

    # Step 4: 示例数据（可选）
    if with_sample_data:
        print("\n[4/4] 生成示例文档...")
        _generate_sample_data()
    else:
        print("\n[4/4] 跳过示例数据（如需请运行 python init_db.py --sample）")

    print("\n" + "=" * 50)
    print("✓ 数据库初始化完成！")
    print(f"   连接地址: {config.DATABASE_URL.split('@')[-1]}")
    print("   接下来运行: python data_ingestion.py")
    print("=" * 50)


def _generate_sample_data():
    """写入示例 Markdown 文件到 data/ 目录（不写入向量库，需重新 ingest）。"""
    import hashlib

    sample_docs = [
        {
            "filename": "员工手册.md",
            "category": "人力资源",
            "content": """# 员工手册

## 第一章 假期制度

### 年假
员工入职满一年后，每年享受 5 天带薪年假。入职满 3 年，年假增加至 10 天。入职满 5 年，年假增加至 15 天。

### 事假
单次事假不超过 3 天，需提前 1 天向直属上级申请。事假期间不发放工资。

### 病假
员工因病无法上班，需在当天上午 9:00 前通过企业微信向部门负责人请假，并提供医院证明。

## 第二章 考勤制度

### 上班时间
公司上班时间为周一至周五 9:00-18:00，午休 12:00-13:00。

### 迟到与早退
- 迟到 30 分钟以内：扣当月绩效 50 元
- 迟到 30 分钟以上：按旷工半天处理
- 早退超过 30 分钟：按旷工半天处理

### 全勤奖励
月度全勤（无迟到、无早退、无请假）员工，发放全勤奖 200 元。

## 第三章 薪酬福利

### 工资发放
工资于每月 15 日发放（如遇节假日提前至前一工作日）。

### 社会保险
公司按国家规定为全员缴纳五险一金，个人部分由公司代扣代缴。

### 餐补
员工每日上班可享受餐补 20 元，按实际出勤天数计发。
""",
        },
        {
            "filename": "报销制度.md",
            "category": "财务",
            "content": """# 报销制度

## 差旅报销

### 交通费
- 飞机票：经济舱实报实销，需提前申请
- 火车票：高铁二等座以下实报实销
- 出租车：市内交通凭票报销，单次不超过 200 元

### 住宿费
- 一线城市：上限 400 元/晚
- 二线城市：上限 300 元/晚
- 报销需提供酒店发票

### 差旅补贴
- 国内出差：150 元/天（含餐费）
- 出差天数不足半天按半天计算

## 日常报销

### 办公用品
单笔 500 元以下由部门负责人审批，500 元以上需总经理审批。

### 业务招待费
需提前填写招待申请，招待结束后 5 个工作日内报销，发票抬头须为公司全称。
""",
        },
    ]

    data_dir = config.DATA_DIR
    os.makedirs(data_dir, exist_ok=True)

    import uuid
    from database import get_db, create_document

    for doc_meta in sample_docs:
        file_path = os.path.join(data_dir, doc_meta["filename"])
        content = doc_meta["content"].encode("utf-8")
        file_hash = hashlib.sha256(content).hexdigest()

        with database._get_engine().connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM documents WHERE file_hash = :h AND status = 'active'"),
                {"h": file_hash},
            ).fetchone()

            if not existing:
                with database._get_db_session() as db:
                    doc, is_new = create_document(
                        db,
                        filename=doc_meta["filename"],
                        file_type=".md",
                        file_size=len(content),
                        content=content,
                        category=doc_meta["category"],
                        uploader="system",
                        title=doc_meta["filename"].replace(".md", ""),
                    )
                    db.commit()
                    print(f"  ✓ 创建文档记录: {doc_meta['filename']} (id={doc.id})")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(doc_meta["content"])
        print(f"  ✓ 写入文件: {file_path}")

    print("\n  提示：示例文件已写入 data/ 目录，请运行 python data_ingestion.py 将其向量化入库")


# 给 database.py 加一个上下文管理器（方便本脚本使用）
def _add_session_context():
    import contextlib
    _orig = database._get_session_local

    def _new():
        cls = _orig()
        return cls()
    database._get_db_session = contextlib.contextmanager(_new)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="初始化 PostgreSQL + pgvector 数据库")
    parser.add_argument("--sample", action="store_true", help="同时生成示例 Markdown 文件")
    args = parser.parse_args()

    _add_session_context()
    init_database(with_sample_data=args.sample)
