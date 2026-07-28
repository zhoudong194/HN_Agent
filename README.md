# 企业规章制度 RAG 问答系统

面向企业内部制度、流程、报销、考勤、采购等文档的本地知识库问答系统。系统支持上传 `.docx`、`.doc`、`.md` 文档，自动抽取文本、结构化切块、生成中文语义向量，使用 PostgreSQL + pgvector 做向量存储与检索，并通过 OpenAI-compatible LLM 接口生成带引用来源的中文回答。

当前系统的核心目标不是做通用聊天机器人，而是做一个可追溯、可维护、可扩展的企业制度助手：

- 问候、感谢、闲聊、系统介绍类问题不进入知识库检索。
- 制度相关问题进入 RAG 流程，返回答案和来源 chunk。
- 无关或过短问题会被引导补充制度关键词。
- 所有文档和 chunk 元数据统一存入 PostgreSQL，便于审计、过滤、归档和后续权限控制。

---

## 1. 系统总览

```text
┌──────────────────────────────────────────────────────────────┐
│ Web UI                                                       │
│ static/index.html                                            │
│ - 文档列表 / 文档上传 / 常见问题 / 问答窗口 / 来源展示        │
└───────────────────────────────┬──────────────────────────────┘
                                │ HTTP JSON / multipart upload
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ FastAPI Backend                                               │
│ server.py                                                     │
│ - /api/query                                                  │
│ - /api/documents                                              │
│ - /api/health                                                 │
│ - /api/categories                                             │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
                ▼                               ▼
┌──────────────────────────────┐   ┌───────────────────────────┐
│ RAG Service                   │   │ Data Ingestion             │
│ rag_service.py                │   │ data_ingestion.py          │
│ - Query Router                │   │ - docx/doc/md text extract │
│ - Embedding query             │   │ - structure-first chunking │
│ - Multi-way retrieval         │   │ - BGE embedding            │
│ - Prompt assembly             │   │ - batch insert             │
│ - LLM generation              │   └─────────────┬─────────────┘
└───────────────┬──────────────┘                 │
                ▼                                ▼
┌──────────────────────────────────────────────────────────────┐
│ Retrieval Engine                                              │
│ recall.py                                                     │
│ - Dense: pgvector cosine search                               │
│ - Sparse: BM25 + jieba                                        │
│ - Exact: PostgreSQL ILIKE                                     │
│ - RRF fusion                                                  │
│ - optional CrossEncoder rerank                                │
│ - relevance gates                                             │
└───────────────┬──────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────┐
│ PostgreSQL + pgvector                                         │
│ database.py                                                   │
│ - documents: source metadata                                  │
│ - chunks: text / headers / embeddings                         │
│ - vector(1024) similarity search                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 端到端流程设计

### 2.1 文档入库流程

```text
用户上传 / data 目录扫描
        │
        ▼
文件去重
SHA-256 hash 写入 documents.file_hash
        │
        ▼
文本抽取
.docx → python-docx
.doc  → textract / docx2txt fallback
.md   → UTF-8 直接读取
        │
        ▼
Markdown-like 标题标准化
文档名 / Heading / 表格行统一转成可解析文本
        │
        ▼
结构优先切块
文档标题 → 章 → 条 → 款/列表/表格
长条款再按长度做二次切分
        │
        ▼
质量过滤
过短文本、低中文比例文本会被跳过
        │
        ▼
BGE-large-zh-v1.5 embedding
每个 chunk 生成 1024 维向量
        │
        ▼
PostgreSQL batch insert
documents + chunks + pgvector embedding
        │
        ▼
BM25 内存索引重建
新文档可参与混合召回
```

对应代码：

- [data_ingestion.py](data_ingestion.py): 文档解析、结构化切块、向量化入库。
- [database.py](database.py): 文档记录、chunk 批量插入、向量检索。
- [server.py](server.py): 上传接口 `POST /api/documents`。

### 2.2 在线问答流程

```text
用户问题
  │
  ▼
