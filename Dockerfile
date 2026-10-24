# Демо/песочница kremle-detect. Для продакшена собирайте свой образ
# и монтируйте кеш вопросов (см. README → «Решу ЕГЭ»).
FROM python:3.12-slim

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
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/kremle/health', timeout=2).status == 200 else 1)"

CMD ["kremle-detect", "serve", "--port", "8000"]
