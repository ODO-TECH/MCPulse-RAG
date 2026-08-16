# RAG on Docker

`RAG on Docker` is a self-hosted RAG service bundle designed for NAS or Docker-based deployments.
It combines document indexing, MCP exposure, vector storage, scheduled health checks, and report delivery into one manageable stack.

- Current version: `0.2.1`
- Chinese documentation: [README_CN.md](README_CN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- License: [MIT](LICENSE)

This project is intended for users who want to:

- mount a local knowledge base directory into Docker
- build and maintain a searchable RAG index automatically
- expose the RAG capability through MCP over Streamable HTTP
- monitor service health on a schedule
- receive health reports when checks run

The current implementation uses:

- `Qdrant` as the vector database
- a local MCP service for search and management tools
- an OpenAI-compatible model API for embedding and rerank access
- a separate scheduled checker for health reports

This repository combines the whole setup into one Docker Compose stack:

- `knowledge-mcp`: the RAG service that builds indexes and exposes MCP over Streamable HTTP
- `ragcheck`: the scheduled health-check and report service
- `qdrant`: the vector database used by the RAG service

## What this project does

At startup, the `knowledge-mcp` service brings the MCP endpoint up immediately, starts an initial background scan, and stores vectors in Qdrant as indexing progresses.
After that, it continues watching for file changes and updates the index automatically with incremental scans.

The service also exposes MCP tools over Streamable HTTP, so an MCP client can search the knowledge base, inspect indexed content, and trigger reindex or incremental ingest operations.

Alongside it, `ragcheck` runs periodic health checks against both the MCP endpoint and Qdrant, writes HTML reports, and sends those results to the configured QQ bot endpoint.

## Main components

- `knowledge-mcp`: indexing, retrieval, MCP tool exposure, and file watching
- `qdrant`: vector storage and collection management
- `ragcheck`: scheduled health checks, report generation, and report delivery

## Model API note

This project is configured around generic OpenAI-compatible API fields:

- `MODEL_API_KEY`
- `MODEL_API_BASE`
- `EMBED_MODEL`
- `RERANK_MODEL`

Fill those values in `knowledge-mcp/.env`.
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

The root `KB_SOURCE_DIR` controls where your NAS or host knowledge files are mounted into the `knowledge-mcp` container.

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
KB_SOURCE_DIR=/absolute/path/to/your/rag-data
```

- `KB_SOURCE_DIR`: absolute path of your RAG knowledge directory on the NAS or host
- This directory will be mounted read-only into the container as `/data/mcpdata`

### `knowledge-mcp/.env`

This file is used by the RAG service for the embedding and rerank API.

```env
MODEL_API_KEY=your_real_api_key
MODEL_API_BASE=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-large
RERANK_MODEL=rerank-1
```

- `MODEL_API_KEY`: your real model API key
- `MODEL_API_BASE`: API base URL for your compatible provider
- `EMBED_MODEL`: embedding model name used for indexing and retrieval
- `RERANK_MODEL`: rerank model name used for result sorting

### `RAGcheck/.env`

This file is used by the health-check and QQ bot report service in the `ragcheck-qqbot` branch.

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

- `MCP_CHECK_URL`: MCP service address inside Docker Compose, usually keep `http://knowledge-mcp:6646`
- `QDRANT_URL`: Qdrant service address inside Docker Compose, usually keep `http://qdrant:6333`
- `REQUIRED_MCP_TOOLS`: expected MCP tools used by the checker
- `MCP_PROTOCOL_VERSION`: MCP protocol version used during Streamable HTTP checks
- `QQ_BOT_WEBHOOK`: your QQ bot report endpoint
- `QQ_BOT_TOKEN`: optional bearer token
- `QQ_BOT_TARGET`: optional target id
- `QQ_BOT_TARGET_TYPE`: delivery target type such as `private`
- `QQ_BOT_TIMEOUT`: request timeout in seconds
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

- MCP endpoint: `http://<your-host>:6646/mcp`
- Qdrant API: `http://<your-host>:6333`

## Delivery variants

- `main`: email delivery variant for public deployments
- `ragcheck-qqbot`: this branch, using QQ bot delivery by default

## Notes for publishing

- Do not upload `knowledge-mcp/.env`
- Do not upload `RAGcheck/.env`
- Do not upload the `storage/` directory
- Commit the two `.env.example` files instead
