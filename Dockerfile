# ohmypm server image: REST API + MCP + built Web UI. The Agent Runner runs on the host, not here.

FROM node:22-alpine AS web
ARG NPM_REGISTRY=
WORKDIR /web
RUN corepack enable && if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN COREPACK_NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}" pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim AS app
# Optional PyPI mirror (e.g. https://pypi.tuna.tsinghua.edu.cn); the lockfile is rewritten to use it.
ARG PYPI_MIRROR=
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir ${PYPI_MIRROR:+-i ${PYPI_MIRROR}/simple} uv==0.12.23
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY common/pyproject.toml common/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY runner/pyproject.toml runner/pyproject.toml
COPY cli/pyproject.toml cli/pyproject.toml
RUN if [ -n "$PYPI_MIRROR" ]; then \
      sed -i "s#https://pypi.org/simple#${PYPI_MIRROR}/simple#g; s#https://files.pythonhosted.org/packages/#${PYPI_MIRROR}/packages/#g" uv.lock; \
    fi && uv sync --frozen --no-dev --package ohmypm-server --no-install-workspace
COPY common/ common/
COPY backend/ backend/
RUN uv sync --frozen --no-dev --package ohmypm-server
COPY --from=web /web/dist /app/web

RUN useradd --system --uid 10001 --home /app ohmypm
USER ohmypm
ENV PATH=/app/.venv/bin:$PATH OHMYPM_WEB_DIST=/app/web OHMYPM_HOST=0.0.0.0 OHMYPM_PORT=8765
EXPOSE 8765
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2)"
CMD ["ohmypm-server", "serve", "--migrate"]
