FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FINANCE_SQL_DIR=/app/sql \
    FAQ_EMBEDDING_DEVICE=cpu \
    FAQ_EMBEDDING_MODEL_CACHE_DIR=/app/.cache/models \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock pyproject.toml README.md ./
COPY finance_agent ./finance_agent

# FAQ embedding 使用 CPU torch，避免把 CUDA 变体打进默认镜像。
# torch 不写入 requirements.lock，以免 pip 从 PyPI 覆盖成 CUDA 轮子。
# INSTALL_PROVIDERS 默认打开：行情路径需要 akshare / baostock extras。
ARG INSTALL_PROVIDERS=1
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.14.0" \
    && pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps . \
    && if [ "$INSTALL_PROVIDERS" = "1" ]; then \
         pip install --no-cache-dir "akshare>=1.10.0" "baostock>=0.8.8"; \
       fi

COPY sql ./sql
COPY tools ./tools
COPY docs/faq ./docs/faq

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "finance_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
