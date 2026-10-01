# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

FROM base AS deps
COPY requirements.txt .
# psycopg[binary] bundles its own libpq and libraries, which security updates never reach. The
# image uses plain psycopg on Debian's libpq5 instead (installed below), patched with the OS.
RUN sed 's/^psycopg\[binary\]/psycopg/' requirements.txt > requirements.image.txt \
 && pip install --prefix=/install -r requirements.image.txt

FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/pavansky/fab-dispatch" \
      org.opencontainers.image.licenses="MIT"
# Security fixes published since the base image was built.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 app && mkdir -p /srv/data && chown app /srv/data
COPY --from=deps /install /usr/local
COPY app ./app
USER app
ENV FAB_ENV=production FAB_LOG_JSON=true
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/livez').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
