# RAG on Docker

`RAG on Docker` 是一套面向 NAS 和通用 Docker 环境的自托管 RAG 服务组合。它把知识库索引、MCP 暴露、向量库存储、定时巡检和报告推送整理成一套统一的 Docker Compose 方案，方便部署、迁移和公开发布。

- 当前版本：`0.2.1`
- 英文说明：[README.md](README.md)
- 更新记录：[CHANGELOG.md](CHANGELOG.md)
- 开源协议：[MIT](LICENSE)

## 项目简介

这个项目适合下面这些场景：

- 把本地或 NAS 上的知识库目录挂载进 Docker
- 自动完成文档切分、向量化和索引维护
- 通过 MCP Streamable HTTP 对外提供检索能力
- 定期检查服务状态
- 在巡检完成后接收报告

当前实现主要使用：

- `Qdrant` 作为向量数据库
- 本地 MCP 服务作为对外工具接口
- 兼容 OpenAI 风格的模型 API 作为 embedding 和 rerank 来源
- 独立的巡检服务负责健康检查和报告推送

## 服务组成

整个仓库整合了 3 个核心服务：

- `knowledge-mcp`
  负责知识库索引、MCP 工具暴露、文件监听和检索能力
- `qdrant`
  负责向量数据存储和 collection 管理
- `ragcheck`
  负责定时巡检、生成报告和发送报告

## 工作流程

启动后，`knowledge-mcp` 会先尽快启动 MCP 接口，同时在后台执行首次扫描，对挂载进容器的知识库目录进行切分、向量化并写入 `Qdrant`。

之后，服务会继续监听文件变化。新增、修改或删除文件时，会自动触发增量索引更新。

与此同时，`ragcheck` 会按设定周期访问 MCP 服务和 Qdrant，检查接口可用性、collection 状态和工具可调用性，并把结果保存成 HTML 报告，再通过当前分支默认的推送方式发送出去。

## 目录结构

```text
RAG on docker/
|- docker-compose.yml
|- .env.example
|- knowledge-mcp/
|  |- .env
|  |- .env.example
|  |- Dockerfile
|  `- app/
|- RAGcheck/
|  |- .env
|  |- .env.example
|  |- Dockerfile
|  `- app/
`- storage/
   |- qdrant/
   |- index_state/
   `- reports/
```

## 首次使用前要做什么

1. 填写 `knowledge-mcp/.env`
2. 填写 `RAGcheck/.env`
3. 如果你想覆盖知识库挂载路径，再根据 `.env.example` 创建顶层 `.env`

顶层 `KB_SOURCE_DIR` 用来指定宿主机或 NAS 上的知识库目录，它会以只读方式挂载到容器内的 `/data/mcpdata`。

## `.env` 应该怎么填写

这个仓库不会包含真实的 `.env` 文件。使用前，请根据示例文件自行创建：

```bash
cp .env.example .env
cp knowledge-mcp/.env.example knowledge-mcp/.env
cp RAGcheck/.env.example RAGcheck/.env
```

### 顶层 `.env`

顶层 `.env` 只负责指定知识库目录挂载路径。

```env
KB_SOURCE_DIR=/absolute/path/to/your/rag-data
```

- `KB_SOURCE_DIR`：你的知识库在 NAS 或宿主机上的绝对路径
- 这个目录会被以只读方式挂载到容器内的 `/data/mcpdata`

### `knowledge-mcp/.env`

这个文件负责配置 RAG 服务调用的模型接口。

```env
MODEL_API_KEY=your_real_api_key
MODEL_API_BASE=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-large
RERANK_MODEL=rerank-1
```

- `MODEL_API_KEY`：你的真实模型接口密钥
- `MODEL_API_BASE`：兼容接口的基础地址
- `EMBED_MODEL`：用于索引和召回的 embedding 模型名
- `RERANK_MODEL`：用于结果重排的 rerank 模型名

### `RAGcheck/.env`

这个文件负责当前 `ragcheck-qqbot` 分支里的 QQ bot 推送巡检服务。

```env
MCP_CHECK_URL=http://knowledge-mcp:6646
QDRANT_URL=http://qdrant:6333
REQUIRED_MCP_TOOLS=search_knowledge_01,search_knowledge_02,search_knowledge_03,search_knowledge_04,search_all,list_topics,get_doc_info,reindex,ingest_knowledge,kb_stats
MCP_PROTOCOL_VERSION=2025-03-26

NOTIFY_MODE=qqbot
QQ_BOT_WEBHOOK=https://your-qq-bot-endpoint.example.com/report
QQ_BOT_TOKEN=
QQ_BOT_TARGET=
QQ_BOT_TARGET_TYPE=private
QQ_BOT_TIMEOUT=20

CHECK_INTERVAL_DAYS=3
REPORT_RETENTION_DAYS=30
```

- `MCP_CHECK_URL`：Docker Compose 内部的 MCP 服务地址
- `QDRANT_URL`：Docker Compose 内部的 Qdrant 地址
- `REQUIRED_MCP_TOOLS`：巡检时要求存在的工具名
- `MCP_PROTOCOL_VERSION`：MCP Streamable HTTP 握手时使用的协议版本
- `QQ_BOT_WEBHOOK`：你的 QQ bot 报告接口
- `QQ_BOT_TOKEN`：可选的 bearer token
- `QQ_BOT_TARGET`：可选的目标 id
- `QQ_BOT_TARGET_TYPE`：目标类型，例如 `private`
- `QQ_BOT_TIMEOUT`：请求超时时间，单位秒

## 启动方式

```bash
docker compose up -d --build
```

## 服务入口

- MCP 接口：`http://<你的主机地址>:6646/mcp`
- Qdrant API：`http://<你的主机地址>:6333`

## 报告推送变体

- `main`：面向公开部署的邮箱推送版本
- `ragcheck-qqbot`：当前分支，默认使用 QQ bot 推送

## 发布前提醒

- 不要上传 `knowledge-mcp/.env`
- 不要上传 `RAGcheck/.env`
- 不要上传 `storage/`
- 保留 `.env.example` 作为公开示例配置
