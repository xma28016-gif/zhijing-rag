# 1.0 验收执行手册

该手册用于 Linux x86_64、16 核/64 GB 基准机的上线前验收。macOS 开发机只执行单元测试、类型检查和前端构建。

## 环境与基础链路

1. 复制 `.env.example` 并替换所有 `replace-with-*` 值。
2. 执行 `docker compose up --build -d`。
3. 执行 `./scripts/healthcheck.sh`，确认 API、PostgreSQL、Redis、Celery 和 MinIO 全部健康。
4. 在管理端配置真实模型密钥，并对 LLM、Embedding、Rerank 各执行一次连通性测试。
5. 逐一验证 Word、PDF、Markdown、Excel/CSV 和图片的导入、预览、构建、检索、对话和引用。

## RAG 质量基线

把 `docs/quality-dataset.example.jsonl` 复制为业务数据集，至少编写 30 条。可回答用例必须填写期望文档；不可回答用例用于验证拒答。API Key 只通过环境变量传入：

```bash
cd backend
RAG_EVAL_API_KEY='sk-...' .venv/bin/python scripts/evaluate_rag.py \
  --dataset ../docs/quality-dataset.jsonl \
  --assistant product-assistant \
  --output ../artifacts/rag-quality-report.json
```

报告记录数据集 SHA-256、来源 Recall@K、引用精度、答案关键词覆盖率、可回答性判断准确率、无答案拒答率和端到端耗时。每次调整分块、阈值或模型后都保留新报告与旧基线对比。

## 50 万分块与 20 路并发

确认目标知识库已有约 50 万个活动分块，并用真实业务查询替换示例文件后执行：

```bash
cd backend
.venv/bin/python scripts/benchmark_retrieval.py \
  --knowledge-base-id '<uuid>' \
  --queries ../docs/retrieval-queries.txt \
  --requests 200 \
  --concurrency 20 \
  --output ../artifacts/retrieval-benchmark.json
```

验收项是热缓存下 `internal_retrieval.p95_ms < 1500`。报告单独记录外部 Embedding、内部 PostgreSQL/pgvector 召回、外部 Rerank 和客户端总耗时；外部模型耗时不纳入 1.5 秒承诺。

## 故障与运维

- 断开 Redis，验证新建任务快速转为失败，页面不会无限显示“构建中”。
- 重启 Worker，验证任务重试和取消。
- 分别模拟 429、无效密钥、超时、损坏文件和流式中断。
- 执行 `scripts/backup.sh`，随后在隔离环境用 `scripts/restore.sh --confirm-restore` 恢复并重跑健康检查。
- 确认 90 天前详细日志被清理，日聚合指标仍可查询。
