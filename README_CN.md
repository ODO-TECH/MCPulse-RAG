# RAG on Docker

`RAG on Docker` 是一套面向 NAS 或普通 Docker 环境的自托管 RAG 服务组合。
它把知识库索引、MCP 暴露、向量库存储、定时健康检查和邮件报告整理成了一套统一的 Docker Compose 方案，方便部署、迁移和公开托管。

- 当前版本：`0.1.0`
- 英文说明：[README.md](README.md)
- 更新记录：[CHANGELOG.md](CHANGELOG.md)
- 开源许可：[MIT](LICENSE)

## 项目简介

这个项目适合下面这类使用场景：

- 把本地或 NAS 上的知识库目录挂载进 Docker
- 自动完成文档切分、向量化和索引维护
- 通过 MCP SSE 对外提供检索能力
- 定期检查服务是否正常
- 将巡检结果保存为 HTML 报告并发送到邮箱

当前实现主要使用：

- `Qdrant` 作为向量数据库
- 本地 MCP 服务作为对外工具接口
- 硅基流动兼容接口作为 embedding 和 rerank 模型来源
- 独立的巡检服务负责健康检查和邮件发送

## 服务组成

整个仓库整合了 3 个容器服务：

- `knowledge-mcp`
  负责知识库索引、MCP 工具暴露、文件监听和检索能力
- `qdrant`
  负责向量数据存储和 collection 管理
- `ragcheck`
  负责定时巡检、生成报告、发送邮件

## 工作流程

启动后，`knowledge-mcp` 会扫描挂载进容器的知识库目录，对支持的文档进行切分，调用配置好的模型接口生成向量，并把结果写入 `Qdrant`。

之后，服务会继续监听文件变化。新增、修改或删除文件时，会自动触发索引更新。

与此同时，`ragcheck` 会按设定周期访问 MCP 服务和 Qdrant，检查接口可用性与 collection 状态，并把结果保存为 HTML 报告，同时发送到指定邮箱。

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

## 初次使用前要做什么

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

如果你的环境不方便使用 `cp`，手动新建 3 个 `.env` 文件并复制对应 `.env.example` 的内容即可。

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
SILICONFLOW_API_KEY=your_real_api_key
SILICONFLOW_API_BASE=https://api.siliconflow.cn/v1
EMBED_MODEL=Qwen/Qwen3-Embedding-8B
RERANK_MODEL=Qwen/Qwen3-Reranker-8B
```

- `SILICONFLOW_API_KEY`：你的真实 API Key
- `SILICONFLOW_API_BASE`：接口地址，默认保持 `https://api.siliconflow.cn/v1`
- `EMBED_MODEL`：用于索引和召回的 embedding 模型名
- `RERANK_MODEL`：用于结果重排的 rerank 模型名

### `RAGcheck/.env`

这个文件负责巡检服务和邮件发送配置。

```env
MCP_CHECK_URL=http://knowledge-mcp:6646
QDRANT_URL=http://qdrant:6333

SMTP_HOST=your_smtp_host
SMTP_PORT=your_smtp_port
SMTP_USER=your_smtp_username
SMTP_PASS=your_smtp_password_or_auth_code
MAIL_FROM=your_sender_email
MAIL_TO=your_receiver_email

CHECK_INTERVAL_DAYS=3
REPORT_RETENTION_DAYS=30
```

- `MCP_CHECK_URL`：Docker Compose 内部的 MCP 服务地址，通常保持 `http://knowledge-mcp:6646`
- `QDRANT_URL`：Docker Compose 内部的 Qdrant 地址，通常保持 `http://qdrant:6333`
- `SMTP_HOST`：以你的邮箱服务商官方文档为准填写 SMTP 服务器地址
- `SMTP_PORT`：以你的邮箱服务商官方文档为准填写端口；常见有 `465` 和 `587`，但不要在未确认前直接套用
- `SMTP_USER`：SMTP 登录账号。有些服务商要求填写完整邮箱地址，有些要求填写独立账号名
- `SMTP_PASS`：邮箱密码或 SMTP 授权码，取决于你的邮箱服务商
- `MAIL_FROM`：发件人邮箱
- `MAIL_TO`：用于接收巡检报告的邮箱
- `CHECK_INTERVAL_DAYS`：自动巡检间隔天数
- `REPORT_RETENTION_DAYS`：本地 HTML 报告保留天数

重要说明：

- 不要直接照搬别人的 SMTP 主机名、端口或用户名格式
- 必须以你自己的邮箱服务商文档为准填写 SMTP 地址、端口、加密方式和认证格式
- 如果你的服务商要求使用客户端专用密码或 SMTP 授权码，请不要直接使用网页登录密码

## 启动方式

```bash
docker compose up -d --build
```

## 服务入口

- MCP SSE：`http://<你的主机地址>:6646/sse`
- Qdrant API：`http://<你的主机地址>:6333`

## 发布到代码托管平台前的提醒

- 不要上传 `knowledge-mcp/.env`
- 不要上传 `RAGcheck/.env`
- 不要上传 `storage/`
- 保留 `.env.example` 作为公开示例配置
