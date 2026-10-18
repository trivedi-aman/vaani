# ---- build the frontend ---------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- runtime --------------------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/cache \
    ENVIRONMENT=production

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home vaani

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY identify ./identify
COPY core ./core
COPY agent ./agent
COPY voice ./voice
COPY server ./server
COPY data ./data
COPY --from=web /web/dist ./web/dist
RUN mkdir -p /app/var && chown vaani /app/var

USER vaani
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/healthz', timeout=2)"
CMD ["python", "-m", "server"]
