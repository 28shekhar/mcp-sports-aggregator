# Hugging Face Spaces (Docker SDK) — this image runs the MCP server as a
# persistent HTTP service on port 7860, which is the port HF Spaces expects
# Docker Spaces to listen on.
FROM python:3.11-slim

WORKDIR /app

# System deps for requests/bs4 TLS + fast wheel installs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HF Spaces sets $PORT for you; we also default to 7860 in config.py.
ENV PORT=7860
EXPOSE 7860

# Runs as a non-root user (good practice, and required by some HF Space
# base images).
RUN useradd -m appuser && chown -R appuser /app
USER appuser

CMD ["python", "server.py"]
