# 企业规章制度 RAG 问答系统

基于 LlamaIndex + PostgreSQL + pgvector 的企业知识库 RAG 系统，支持文档上传、语义切块、中文向量检索、LLM 问答。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端 (Web UI)                             │
│                     http://localhost:8000                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / REST
         ┌─────────────────┼──────────────────┐
         │                 │                  │
         ▼                 ▼                  ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────────┐
│  PostgreSQL     │ │   FastAPI    │ │   通义千问 /      │
│  (元数据)       │ │   server.py  │ │   OpenAI /       │
│                 │ │              │ │   DeepSeek LLM   │
│  documents 表   │ │              │ │                  │
│  chunks 表      │ │              │ │  生成式答案       │
└────────┬────────┘ └──────┬───────┘ └──────────────────┘
         │                  │
         │   pgvector       │
         │   <=> (cosine)   │
         ▼                  ▼
┌─────────────────────────────────────────────────┐
│              PostgreSQL (向量数据库)              │
│                                                  │
│  chunks.embedding  (1024 维 BGE 向量)           │
│  HNSW 索引 (m=16, ef_construction=200)         │
│  cosine 距离排序 → TOP-K 语义检索               │
└─────────────────────────────────────────────────┘
         │
         │ BGE-large-zh-v1.5 (~330 MB)
         ▼
┌─────────────────────────────────────────────────┐
│              BGE Embedding 模型                   │
│  中文语义向量生成                                 │
└─────────────────────────────────────────────────┘
```

---

## 一、数据如何存储

### 1.1 两张核心表

```
documents 表                     chunks 表
───────────────────────         ───────────────────────────────
id         (UUID, PK)           id         (UUID, PK)
filename   (文件名)              document_id (FK → documents)
file_type  (.docx/.md/.pdf)     text        (原始文本)
file_size  (字节)               header_1/2/3 (来源标题层级)
file_hash  (SHA-256 防重)       source_file  (原始文件路径)
category   (分类标签)            chunk_index  (文档内顺序)
uploader   (上传者)              embedding    (pgvector, 4KB/条)
status     (active/archived)    prev/next_chunk_id (上下游块)
version    (版本号)
uploaded_at / updated_at        ← 每个语义块一条记录
```

### 1.2 为什么用 PostgreSQL 而不是 ChromaDB

| 维度 | ChromaDB | PostgreSQL + pgvector |
|------|----------|----------------------|
| 部署 | 单文件，无依赖 | 需额外部署 PostgreSQL |
| 元数据 | 有限支持 | 完全支持 SQL 查询 |
| 事务 | 无 | ACID 完整事务 |
| 软删除 | 需手动维护 | `status='archived'` 即可 |
| 版本管理 | 不支持 | `version` 字段天然支持 |
| 规模 | ~百万向量 | ~千万向量（分表/分库） |
| SQL 联表查询 | 不支持 | `JOIN documents` 获取元数据 |
| 运维 | 简单 | 标准数据库运维 |

### 1.3 向量存储原理

```sql
-- chunks.embedding 列类型
embedding vector(1024)

-- 检索：余弦距离 (<=>) 越小越相似，ORDER BY 取前 K 条
SELECT id, text,
       embedding <=> '[0.12, -0.34, ...]'::vector AS distance
FROM chunks
ORDER BY distance
LIMIT 5;
```

`1 - distance` = 余弦相似度（0~1，分数越高越相关）。

---

## 二、向量的生成流程

```
源文件 (.docx / .md)
        │
        ▼  python-docx
    提取段落/表格/标题
        │
        ▼  MarkdownNodeParser（按 # 标题层级切块）
    语义 chunks
        │
        ▼  BGE-large-zh-v1.5
    1024 维 Float32 向量
        │
        ▼  struct.pack("<i", dim) + "<{dim}f"
    pgvector 二进制格式 (4 字节头 + 4096 字节数据)
        │
        ▼  psycopg2 + SQL INSERT
    PostgreSQL chunks 表
        │
        ▼  自动创建 HNSW 索引
    可检索向量库
```

---

## 三、语义切块策略

按 Markdown 标题层级切分，保证每个 chunk 是语义完整的段落。

**示例：**

```markdown
# 员工手册
## 第一章 假期制度
### 年假
员工入职满一年后，每年享受 5 天带薪年假。
### 事假
单次事假不超过 3 天。
## 第二章 考勤制度
迟到一次扣 50 元。
```

**切块结果（3 个独立节点）：**

| chunk | 文本内容 | header_1 | header_2 |
|-------|---------|---------|---------|
| #1 | 员工入职满一年后，每年享受 5 天带薪年假。 | 第一章 假期制度 | 年假 |
| #2 | 单次事假不超过 3 天。 | 第一章 假期制度 | 事假 |
| #3 | 迟到一次扣 50 元。 | 第二章 考勤制度 | （无） |

---

## 四、快速部署

### 4.1 一键启动（Docker Compose）

```bash
# 1. 克隆
git clone https://github.com/zhoudong194/HN_Agent.git
cd HN_Agent

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY

# 3. 启动（自动初始化数据库 + 入库 + 启动服务）
docker compose up --build