Query Router
判断是否需要检索
  │
  ├─ 问候/感谢/系统介绍/无关问题
  │     → 直接返回 chat 响应，sources=[]
  │
  └─ 制度相关问题
        │
        ▼
    BGE query embedding
        │
        ▼
    三路召回
    Dense: pgvector cosine
    Sparse: BM25
    Exact: PostgreSQL ILIKE
        │
        ▼
    相关性过滤
    BM25 score <= 0 丢弃
    dense similarity < 0.45 丢弃
    弱 dense-only 结果拒绝
        │
        ▼
    RRF 融合
        │
        ▼
    CrossEncoder 精排（可选）
    如果本地 reranker 不可用，则保留 RRF 顺序，不伪造高分
        │
        ▼
    组装上下文 prompt
        │
        ▼
    调用 OpenAI-compatible LLM
        │
        ▼
    返回 answer + sources + retrieval_stats
```

对应代码：

- [rag_service.py](rag_service.py): Query Router、RAG 主流程、LLM 调用。
- [recall.py](recall.py): Dense/BM25/Exact/RRF/Rerank/过滤策略。
- [static/index.html](static/index.html): 前端仅在 `retrieval_required=true` 时展示引用区。

---

## 3. 核心能力

| 能力 | 当前实现 |
|------|----------|
| Web UI | 单页 HTML/CSS/JS，支持问答、文档列表、上传、引用展示 |
| API 服务 | FastAPI + uvicorn |
| 文档上传 | `POST /api/documents`，支持 `.docx`、`.doc`、`.md` |
| 批量入库 | `python data_ingestion.py` 扫描 `data/` |
| 文件去重 | SHA-256 hash，避免重复入库同一内容 |
| 文档管理 | 列表、分类过滤、软删除、硬删除 |
| 文本抽取 | python-docx、textract、docx2txt、Markdown 读取 |
| 结构化切块 | 文档标题、章、条、款优先，长文本二次切分 |
| 向量模型 | `BAAI/bge-large-zh-v1.5`，1024 维中文 embedding |
| 向量存储 | PostgreSQL + pgvector |
| 稠密召回 | pgvector cosine similarity |
| 稀疏召回 | BM25 + jieba 中文分词 |
| 精确召回 | PostgreSQL `ILIKE` 短语匹配 |
| 召回融合 | Reciprocal Rank Fusion, RRF |
| 精排 | 可选 `BAAI/bge-reranker-base` CrossEncoder |
| 闲聊拦截 | 问候、感谢、系统介绍、无关问题不进入 RAG |
| LLM 生成 | OpenAI-compatible SDK，默认通义千问兼容端点 |
| 降级模式 | 无 API Key 时返回检索原文，不调用 LLM |

---

## 4. 数据模型设计

### 4.1 documents 表

用于记录源文件级元数据。

| 字段 | 说明 |
|------|------|
| `id` | UUID 主键 |
| `filename` | 原始文件名 |
| `file_type` | `.docx` / `.doc` / `.md` |
| `file_size` | 文件大小，字节 |
| `file_hash` | SHA-256，用于重复检测 |
| `category` | 文档分类，例如人力资源、财务、采购 |
| `uploader` | 上传者 |
| `title` | 文档标题，默认来自文件名 |
| `status` | `active` / `archived` |
| `version` | 版本号，当前默认 `1` |
| `uploaded_at` | 上传时间 |
| `updated_at` | 更新时间 |

### 4.2 chunks 表

用于记录可检索的制度片段。

| 字段 | 说明 |
|------|------|
| `id` | UUID 主键 |
| `document_id` | 所属文档 ID |
| `text` | chunk 原文 |
| `text_hash` | chunk 文本 hash |
| `header_1` | 文档标题或一级标题 |
| `header_2` | 章/二级标题 |
| `header_3` | 条/三级标题 |
| `source_file` | 源文件路径 |
| `chunk_index` | 文档内顺序 |
| `embedding` | pgvector `vector(1024)` |

### 4.3 向量检索 SQL

```sql
SELECT
    c.id,
    c.text,
    d.filename AS doc_filename,
    1 - (c.embedding <=> %s::vector) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'active'
  AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> %s::vector
