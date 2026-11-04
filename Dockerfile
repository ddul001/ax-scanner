# --- UI build ---
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- API + built UI (one service) ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
# playwright is optional (JS-only homepages); it is skipped here to keep the image small
COPY requirements.txt .
RUN grep -v -i "^playwright\|^pytest" requirements.txt > req.prod.txt && pip install -r req.prod.txt
COPY app ./app
COPY --from=web /web/dist ./web/dist
# SQLite lives on a mounted volume (/data); set DATABASE_URL to a Postgres URL to replace it
ENV DATABASE_URL=sqlite:////data/ax.db
RUN mkdir -p /data
EXPOSE 8000
# behind the platform proxy: trust X-Forwarded-For so the per-visitor rate limit sees the visitor, not the proxy
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