# 4. 访问
open http://localhost:8000
```

**一条命令完成：**
1. 启动 PostgreSQL + pgvector 容器
2. 等待数据库就绪（healthcheck）
3. 初始化表结构 + 启用 pgvector 扩展
4. 扫描 `data/` 目录，向量化入库
5. 启动 FastAPI 服务

### 4.2 x86_64 服务器（阿里云 / 腾讯云 / VMware）

Docker 镜像默认使用 `linux/amd64`，直接运行：

```bash
docker compose up -d
docker compose logs -f rag-api   # 查看启动日志
```

**资源建议：**

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU | 2 核 | 4 核 |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 20 GB | 50 GB（PostgreSQL WAL + 向量数据增长） |

### 4.3 ARM 设备（树莓派 4 / ARM 开发板）

```yaml
# docker-compose.yml 中修改 build.platforms
services:
  rag-api:
    build:
      context: .
      dockerfile: Dockerfile
      platforms:
        - linux/arm64      # 树莓派 4
        - linux/amd64      # 保留 x86 兼容
```

在 ARM 设备上构建：

```bash
docker compose build --platform linux/arm64
docker compose up -d
```

**树莓派注意事项：**

| 问题 | 解决方案 |
|------|---------|
| 内存不足 | 建议 4GB+ 版本；关闭桌面 GUI |
| 磁盘空间 | 模型 ~330MB + 向量库，建议 16GB+ SD 卡 |
| 构建慢 | ARM 上 pip 编译 numpy/torch 约 20-30 分钟 |
| 模型下载失败 | 配置 `HF_TOKEN` 环境变量 |

### 4.4 数据持久化

```
宿主机                    容器内
──────────────────────────────────────────────
./data/          →  /app/data          (源文档)
./static/        →  /app/static        (前端)
postgres_data/   →  /var/lib/postgresql/data (向量库)
.env             →  环境变量注入
```

---

## 五、本地开发

### 5.1 前置条件

- Python 3.11+
- PostgreSQL 15+ 已安装 pgvector 扩展

**安装 PostgreSQL + pgvector（macOS）：**
```bash
brew install postgresql@15
brew install pgvector
brew services start postgresql@15
```

**安装 PostgreSQL + pgvector（Ubuntu / Debian）：**
```bash
sudo apt install postgresql-15 postgresql-15-pgvector
```

### 5.2 初始化

```bash
# 1. 创建数据库和用户
sudo -u postgres psql -c "CREATE USER raguser WITH PASSWORD 'ragpass';"
sudo -u postgres psql -c "CREATE DATABASE ragdb OWNER raguser;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ragdb TO raguser;"

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库（建表 + 启用 pgvector）
python init_db.py

# 4. 生成测试数据
python generate_test_data.py

# 5. 向量化入库
python data_ingestion.py

# 6. 启动服务
python server.py

# 7. 打开浏览器
open http://localhost:8000
```

---

## 六、API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 服务状态 |
| POST | `/api/query` | RAG 问答 |
| POST | `/api/documents` | 上传文档（.docx / .md） |
| GET | `/api/documents` | 列出文档（支持分页/分类过滤） |
| DELETE | `/api/documents/{id}` | 软删除（归档） |
| DELETE | `/api/documents/{id}/hard` | 永久删除 |
| GET | `/api/categories` | 列出所有分类 |

### 查询示例

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "请问我有多少天年假？", "top_k": 5}'
```

### 上传示例

```bash
curl -X POST http://localhost:8000/api/documents \
  -F "file=@员工手册.docx" \
  -F "category=人力资源" \
  -F "uploader=张三"
```

---

## 七、配置说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | 空 | 通义千问 API Key（留空=仅检索模式） |
| `OPENAI_API_BASE` | 阿里云通义千问端点 | 可切换 DeepSeek / Azure / vLLM |
| `LLM_MODEL` | `qwen-plus` | 模型名 |
| `EMBED_MODEL_NAME` | `BAAI/bge-large-zh-v1.5` | Embedding 模型 |
| `EMBED_DIM` | `1024` | 向量维度 |
| `TOP_K` | `5` | 检索返回段落数 |
| `SIMILARITY_THRESHOLD` | `0.0` | 最低相似度阈值（0=不过滤） |
| `POSTGRES_HOST` | `postgres` | 数据库地址（Docker 内） |

> **优先级**：环境变量 > `.env` > 代码默认值

---

## 八、项目结构

```
.
├── .env.example                # 配置模板
├── .gitignore
├── Dockerfile                  # 多阶段构建
├── docker-compose.yml          # PostgreSQL + API 服务
├── config.py                   # 配置加载（.env + 环境变量）
├── database.py                 # SQLAlchemy 模型 + CRUD + 向量检索
├── init_db.py                 # 数据库初始化脚本
├── data_ingestion.py          # 文档解析 + 切块 + 向量化入库
├── rag_service.py              # RAG 服务层（检索 + LLM 生成）
├── rag_query.py               # CLI wrapper
├── server.py                   # FastAPI Web 后端
├── generate_test_data.py      # 测试数据生成
├── requirements.txt           # Python 依赖
└── README.md                  # 本文档
```

---

## 九、技术栈

| 组件 | 技术 | 作用 |
|------|------|------|
| 向量数据库 | PostgreSQL + pgvector | 向量存储 + 语义检索 |
| 语义索引 | HNSW (m=16, ef=200) | 近似最近邻检索 |
| Embedding | BAAI/bge-large-zh-v1.5 | 中文语义向量（1024 维） |
| 语义切块 | MarkdownNodeParser | 按标题层级分块 |
| 文档解析 | python-docx | Word 文档提取 |
| ORM | SQLAlchemy 2.0 | 数据库操作 |
| LLM | 通义千问 / OpenAI / DeepSeek | 答案生成 |
| Web | FastAPI + uvicorn | REST API + Web UI |