LIMIT %s;
```

`<=>` 是 pgvector 的 cosine distance 操作符，`1 - distance` 作为 cosine similarity。

---

## 5. 切块策略

制度类文档最重要的是保留条款边界。当前切块策略是“结构优先”，不是单纯按固定长度硬切。

优先层级：

```text
文档标题
  → 章 / 一级制度模块
    → 条 / 具体规则
      → 款 / 列表 / 表格
```


示例： 

```markdown
# 公司采购管理制度

## 第二章 采购流程

### 第四条 采购申请
采购金额超过 5000 元需部门经理审批。
采购金额超过 20000 元需总经理审批。
```

入库后的 chunk 会保留：

```json
{
  "header_1": "公司采购管理制度",
  "header_2": "第二章 采购流程",
  "header_3": "第四条 采购申请",
  "chunk_index": 1
}
```

chunk 文本：

```text
采购金额超过 5000 元需部门经理审批。
采购金额超过 20000 元需总经理审批。
```

如果某个条款过长，会按 `max_chars=700`、`overlap=100` 进行二次切分，同时保留同一组标题元数据。

质量门：

- chunk 少于 30 个字符会跳过。
- 中文字符比例低于 15% 会跳过。
- 空文本或解析失败文本不会入库。

---

## 6. 召回策略

### 6.1 Query Router

RAG 前置路由在 [rag_service.py](rag_service.py) 中完成。

| 类型 | 示例 | 行为 |
|------|------|------|
| 问候 | `hi`、`你好`、`早上好` | 直接问候，`sources=[]` |
| 礼貌 | `谢谢`、`再见` | 直接响应，`sources=[]` |
| 系统介绍 | `你是谁`、`你能做什么` | 说明助手能力，`sources=[]` |
| 无关问题 | `today mood`、无制度关键词问题 | 引导补充制度关键词 |
| 制度问题 | `年假有多少天`、`采购超过 5000 怎么审批` | 进入 RAG |

这样可以避免用户简单问候时，系统还硬返回 5 个无关 chunk。

### 6.2 三路召回

| 路径 | 技术 | 适合的问题 |
|------|------|------------|
| Dense | BGE embedding + pgvector cosine | 语义相近问题，如“休假怎么算” |
| Sparse | BM25 + jieba | 关键词、金额、部门、制度名称 |
| Exact | PostgreSQL `ILIKE` | 精确词组、编号、金额短语 |

### 6.3 相关性过滤

当前过滤策略：

- BM25 `score <= 0` 不参与融合。
- Dense similarity 低于 `0.45` 不参与融合。
- 如果只有 dense 命中且最高分低于 `0.55`，直接拒绝。
- Reranker 不可用时不伪造 `1.000` 分数，改为 `score=null`，保留 `rrf_score`。

### 6.4 RRF 融合

系统使用 Reciprocal Rank Fusion 将多路召回结果融合：

```text
RRF score = Σ weight / (k + rank + 1)
```

默认权重：

- Dense: `1.0`
- BM25: `1.0`
- Exact: `2.0`
- RRF k: `60`

Exact 权重大一些，因为精确短语命中通常更可信。

### 6.5 精排

系统预留 `BAAI/bge-reranker-base` CrossEncoder 精排：

- 如果本地模型存在，使用 CrossEncoder 对 query/chunk pair 打分。
- 如果本地模型不存在，降级为 RRF 顺序。
- 降级时不会把分数伪装成 `1.0`，前端会看到 `score=null` 或 `rrf_score`。

---

## 7. LLM 生成策略

LLM 通过 OpenAI-compatible SDK 调用，默认配置为阿里云通义千问兼容端点：

```text
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

Prompt 约束：

