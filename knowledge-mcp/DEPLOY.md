# 知识库 MCP 服务部署指南

## 架构概览

```
┌──────────────────────────────────────────────┐
│            Docker Container                   │
│                                               │
│  ┌───────────┐  ┌──────────┐  ┌───────────┐ │
│  │ MCP Server│  │ Indexer  │  │  Watcher  │ │
│  │  :6646    │  │          │  │  (watchdog)│ │
│  └─────┬─────┘  └────┬─────┘  └─────┬─────┘ │
│        │              │              │        │
│        └──────────────┼──────────────┘        │
│                       │                       │
└───────────────────────┼───────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
     ┌────┴────┐  ┌─────┴────┐  ┌────┴────┐
     │ Qdrant  │  │SiliconFlow│  │ mcpdata │
     │  :6333  │  │   API    │  │ (挂载)  │
     └─────────┘  └──────────┘  └─────────┘
```

- **MCP Server**: 通过 SSE 协议暴露知识库检索工具，端口 6646
- **Qdrant**: 向量数据库，存储嵌入向量
- **SiliconFlow API**: 提供 Qwen3-Embedding-8B (4096维) 和 Qwen3-Reranker-8B
- **Watchdog**: 监听文件变更，自动触发增量索引
- **mcpdata**: 知识库文件目录，目录层级代表主题关系

## 前置条件

- Docker 和 Docker Compose
- SiliconFlow API Key（在 https://cloud.siliconflow.cn 获取）

## 部署步骤

### 1. 上传项目到 NAS

将整个 `docker/` 目录上传到 NAS，例如 `/vol1/1000/docker/knowledge-mcp/`

### 2. 准备知识库文件

将知识库文件放到 `mcpdata/` 目录下，按目录层级组织主题：

```
mcpdata/
├── category_01/       ← 自定义知识分类 01
│   ├── topic_a/
│   └── topic_b/
├── category_02/       ← 自定义知识分类 02
│   ├── topic_a/
│   ├── topic_b/
│   ├── topic_c/
│   └── topic_d/
├── category_03/       ← 自定义知识分类 03
│   └── topic_a/
└── category_04/       ← 自定义知识分类 04
```

### 3. 填写 API Key

编辑 `.env` 文件：

```
SILICONFLOW_API_KEY=你的API密钥
```

### 4. 修改路径（可选）

编辑 `docker-compose.yml`，修改 `mcpdata` 挂载路径为你的实际路径：

```yaml
volumes:
  - /absolute/path/to/your/rag-data:/data/mcpdata:ro   # 改为你的知识库目录
```

### 5. 启动服务

```bash
cd /vol1/1000/docker/knowledge-mcp
docker compose up -d --build
```

首次启动会自动进行全量索引。

### 6. 验证服务

```bash
# 查看日志
docker compose logs -f

# 检查 Qdrant
curl http://localhost:6333/collections

# 检查 MCP 服务
curl http://localhost:6646/sse
```

## MCP 客户端配置

### 连接地址

```
http://<NAS-IP>:6646/sse
```

### Cherry Studio / Claude Desktop 配置示例

```json
{
  "mcpServers": {
    "knowledge-base": {
      "url": "http://<your-nas-ip>:6646/sse"
    }
  }
}
```

## 可用 MCP 工具

| 工具 | 说明 |
|------|------|
| `search_knowledge_01` | 在 knowledge_01 知识库中搜索 |
| `search_knowledge_02` | 在 knowledge_02 知识库中搜索 |
| `search_knowledge_03` | 在 knowledge_03 知识库中搜索 |
| `search_knowledge_04` | 在 knowledge_04 知识库中搜索 |
| `search_all` | 跨所有知识库搜索 |
| `list_topics` | 列出主题目录层级 |
| `get_doc_info` | 查看文件详细信息 |
| `reindex` | 手动触发重新索引 |
| `kb_stats` | 查看知识库统计 |

### search_xxx 参数

- `query`（必填）: 搜索查询
- `dir_filter`（可选）: 目录路径前缀过滤，如 `category_01/topic_a` 只搜索该子目录

### search_all 参数

- `query`（必填）: 搜索查询
- `top_k_per_base`（可选）: 每个知识库返回的结果数，默认 3

## 日常维护

### 添加新文件

将文件拷贝到 `mcpdata/` 对应目录下，watchdog 会在 30 秒内自动检测并触发增量索引。

### 修改现有文件

直接编辑文件，watchdog 会自动检测变更并重新索引该文件。

### 手动全量重建

```bash
# 进入容器
docker exec -it knowledge-mcp bash

# 全量重建
python /app/indexer.py --force
```

或通过 MCP 工具调用 `reindex`。

### 添加新知识库

1. 在 `mcpdata/` 下创建新目录
2. 在 `app/config.yaml` 的 `knowledge.bases` 中添加配置
3. 重启服务：`docker compose restart knowledge-mcp`

### 查看日志

```bash
docker compose logs -f knowledge-mcp
```

## 支持的文件格式

| 格式 | 说明 |
|------|------|
| .md | Markdown 文件 |
| .txt | 纯文本文件 |
| .pdf | PDF 文档（需要 pymupdf） |
| .docx | Word 文档（需要 python-docx） |
| .doc | 旧版 Word 文档（有限支持） |
