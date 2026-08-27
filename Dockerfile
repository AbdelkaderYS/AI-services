FROM python:3.11-slim

WORKDIR /app

# System deps for matplotlib (headless Agg) and anydoc native deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persisted data (documents, memory) and the optional MCP sandbox live here.
VOLUME ["/app/data", "/app/mcp-files"]
EXPOSE 8080

ENV AI_AGENT_PORT=8080
CMD ["python", "webapp.py"]
