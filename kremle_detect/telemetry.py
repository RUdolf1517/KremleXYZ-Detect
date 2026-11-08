# -*- coding: utf-8 -*-
"""
Телеметрия: трейсы «челлендж → проверка» и JSON-логи. Всё опционально.

Библиотека, которая тянет OpenTelemetry в обязательные зависимости, — это
библиотека, которую не поставят. Поэтому: без `kremle-detect[otel]` здесь
пустые заглушки, а код вызовов не меняется.

    pip install "kremle-detect[otel]"
    export KREMLE_OTEL_ENDPOINT=http://localhost:4318   # OTLP/HTTP в Jaeger
    kremle-detect serve

Что попадает в трейс:

    kremle.challenge  reason, questions, max_errors
    kremle.verify     passed, errors, total, max_errors

IP и токен челленджа **не** пишем: первый — персональные данные, второй —
секрет, по которому можно пройти капчу. Для поиска нужного запроса хватает
`trace_id`, он же печатается в JSON-логе.

JSON-логи:

    export KREMLE_LOG_JSON=1

    {"ts": "2026-10-24T12:00:00Z", "level": "INFO", "logger": "kremle",
     "message": "Challenge created: token=… questions=3"}
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

__all__ = [
    'available', 'setup_tracing', 'span', 'JsonFormatter', 'setup_json_logs',
    'configure_from_env',
]

_TRACER_NAME = 'kremle_detect'


def available() -> bool:
    """Есть ли в окружении OpenTelemetry (extras ``[otel]``)."""
    try:
        import opentelemetry.trace  # noqa: F401
    except ImportError:
        return False
    return True


def setup_tracing(service_name: str = 'kremle-detect',
                  endpoint: Optional[str] = None,
                  sample_ratio: Optional[float] = None) -> bool:
    """
    Подключить OTLP-экспортёры, если установлены SDK и экспортёр.

    Возвращает ``True``, если трассировка включена. Отсутствие зависимостей —
    не ошибка: библиотека продолжает работать, просто без трейсов.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logging.getLogger('kremle').debug(
            'OpenTelemetry не установлен — трейсы отключены '
            '(pip install "kremle-detect[otel]")'
        )
        return False

    endpoint = endpoint or os.environ.get('KREMLE_OTEL_ENDPOINT')
    if not endpoint:
        return False

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:  # pragma: no cover - зависит от extras
        return False

    provider = TracerProvider(resource=Resource.create({'service.name': service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    if sample_ratio is not None:  # pragma: no cover - простой путь без сэмплера
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        provider.sampler = TraceIdRatioBased(sample_ratio)
    return True


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """
    Спан вокруг операции. Без OpenTelemetry — обычный no-op.

    Атрибуты со значением ``None`` не отправляются: пустой атрибут в Jaeger
    выглядит как данные, а данных нет.
    """
    if not available():
        yield None
        return
    from opentelemetry import trace

    tracer = trace.get_tracer(_TRACER_NAME)
    clean = {key: value for key, value in attributes.items() if value is not None}
    with tracer.start_as_current_span(name, attributes=clean) as current:
        yield current


class JsonFormatter(logging.Formatter):
    """Одна строка — один JSON. Для сборщиков логов, а не для чтения глазами."""

    def __init__(self, extra_fields: Optional[dict] = None):
        super().__init__()
        self.extra_fields = dict(extra_fields or {})

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        payload.update(self.extra_fields)
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        trace_id = _current_trace_id()
        if trace_id:
            payload['trace_id'] = trace_id
        return json.dumps(payload, ensure_ascii=False)


def _current_trace_id() -> Optional[str]:
    """trace_id текущего спана — чтобы лог и трейс склеивались по одному полю."""
    if not available():
        return None
    from opentelemetry import trace

    context = trace.get_current_span().get_span_context()
    if not context or not context.trace_id:
        return None
    return format(context.trace_id, '032x')


def setup_json_logs(logger: Optional[logging.Logger] = None,
                    level: Optional[int] = logging.INFO) -> logging.Logger:
    """
    Перевести лог ``kremle`` в JSON. Повторный вызов не плодит обработчики.

    ``propagate`` выключается: иначе та же запись уедет в корневой обработчик
    обычным текстом, и в потоке окажется смесь JSON и человеческого.
    Уровень по умолчанию — ``INFO``: без него библиотечные сообщения молча
    отфильтруются корневым логгером, и «JSON-логи включены» будет ложью.
    """
    logger = logger or logging.getLogger('kremle')
    for handler in logger.handlers:
        if getattr(handler, '_kremle_json', False):
            break
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler._kremle_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    for handler in logger.handlers:
        if getattr(handler, '_kremle_json', False):
            handler.setFormatter(JsonFormatter())
    if level is not None:
        logger.setLevel(level)
    logger.propagate = False
    return logger


def configure_from_env() -> dict:
    """
    Включить то, что просят переменными окружения. Возвращает отчёт для баннера.

    ``KREMLE_OTEL_ENDPOINT`` — OTLP-эндпоинт; ``KREMLE_LOG_JSON=1`` — JSON-логи.
    """
    report = {'tracing': False, 'json_logs': False}
    endpoint = os.environ.get('KREMLE_OTEL_ENDPOINT')
    if endpoint:
        report['tracing'] = setup_tracing(endpoint=endpoint)
    if os.environ.get('KREMLE_LOG_JSON', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        setup_json_logs()
        report['json_logs'] = True
    return report
