# The server image: the API plus the built UI, served from one origin.
# Build from the repository root:  docker build -t cluster-navigator .

FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UI_DIR=/app/ui
WORKDIR /app

COPY backend/requirements-collector.txt backend/requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

COPY backend/navigator navigator
COPY --from=ui /ui/dist /app/ui

EXPOSE 8080
# Any non-root UID works, so OpenShift's restricted SCC can assign its own.
USER 1001
# --proxy-headers: behind a Route, the public scheme and host come from the
# forwarded headers. The OAuth redirect URI is built from them.
CMD ["uvicorn", "navigator.server.app:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
