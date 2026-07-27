# 企业规章制度 RAG 问答系统

基于 LlamaIndex 的企业规章制度 RAG（检索增强生成）系统，支持 docx / md 文档解析、语义切块、BGE 中文向量检索，可一键部署到 Docker。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     RAG Pipeline                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
│  │  data_       │    │   LlamaIndex  │    │   ChromaDB   │ │
│  │  ingestion.py│───▶│  (Embedding)  │───▶│  (Vectors)   │ │
│  └──────────────┘    └──────────────┘    └──────────────┘ │
│                                                     │      │
│                                                     ▼      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
│  │  rag_query.py│◀───│  OpenAI LLM  │◀───│  Retrieval   │ │
│  └──────────────┘    └──────────────┘    └──────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 一、数据如何存储（ChromaDB）

### 1.1 为什么选择 ChromaDB

| 对比项 | ChromaDB（本地） | pgvector（PostgreSQL 插件） |
|--------|-----------------|---------------------------|
| 部署复杂度 | 单文件，即开即用 | 需要安装 PostgreSQL + 插件 |
| 数据存储 | `./chroma_db/` 目录（SQLite 底层） | 需要额外部署数据库服务 |
| 适用场景 | 中小规模（百万级向量）、个人/团队 | 企业级大规模生产环境 |
| 迁移方式 | 直接复制目录即可 | 需要 pg_dump 导出/导入 |

本项目面向企业内部使用，数据量和并发用户规模有限，ChromaDB 完全满足需求，且部署极简。

### 1.2 ChromaDB 存储结构

```
./chroma_db/
├── 01234567_0123_4567_8901_234567890123/   # 集合 ID 目录（随机生成）
│   ├── data_level0.bin                      # 向量数据（HNSW 索引文件）
│   ├── index_metadata.json                  # 索引元数据
│   └── chroma.sqlite                        # 元数据存储（文档来源、chunk ID 等）
```

**持久化原理：**
- `chromadb.PersistentClient` 启动时打开/创建目录，自动加载已有数据
- 每次新增文档后，调用 `StorageContext` 持久化，ChromaDB 将向量写入 `.bin` 文件、文档元数据写入 `.sqlite`
- 重启服务后向量数据无需重新导入

### 1.3 集合配置（代码）

```python
# data_ingestion.py
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# cosine 距离：1=完全相同，0=正交，-1=完全相反
collection = chroma_client.create_collection(
    name="rules_vectors",
    metadata={"hnsw:space": "cosine"}   # 可选: cosine | l2 | ip
)
```

---

## 二、向量的生成流程（BGE Embedding）

### 2.1 为什么选择 BGE-large-zh-v1.5

| 模型 | 维度 | 中文能力 | 优势 |
|------|------|---------|------|
| `BAAI/bge-large-zh-v1.5` | 1024 | ★★★★★ 专为中文优化 | MRL（Matryoshka Representation Learning）支持变长输出 |
| `text-embedding-ada-002` | 1536 | ★★★ API 调用需付费 | OpenAI 官方，通用性强 |
| `m3e-base` | 768 | ★★★★ 开源免费 | 轻量，适合边缘设备 |

### 2.2 向量生成流程

```
用户文档 (.docx / .md)
       │
       ▼
┌─────────────────────┐
│  文本提取              │ python-docx 解析段落/表格/标题
│  (docx_to_text)       │
└─────────────────────┘
       │
       ▼
┌─────────────────────┐
│  MarkdownNodeParser │ 按 Markdown 标题层级切分语义块
│  语义切块              │
└─────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  BGE-large-zh-v1.5           │
│  (HuggingFaceEmbedding)      │
│                               │  每个 chunk → 1024 维浮点向量
│  中文 query 指令:             │
│  "为这个句子生成表示..."      │
└─────────────────────────────┘
       │
       ▼
  1024 维 Float32 向量
  存入 ChromaDB
```

### 2.3 查询时的向量计算

```python
# rag_service.py - 查询时同样使用 BGE 将问题转为向量
embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-large-zh-v1.5")

query_vector = embed_model.get_query_embedding("请问我年假有几天？")
# 返回: List[float] 长度为 1024
```

### 2.4 相似度检索原理

ChromaDB 使用 **HNSW（Hierarchical Navigable Small World）** 索引：

