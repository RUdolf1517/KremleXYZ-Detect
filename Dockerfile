# Демо/песочница kremle-detect — образ для «попробовать одной командой».
#
#   docker run -p 8000:8000 ghcr.io/rudolf1517/kremle-detect:latest
#
# Для продакшена собирайте свой образ и монтируйте кеш вопросов
# (см. docs/install.md → «Решу ЕГЭ»), а ключ задавайте явно: KREMLE_SECRET.
FROM python:3.12-slim

ARG KREMLE_VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="kremle-detect" \
      org.opencontainers.image.description="Капча-фильтр по браузеру: Flask, Django, FastAPI, виджет без сборки" \
      org.opencontainers.image.source="https://github.com/RUdolf1517/KremleXYZ-Detect" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${KREMLE_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сначала зависимости — слой кешируется между сборками
COPY pyproject.toml README.md ./
COPY kremle_detect ./kremle_detect
RUN pip install --upgrade pip && pip install ".[demo]"

# Кеш вопросов «Решу ЕГЭ» живёт в томе, а не в образе
ENV KREMLE_CACHE_DIR=/data/cache
RUN useradd --create-home --uid 10001 kremle \
    && mkdir -p /data/cache \
    && chown -R kremle:kremle /data
VOLUME ["/data"]

USER kremle

EXPOSE 8000

# HEALTHCHECK без curl: в slim-образе его нет, а urllib есть всегда
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/kremle/health', timeout=2).status == 200 else 1)"

CMD ["kremle-detect", "serve", "--port", "8000"]