- 只基于检索到的内容回答。
- 检索内容不足时明确告知。
- 使用中文。
- 回答制度问题时尽量引用相关条款。

如果没有配置 `OPENAI_API_KEY`：

- `mode=retrieval_only`
- 不调用 LLM
- 直接返回检索到的原文摘录

---

## 8. API 接口

### 8.1 健康检查

```http
GET /api/health
```

返回示例：

```json
{
  "initialized": true,
  "llm_available": true,
  "embedding_model": "BAAI/bge-large-zh-v1.5",
  "llm_model": "qwen-plus",
  "collection": "PostgreSQL + pgvector",
  "vector_store": "pgvector HNSW (PostgreSQL)",
  "metadata_store": "PostgreSQL",
  "document_count": 4,
  "chunk_count": 10
}
```

### 8.2 问答

```http
POST /api/query
Content-Type: application/json
```

请求：

```json
{
  "question": "年假有多少天？",
  "top_k": 5,
  "min_score": 0.35
}
```

响应：

```json
{
  "query": "年假有多少天？",
  "mode": "llm",
  "answer": "根据员工手册，年假天数与工龄有关...",
  "retrieval_required": true,
  "sources": [
    {
      "id": "chunk-id",
      "text": "工龄 1 年以下...",
      "score": null,
      "rrf_score": 0.0327,
      "header_1": "员工手册",
      "header_2": "第一章 年假制度",
      "header_3": "1.1 年假天数",
      "doc_filename": "员工手册.docx",
      "document_id": "document-id"
    }
  ],
  "retrieval_stats": {
    "dense_count": 5,
    "sparse_count": 2,
    "exact_count": 0,
    "fused_candidates": 6,
    "after_rerank": 6,
    "after_filter": 5,
    "latency_ms": 28.4
  }
}
```

闲聊类请求示例：

```json
{
  "question": "hi",
  "top_k": 5
}
```

响应特点：

```json
{
  "mode": "chat",
  "retrieval_required": false,
  "sources": [],
  "retrieval_stats": {
    "route": "greeting"
  }
}
```

### 8.3 上传文档

```http
POST /api/documents
Content-Type: multipart/form-data
```

示例：

```bash
curl -X POST http://localhost:8000/api/documents \
  -F "file=@员工手册.docx" \
  -F "category=人力资源" \
  -F "uploader=张三"
```

### 8.4 文档列表

```http
GET /api/documents?status=active&category=人力资源&limit=100&offset=0
```

### 8.5 删除文档

软删除：

```http
DELETE /api/documents/{doc_id}
```

永久删除：

```http
DELETE /api/documents/{doc_id}/hard
```

### 8.6 分类列表

```http
GET /api/categories
```

---

## 9. 配置说明

配置读取优先级：

```text
进程环境变量 > .env 文件 > config.py 默认值
```

核心变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | API 监听地址 |
| `PORT` | `8000` | API 端口 |
| `OPENAI_API_KEY` | 空 | LLM API Key，空值时进入仅检索模式 |
| `OPENAI_API_BASE` | DashScope compatible endpoint | OpenAI-compatible API 地址 |
| `LLM_MODEL` | `qwen-plus` | 生成模型 |
| `LLM_TEMPERATURE` | `0.1` | 回答稳定性 |
| `LLM_MAX_TOKENS` | `1024` | 最大输出长度 |
| `EMBED_MODEL_NAME` | `BAAI/bge-large-zh-v1.5` | embedding 模型 |
| `EMBED_DIM` | `1024` | embedding 维度 |
| `HF_TOKEN` | 空 | HuggingFace token，可提升下载稳定性 |
| `DB_HOST` | `localhost` | PostgreSQL 主机 |
| `DB_PORT` | `5433` | PostgreSQL 端口 |
| `DB_NAME` | `ragdb` | 数据库名 |
| `DB_USER` | `raguser` | 数据库用户 |
| `DB_PASSWORD` | `ragpass` | 数据库密码 |
| `TOP_K` | `5` | 默认返回 chunk 数 |
| `SIMILARITY_THRESHOLD` | `0.0` | 外部传入 min_score 时可覆盖 |
| `DATA_DIR` | `./data` | 源文档目录 |