```
查询向量
    │
    ▼
┌────────────────────────────┐
│  Layer 3  (顶层，粗略搜索)   │  随机采样快速定位大致区域
├────────────────────────────┤
│  Layer 2  (中层)            │
├────────────────────────────┤
│  Layer 1  (下层)            │
├────────────────────────────┤
│  Layer 0  (底层，最近邻搜索)  │  穷举式精确搜索最近向量
└────────────────────────────┘
    │
    ▼
返回 TOP_K 个最相似 chunk
```

---

## 三、语义切块策略（MarkdownNodeParser）

### 3.1 为什么按 Markdown 结构切块

传统切块方式（固定字数）会切断语义边界，例如把"第三章 考勤制度"标题和下面的正文切到不同块。`MarkdownNodeParser` 以 `#` 标题层级为边界，保证每个 chunk 是语义完整的段落。

### 3.2 切块过程示例

**输入 Markdown：**
```markdown
# 公司规章制度

## 第一章 假期制度

### 年假
员工入职满一年后，每年享受 5 天带薪年假。

### 事假
单次事假不超过 3 天，需提前申请。

## 第二章 考勤制度
迟到一次扣 50 元。
```

**切块结果（3 个节点）：**

| Chunk ID | 内容 | 父级标题 |
|----------|------|---------|
| Node-1 | 员工入职满一年后，每年享受 5 天带薪年假。 | 第一章 假期制度 / 年假 |
| Node-2 | 单次事假不超过 3 天，需提前申请。 | 第一章 假期制度 / 事假 |
| Node-3 | 迟到一次扣 50 元。 | 第二章 考勤制度 |

### 3.3 代码实现

```python
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import MetadataMode

parser = MarkdownNodeParser(
    include_metadata=True,       # 在 metadata 中保存文件来源、标题层级
    include_prev_next_rel=True,  # 记录相邻 chunk 关系（用于上下文扩展）
    metadata_mode=MetadataMode.ALL
)

nodes = parser.get_nodes_from_documents(documents)
```

### 3.4 元数据保留

每个 Chunk 节点包含丰富 metadata，检索结果中会一并返回：

```json
{
  "text": "员工入职满一年后，每年享受 5 天带薪年假。",
  "metadata": {
    "source_file": "./data/员工手册.docx",
    "file_type": ".docx",
    "header_1": "第一章 假期制度",
    "header_2": "年假",
    "prev_node_id": "Node-X",
    "next_node_id": "Node-Y"
  },
  "score": 0.87
}
```

---

## 四、Docker 部署

### 4.1 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/zhoudong194/HN_Agent.git
cd HN_Agent

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY

# 3. 启动服务
docker compose up --build

# 4. 访问
# 前端: http://localhost:8000
# API:  http://localhost:8000/api/health
```

### 4.2 x86_64 服务器（阿里云/腾讯云/VMware）

**硬件需求：**

| 资源 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 2 核 | 4 核 |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 10 GB | 20 GB |

Docker 镜像自动使用 `linux/amd64` 架构，无需任何额外配置。`docker-compose.yml` 中已限制容器内存上限为 4 GB。

**部署命令：**
```bash
# 在服务器上执行
docker compose up -d --build
docker compose logs -f   # 查看启动日志
```

### 4.3 ARM 设备（树莓派 4 / ARM 开发板）

树莓派 4 和大多数 ARM 开发板采用 `linux/arm64` 架构，需要构建对应平台的镜像。

**修改 docker-compose.yml**，添加平台参数：

```yaml
services:
  rag-api:
    build:
      context: .
      dockerfile: Dockerfile
      platforms:           # ← 添加这一段
        - linux/arm64     # 树莓派 4 / ARM 开发板
        - linux/amd64     # 保留 x86 兼容
```

**构建并启动（ARM 设备上执行）：**
```bash
# 在树莓派上直接构建（自动选择 arm64）
docker compose build --platform linux/arm64
docker compose up -d

