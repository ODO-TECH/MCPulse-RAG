# RAG on Docker

`RAG on Docker` is a self-hosted RAG service bundle designed for NAS or Docker-based deployments.
It combines document indexing, MCP exposure, vector storage, scheduled health checks, and email reporting into one manageable stack.

- Current version: `0.1.0`
- Chinese documentation: [README_CN.md](README_CN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- License: [MIT](LICENSE)

This project is intended for users who want to:

- mount a local knowledge base directory into Docker
- build and maintain a searchable RAG index automatically
- expose the RAG capability through MCP over SSE
- monitor service health on a schedule
- receive email reports when checks run

The current implementation uses:

- `Qdrant` as the vector database
- a local MCP service for search and management tools
- SiliconFlow API endpoints for embedding and rerank model access
- a separate scheduled checker for health reports

This repository combines the whole setup into one Docker Compose stack:

- `knowledge-mcp`: the RAG service that builds indexes and exposes MCP over SSE
- `ragcheck`: the scheduled health-check and email report service
- `qdrant`: the vector database used by the RAG service

## What this project does

At startup, the `knowledge-mcp` service scans the mounted knowledge directory, splits supported documents into chunks, generates embeddings through the configured model API, and stores vectors in Qdrant.
After that, it continues watching for file changes and updates the index automatically.

The service also exposes MCP tools over SSE, so an MCP client can search the knowledge base, inspect indexed content, and trigger reindex operations.

Alongside it, `ragcheck` runs periodic health checks against both the MCP endpoint and Qdrant, writes HTML reports, and sends those results to the configured mailbox.

## Main components

- `knowledge-mcp`: indexing, retrieval, MCP tool exposure, and file watching
- `qdrant`: vector storage and collection management
- `ragcheck`: scheduled health checks, report generation, and email delivery

## Model API note

This project is configured around the SiliconFlow-compatible API fields already used by the service:

- `SILICONFLOW_API_KEY`
- `SILICONFLOW_API_BASE`
- `EMBED_MODEL`
- `RERANK_MODEL`

If you continue using the same setup, fill those values in `knowledge-mcp/.env`.
If you later adapt the code for another compatible provider, the deployment structure here can still stay the same.

## Directory layout

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

## Before first start

1. Edit `knowledge-mcp/.env`
2. Edit `RAGcheck/.env`
3. Create a root `.env` from `.env.example` if you want to override `KB_SOURCE_DIR`

The root `KB_SOURCE_DIR` controls where your NAS knowledge files are mounted into the `knowledge-mcp` container.

## How to fill `.env`

This repository does not include real `.env` files. Before starting, create them from the example files:

```bash
cp .env.example .env
cp knowledge-mcp/.env.example knowledge-mcp/.env
cp RAGcheck/.env.example RAGcheck/.env
```

If your environment does not use `cp`, create the three `.env` files manually and copy the contents from the matching `.env.example` files.

### Root `.env`

The root `.env` is only used to define where your knowledge files live on the host machine.

```env
KB_SOURCE_DIR=/vol3/1000/RAGdata
```

- `KB_SOURCE_DIR`: absolute path of your RAG knowledge directory on the NAS or host
- This directory will be mounted read-only into the container as `/data/mcpdata`

### `knowledge-mcp/.env`

This file is used by the RAG service for the embedding and rerank API.

```env
SILICONFLOW_API_KEY=your_real_api_key
SILICONFLOW_API_BASE=https://api.siliconflow.cn/v1
EMBED_MODEL=Qwen/Qwen3-Embedding-8B
RERANK_MODEL=Qwen/Qwen3-Reranker-8B
```

- `SILICONFLOW_API_KEY`: your real SiliconFlow API key
- `SILICONFLOW_API_BASE`: API base URL, normally keep `https://api.siliconflow.cn/v1`
- `EMBED_MODEL`: embedding model name used for indexing and retrieval
- `RERANK_MODEL`: rerank model name used for result sorting

### `RAGcheck/.env`

This file is used by the health-check and email report service.

```env
MCP_CHECK_URL=http://knowledge-mcp:6646
QDRANT_URL=http://qdrant:6333

SMTP_HOST=smtp.126.com
SMTP_PORT=465
SMTP_USER=your_mail_account
SMTP_PASS=your_smtp_password_or_auth_code
MAIL_FROM=your_mail_account@126.com
MAIL_TO=receiver@example.com

CHECK_INTERVAL_DAYS=3
REPORT_RETENTION_DAYS=30
```

- `MCP_CHECK_URL`: MCP service address inside Docker Compose, usually keep `http://knowledge-mcp:6646`
- `QDRANT_URL`: Qdrant service address inside Docker Compose, usually keep `http://qdrant:6333`
- `SMTP_HOST`: SMTP server address of your mailbox provider
- `SMTP_PORT`: SMTP port, commonly `465` for SSL or `587` for STARTTLS
- `SMTP_USER`: sender mailbox login account
- `SMTP_PASS`: mailbox password or SMTP authorization code, depending on your provider
- `MAIL_FROM`: sender email address
- `MAIL_TO`: receiver email address for the health reports
- `CHECK_INTERVAL_DAYS`: how many days between automatic checks
- `REPORT_RETENTION_DAYS`: how many days local HTML reports are kept

### Publishing reminder

Before uploading to GitHub or Gitee:

- keep `knowledge-mcp/.env` deleted
- keep `RAGcheck/.env` deleted
- only upload `.env.example` files
- do not upload `storage/`

## Start

```bash
docker compose up -d --build
```

## Service endpoints

- MCP SSE: `http://<your-host>:6646/sse`
- Qdrant API: `http://<your-host>:6333`

## Notes for publishing

- Do not upload `knowledge-mcp/.env`
- Do not upload `RAGcheck/.env`
- Do not upload the `storage/` directory
- Commit the two `.env.example` files instead
