# Company Rules RAG System

基于 LlamaIndex 的企业规章制度 RAG（检索增强生成）系统。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      RAG Pipeline                          │
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

## 组件说明

### 1. data_ingestion.py (离线入库)
- 扫描 `./data` 目录下的 Word/PDF/Markdown 文件
- 使用 `python-docx` 解析 Word 文档
- 通过 `MarkdownNodeParser` 进行语义分块
- 使用 **BGE** (`BAAI/bge-large-zh-v1.5`) 计算向量
- 存储到 **ChromaDB** 本地向量库

### 2. rag_query.py (在线问答)
- 加载 BGE 向量模型
- 连接 ChromaDB 向量库构建检索器
- 配置 OpenAI 兼容 LLM（支持切换模型）
- 提供 `query_policy()` 函数进行 RAG 问答
- 无 API Key 时自动降级为直接检索模式

## 配置

### 环境配置 (.env 文件)

本项目使用 `.env` 文件管理配置。**`.env` 已被 `.gitignore` 忽略，不会被提交到 git**。

```bash
# 1. 复制示例模板
cp .env.example .env          # macOS / Linux
copy .env.example .env        # Windows

# 2. 编辑 .env，填入你的 API Key 和自定义参数
#    OPENAI_API_KEY=sk-...
#    OPENAI_API_BASE=https://api.deepseek.com/v1   # 切换供应商
#    LLM_MODEL=deepseek-chat                       # 对应模型名
```

### 主要配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | 空 | 通义千问 API Key，留空则启用"仅检索模式" |
| `OPENAI_API_BASE` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问端点 |
| `LLM_MODEL` | `qwen-plus` | 通义千问模型（可选 turbo / plus / max） |
| `EMBED_MODEL_NAME` | `BAAI/bge-large-zh-v1.5` | Embedding 模型 |
| `HF_TOKEN` | 空 | HuggingFace Token（加速模型下载） |
| `TOP_K` | `5` | 检索返回的段落数 |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Web 服务监听地址 |

### 切换 LLM 供应商示例

**DeepSeek**（便宜、中文强）：
```env
OPENAI_API_KEY=sk-your-deepseek-key
OPENAI_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

**Azure OpenAI**：
```env
OPENAI_API_KEY=your-azure-key
OPENAI_API_BASE=https://YOUR_RESOURCE.openai.azure.com/openai/deployments/YOUR_DEPLOYMENT
LLM_MODEL=YOUR_DEPLOYMENT_NAME
```

**本地 vLLM**：
```env
OPENAI_API_KEY=EMPTY
OPENAI_API_BASE=http://localhost:8000/v1
LLM_MODEL=/path/to/your/model
```

> 💡 **优先级**：进程环境变量 > `.env` 文件 > 代码默认值
> 生产环境（Docker / K8s）建议用环境变量，开发环境用 `.env` 文件。

## 使用方法

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 生成测试数据
```bash
python generate_test_data.py
```

### 3. 执行数据入库
```bash
python data_ingestion.py
```

### 4. 执行问答测试
```bash
python rag_query.py
```

## API 使用

```python
from rag_query import query_policy, initialize_rag

# 初始化（可选，自动初始化）
initialize_rag()

# 查询规章制度
answer = query_policy("请问我有多少天年假？")
print(answer)
```

## 项目结构
```
.
├── .env.example                # 配置模板（提交到 git）
├── .gitignore                  # 忽略 .env / chroma_db / data 等
├── config.py                   # 集中配置加载器（读 .env）
├── data/                       # 源文档目录
│   └── *.docx, *.md            # 待处理文档
├── chroma_db/                  # ChromaDB 向量数据库（被 .gitignore 忽略）
├── static/                     # 前端 SPA
│   └── index.html              # 单文件前端（HTML + CSS + JS）
├── data_ingestion.py           # 离线数据入库脚本
├── rag_service.py              # RAG 服务层（被 server.py 调用）
├── rag_query.py                # CLI 兼容 wrapper
├── server.py                   # FastAPI Web 后端
├── generate_test_data.py       # 测试数据生成
├── requirements.txt            # 依赖列表
└── README.md                   # 本文档
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 核心框架 | LlamaIndex |
| 向量存储 | ChromaDB (本地) |
| Embedding | BAAI/bge-large-zh-v1.5 |
| LLM | OpenAI (兼容格式) |
| 文档解析 | python-docx |
| 分块策略 | MarkdownNodeParser |

## 注意事项

1. **向量数据库**: 由于 PostgreSQL 不可用，系统使用 ChromaDB 作为本地向量存储，功能等效
2. **API Key**: 不设置 OPENAI_API_KEY 时，系统会自动降级为直接检索模式，返回相关文档片段
3. **中文支持**: BGE 模型专门针对中文文本优化，支持高质量中文语义检索
