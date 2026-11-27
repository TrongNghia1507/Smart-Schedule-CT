FROM node:24-bookworm-slim AS frontend

WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/index.html apps/web/tsconfig.json apps/web/vite.config.ts ./
COPY apps/web/src ./src
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh \
    CPSAT_WORKERS=2 \
    COMPRESSION_TIME_BUDGET=15 \
    SCHEDULE_WEB_DATA_DIR=/data \
    SCHEDULE_WEB_DIST=/app/web

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
COPY database ./database
RUN pip install --no-cache-dir . && mkdir -p /data && chmod 777 /data
COPY --from=frontend /build/dist /app/web

EXPOSE 7860
CMD ["sh", "-c", "exec python -m uvicorn backend.web.app:app --host 0.0.0.0 --port ${PORT:-7860}"]