> 注意：代码当前读取的是 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`。如果使用 Docker Compose，需要确保 Compose 环境变量与这些名称一致。

---

## 10. 本地开发流程

### 10.1 推荐环境

- Python 3.11+
- PostgreSQL 15+
- pgvector extension
- 8GB+ 内存更稳，BGE 模型加载会占用一定内存

### 10.2 安装依赖

```bash
pip install -r requirements.txt
```

当前代码实际还依赖以下包，若环境中缺失需要补装：

```bash
pip install psycopg2-binary rank-bm25 jieba python-multipart docx2txt textract sentence-transformers
```

### 10.3 准备环境变量

```bash
copy .env.example .env
```

至少确认：

```env
OPENAI_API_KEY=你的 API Key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

DB_HOST=localhost
DB_PORT=5433
DB_NAME=ragdb
DB_USER=raguser
DB_PASSWORD=ragpass
```

### 10.4 初始化数据库

需要先创建数据库、用户、pgvector extension，并创建 `documents`、`chunks` 表。项目中保留了初始化脚本，但当前主链路已经迁移到 psycopg2，初始化脚本如果继续沿用旧 SQLAlchemy 版本，需要先对齐。

最低要求是 PostgreSQL 中存在：

- `documents`
- `chunks`
- `chunks.embedding vector(1024)`

### 10.5 入库

把制度文档放到 `data/`：

```text
data/
  员工手册.docx
  采购管理制度.md
```

执行：

```bash
python data_ingestion.py
```

### 10.6 启动服务

```bash
python server.py
```

访问：

```text
http://localhost:8000
```

Windows 本地也可以使用项目中的批处理脚本：

```bat
start.bat
stop.bat
restart.bat
```

---

## 11. Docker 部署说明

项目包含 [docker-compose.yml](docker-compose.yml) 和 [Dockerfile](Dockerfile)，目标是让同一份代码在 x86_64 和 ARM64 上都能直接跑起来。

当前方案：

- PostgreSQL 镜像使用 `pgvector/pgvector:pg16`
- API 镜像基于 `python:3.11-slim-bookworm`
- 数据库初始化使用 `schema.sql`
- RBAC 初始化使用 `_rbac_init.sql`
- 文档入库默认由 `AUTO_INGEST=0/1` 控制

本地启动：

```bash
copy .env.example .env
docker compose up --build
```

如果要自动把 `data/` 里的文件在容器启动时入库：

```env
AUTO_INGEST=1
```

如果要发布 GitHub 可直接拉取的多架构镜像，建议用 `docker buildx`：

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t yourname/hn-agent:latest --push .
```

Navicat / 本地工具连接数据库时使用：

```text
host=localhost
port=5433
db=ragdb
user=raguser
password=.env 里的 DB_PASSWORD
```

访问：

```text
http://localhost:8000
```

---

## 12. 项目结构

```text
.
├── config.py                  # 配置加载，环境变量 + .env
├── database.py                # PostgreSQL/pgvector 数据访问层
├── data_ingestion.py          # 文档解析、结构化切块、embedding、入库
├── recall.py                  # 混合召回、RRF、rerank、相关性过滤
├── rag_service.py             # Query Router、RAG 主流程、LLM 调用
├── server.py                  # FastAPI 后端与 REST API
├── rag_query.py               # CLI 兼容入口
├── generate_test_data.py      # 测试数据生成
├── db_inspect.py              # 数据库/索引检查辅助脚本
├── static/
│   └── index.html             # Web UI
├── data/                      # 源文档目录
├── models/                    # 本地模型目录，例如 reranker
├── docker-compose.yml         # PostgreSQL + API 编排
├── Dockerfile                 # API 镜像构建
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量模板
└── README.md                  # 项目说明
```

