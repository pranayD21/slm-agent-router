FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir -e ".[web]"

ENV HOST=0.0.0.0
ENV PORT=8000
ENV SLM_ROUTER_MAX_ACTIVE_RUNS=3
ENV SLM_ROUTER_RUNS_PER_HOUR=20
ENV SLM_ROUTER_MAX_STEPS=15

EXPOSE 8000

CMD ["sh", "-c", "slm-router serve --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