# 首次构建会自动下载 BGE 模型（约 330 MB），请确保网络畅通
```

**树莓派注意事项：**

| 问题 | 解决方案 |
|------|---------|
| 内存不足 | 建议 4GB+ 内存版本；关闭桌面 GUI 以释放约 500MB |
| 磁盘空间 | 模型缓存约 330MB + 向量库，建议 16GB+ SD 卡 |
| 构建速度慢 | ARM 架构 pip 编译 numpy/torch 较慢，首次约 20-30 分钟 |
| 模型下载失败 | 配置 `HF_TOKEN` 环境变量或挂载宿主机缓存 `~/.cache/huggingface` |

### 4.4 数据持久化说明

```
宿主机                          容器内
─────────────────────────────────────────────────
./chroma_db/        →  /app/chroma_db       (向量数据，持久化)
./data/             →  /app/data            (源文档目录)
~/.cache/huggingface →  /root/.cache/huggingface  (模型缓存，加速重启)
.env                →  /app/.env:ro        (只读，防止误改)
```

**重要：首次部署后，数据目录会由 Docker 自动创建，后续上传的文档和向量库都在宿主机目录中保留。**

### 4.5 生产环境建议

```bash
# 1. 使用环境变量而非 .env 文件（更适合容器编排）
docker run -d \
  -e OPENAI_API_KEY=sk-xxx \
  -e OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  -e LLM_MODEL=qwen-plus \
  -p 8000:8000 \
  -v $(pwd)/chroma_db:/app/chroma_db \
  -v $(pwd)/data:/app/data \
  --memory=4g \
  --restart=unless-stopped \
  company-rules-rag
```

```bash
# 2. 使用 Nginx 反向代理（处理 HTTPS + 负载均衡）
# upstream rag_backend {
#     server 127.0.0.1:8000;
# }
#
# server {
#     listen 443 ssl;
#     server_name your-domain.com;
#
#     ssl_certificate /path/to/cert.pem;
#     ssl_certificate_key /path/to/key.pem;
#
#     location / {
#         proxy_pass http://rag_backend;
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#     }
# }
```

```bash
# 3. 使用 Docker Compose + Watchtower 自动更新
# 在 docker-compose.yml 加上部属:
services:
  rag-api:
    image: company-rules-rag:latest
    environment:
      - WATCHTOWER_AUTO_UPDATE=true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

  watchtower:
    image: containrrr/watchtower
    command: --interval 86400
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

---

## 五、核心配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | 空 | 通义千问 API Key，留空则启用"仅检索模式" |
| `OPENAI_API_BASE` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问端点 |
| `LLM_MODEL` | `qwen-plus` | 模型（turbo / plus / max） |
| `EMBED_MODEL_NAME` | `BAAI/bge-large-zh-v1.5` | Embedding 模型 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | 向量库存储路径 |
| `COLLECTION_NAME` | `rules_vectors` | ChromaDB 集合名 |
| `TOP_K` | `5` | 检索返回的段落数 |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | 服务监听地址 |

> **优先级**：进程环境变量 > `.env` 文件 > 代码默认值
> 生产环境（Docker / K8s）建议用环境变量，开发环境用 `.env` 文件。

---

## 六、本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 生成测试数据
python generate_test_data.py

# 3. 执行数据入库
python data_ingestion.py

# 4. 启动 Web 服务
python server.py

# 5. 执行 CLI 问答测试
python rag_query.py
```

---

## 七、项目结构

```
.
├── .env.example                # 配置模板
├── .gitignore                  # 忽略 .env / chroma_db / data 等
├── Dockerfile                  # 多阶段 Docker 构建
├── docker-compose.yml          # 容器编排配置
├── config.py                   # 集中配置加载器
├── data/                       # 源文档目录（上传 .docx / .md）
├── chroma_db/                  # ChromaDB 向量库（持久化存储）
├── static/index.html           # 单文件前端（SPA）
├── data_ingestion.py           # 离线数据入库（切块+向量化）
├── rag_service.py              # RAG 服务层（检索+生成）
├── rag_query.py                # CLI 兼容 wrapper
├── server.py                   # FastAPI Web 后端
├── generate_test_data.py       # 测试数据生成
├── requirements.txt            # 依赖列表
└── README.md                   # 本文档
```

---

## 八、技术栈

| 组件 | 技术 | 作用 |
|------|------|------|
| 核心框架 | LlamaIndex | RAG pipeline 编排 |
| 向量存储 | ChromaDB | 本地持久化向量数据库 |
| 向量检索 | HNSW 索引 | 近似最近邻检索 |
| Embedding | BAAI/bge-large-zh-v1.5 | 中文语义向量（1024 维） |
| 语义切块 | MarkdownNodeParser | 按标题层级语义分块 |
| 文档解析 | python-docx | Word 文档提取 |
| LLM | 通义千问 / DeepSeek / Azure OpenAI / vLLM | 答案生成 |
| Web | FastAPI + uvicorn | REST API + Web UI |
