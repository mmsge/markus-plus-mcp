FROM python:3.12-slim

RUN pip install uv
WORKDIR /app
COPY . .
RUN uv sync
RUN uv run playwright install chromium --with-deps

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "src.markus_plus_mcp.server:app", \
     "--host", "0.0.0.0", "--port", "8000"]
