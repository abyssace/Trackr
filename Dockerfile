FROM python:3.11-slim

WORKDIR /app

# Instalar uv
RUN pip install --no-cache-dir uv

# Copiar el proyecto
COPY . .

# Instalar dependencias de producción (sin grupos de dev)
RUN uv sync --no-dev

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV DATABASE_URL=sqlite:///data/trackr.db
ENV BACKUP_DIR=/data/backups

EXPOSE 8000

# Health check sin autenticación
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD uv run python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1

# Un solo worker para evitar concurrencia sobre SQLite
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
