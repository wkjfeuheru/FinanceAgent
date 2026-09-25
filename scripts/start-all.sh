#!/usr/bin/env bash
# FinanceAgent Linux 预发入口：Docker Compose（Postgres/pgvector、Redis、migrate、API、Celery、Nginx）。
# 开发机 Windows 路径见 scripts/start-all.ps1。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "缺少 .env。请先复制并填写必填项：" >&2
  echo "  cp .env.example .env" >&2
  echo "  # DEEPSEEK_API_KEY / POSTGRES_PASSWORD / INTENT_MODEL_API_KEY / APP_ENV=production" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 docker。" >&2
  exit 1
fi

echo "==> docker compose up -d --wait"
docker compose up -d --wait

echo
echo "预发已启动： http://localhost"
echo "健康检查：   curl -fsS http://localhost/api/health"
echo "管理员引导： docker compose exec api python tools/bootstrap_admin.py --username admin"
echo "FAQ 索引：   docker compose exec api python -m finance_agent.faq index --root docs/faq"
