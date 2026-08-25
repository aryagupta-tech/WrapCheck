FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir mcp-clickhouse==0.4.1 \
    && useradd --create-home --uid 10001 mcpuser
USER mcpuser

EXPOSE 8000
CMD ["python", "-m", "mcp_clickhouse.main"]