仓库中还保留了一些历史目录或迁移产物：

- `faiss_index/`
- `embeddings/`
- `rag_meta.db`
- `_backup_faiss/`
- `chroma_db/`

当前主链路是 PostgreSQL + pgvector，这些内容主要用于历史迁移或调试参考。

---

## 13. 技术栈选型

| 层级 | 技术 | 选型原因 |
|------|------|----------|
| Web UI | 原生 HTML/CSS/JS | 项目轻量，部署简单，无需前端构建链 |
| API | FastAPI | 类型清晰、接口开发快、文档自动化好 |
| ASGI Server | uvicorn | FastAPI 标准运行方式 |
| 配置 | python-dotenv | 本地 `.env` 和生产环境变量兼容 |
| 文档解析 | python-docx | 稳定读取 `.docx` 段落、标题、表格 |
| 旧 Word 解析 | textract / docx2txt | 兼容 `.doc` 的兜底方案 |
| 文档对象 | LlamaIndex `Document` | 承接文本和 metadata |
| Embedding | BGE-large-zh-v1.5 | 中文语义检索效果好，1024 维 |
| 向量库 | PostgreSQL + pgvector | 向量、元数据、事务、过滤、归档统一在 SQL 中 |
| 数据访问 | psycopg2 connection pool | 简洁直接，便于控制 SQL 和 pgvector 操作 |
| Dense Recall | pgvector cosine | 语义相似问题召回 |
| Sparse Recall | BM25 + jieba | 中文关键词、金额、条款名召回 |
| Exact Recall | PostgreSQL ILIKE | 精确短语和兜底匹配 |
| Fusion | RRF | 多路召回排序融合，简单稳健 |
| Rerank | BGE reranker CrossEncoder | 可选精排，提升最终 Top-K 质量 |
| LLM | OpenAI SDK compatible API | 可切换通义千问、DeepSeek、OpenAI-compatible 服务 |
| 日志 | RotatingFileHandler | 后台运行时写入 `server.log`，避免日志无限增长 |
| 部署 | Docker Compose | PostgreSQL 与 API 服务可一键编排 |

---

## 14. 当前设计边界与后续演进

当前系统已经能跑通“文档入库 → 混合召回 → LLM 回答 → 来源展示”的主流程，但还可以继续完善：

1. 初始化脚本统一  
   当前数据库访问层已经切到 psycopg2，初始化脚本仍有旧 SQLAlchemy 痕迹，应补一份明确的 `schema.sql` 或迁移工具。

2. requirements 对齐  
   `requirements.txt` 还保留部分 FAISS 时代依赖，也缺少部分当前实际依赖，建议清理并重新锁定。

3. Docker 环境变量对齐  
   Compose 文件应统一使用 `DB_*`，避免容器内连接数据库失败。

4. Reranker 配置化  
   当前 reranker 本地路径写在代码中，建议改成环境变量，例如 `RERANKER_MODEL_PATH`。

5. 权限控制  
   当前接口没有鉴权，后续企业内部使用应加入用户、角色、分类权限、审计日志。

6. 文档版本管理  
   `documents.version` 已预留，但还没有完整的多版本替换、回滚、差异对比流程。

7. PDF 支持  
   当前 README 以 `.docx/.doc/.md` 为主；如果要支持 PDF，需要补齐解析、表格抽取和版面质量验证。

8. 后台任务化  
   上传后 embedding 可能较慢，后续可以改成队列任务，前端轮询入库状态。

---

## 15. 常用命令

启动服务：

```bash
python server.py
```

入库：

```bash
python data_ingestion.py
```

健康检查：

```bash
curl http://localhost:8000/api/health
```

问答：

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"年假有多少天？\",\"top_k\":5}"
```

上传文档：

```bash
curl -X POST http://localhost:8000/api/documents \
  -F "file=@员工手册.docx" \
  -F "category=人力资源" \
  -F "uploader=system"
```
