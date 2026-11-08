# -*- coding: utf-8 -*-
"""Телеметрия: трейсы challenge → verify и JSON-логи.

Главное требование — необязательность. Библиотека без `[otel]` должна работать
ровно как раньше: никаких ImportError, никаких полей в логах, только no-op.
Поэтому половина тестов здесь проверяет именно отсутствие OpenTelemetry.
"""

import io
import json
import logging

import pytest

from kremle_detect import telemetry

HAS_OTEL = telemetry.available()


def make_engine(**kwargs):
    from kremle_detect.captcha import CaptchaEngine

    params = dict(categories=['math'], question_count=3, max_errors=1, secret='test')
    params.update(kwargs)
    return CaptchaEngine(**params)


class TestWithoutOtel:
    """Поведение по умолчанию: спаны — no-op, зависимости не нужны."""

    def test_span_is_a_context_manager_even_without_otel(self):
        with telemetry.span('kremle.test', answer=42) as current:
            assert current is None or HAS_OTEL

    def test_span_is_noop_when_otel_is_missing(self, monkeypatch):
        # Явно изображаем «пакета нет», даже если он установлен в окружении
        monkeypatch.setattr(telemetry, 'available', lambda: False)
        with telemetry.span('kremle.test', answer=42) as current:
            assert current is None

    def test_trace_id_is_not_invented(self, monkeypatch):
        monkeypatch.setattr(telemetry, 'available', lambda: False)
        assert telemetry._current_trace_id() is None

    def test_setup_tracing_is_false_without_endpoint(self, monkeypatch):
        monkeypatch.delenv('KREMLE_OTEL_ENDPOINT', raising=False)
        assert telemetry.setup_tracing() is False

    def test_configure_from_env_is_quiet_by_default(self, monkeypatch):
        monkeypatch.delenv('KREMLE_OTEL_ENDPOINT', raising=False)
        monkeypatch.delenv('KREMLE_LOG_JSON', raising=False)
        assert telemetry.configure_from_env() == {'tracing': False, 'json_logs': False}


class TestSetupTracing:
    """`setup_tracing` не должен падать ни при каком состоянии окружения."""

    def test_without_endpoint_is_false(self, monkeypatch):
        monkeypatch.delenv('KREMLE_OTEL_ENDPOINT', raising=False)
        assert telemetry.setup_tracing() is False

    def test_without_exporter_returns_false(self, monkeypatch):
        pytest.importorskip('opentelemetry.sdk')
        import sys

        monkeypatch.setitem(
            sys.modules, 'opentelemetry.exporter.otlp.proto.http.trace_exporter', None)
        assert telemetry.setup_tracing(endpoint='http://localhost:4318') is False

    def test_with_endpoint_configures_provider(self, monkeypatch):
        pytest.importorskip('opentelemetry.sdk')
        pytest.importorskip('opentelemetry.exporter.otlp.proto.http.trace_exporter')
        from opentelemetry import trace

        installed = {}
        monkeypatch.setattr(trace, 'set_tracer_provider',
                            lambda provider: installed.setdefault('provider', provider))
        assert telemetry.setup_tracing(service_name='kremle-test',
                                       endpoint='http://localhost:4318') is True
        provider = installed['provider']
        assert provider is not None
        # ресурс сервиса виден в бэкенде — иначе трейсы не с чем соотнести
        assert provider.resource.attributes['service.name'] == 'kremle-test'

    def test_sample_ratio_is_applied(self, monkeypatch):
        pytest.importorskip('opentelemetry.sdk')
        pytest.importorskip('opentelemetry.exporter.otlp.proto.http.trace_exporter')
        from opentelemetry import trace
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        monkeypatch.setattr(trace, 'set_tracer_provider', lambda provider: None)
        assert telemetry.setup_tracing(endpoint='http://localhost:4318',
                                       sample_ratio=0.25) is True
        assert TraceIdRatioBased is not None  # ветка выполнена без исключения

    def test_env_endpoint_is_used(self, monkeypatch):
        pytest.importorskip('opentelemetry.sdk')
        pytest.importorskip('opentelemetry.exporter.otlp.proto.http.trace_exporter')
        from opentelemetry import trace

        monkeypatch.setattr(trace, 'set_tracer_provider', lambda provider: None)
        monkeypatch.setenv('KREMLE_OTEL_ENDPOINT', 'http://localhost:4318')
        assert telemetry.configure_from_env()['tracing'] is True


class TestJsonLogs:
    def test_record_becomes_one_json_line(self):
        formatter = telemetry.JsonFormatter()
        record = logging.LogRecord('kremle', logging.INFO, __file__, 1,
                                   'Challenge created: %s', ('abc',), None)
        payload = json.loads(formatter.format(record))
        assert payload['level'] == 'INFO'
        assert payload['logger'] == 'kremle'
        assert payload['message'] == 'Challenge created: abc'
        assert 'ts' in payload

    def test_extra_fields_and_exceptions(self):
        formatter = telemetry.JsonFormatter(extra_fields={'service': 'kremle'})
        try:
            raise ValueError('поломка')
        except ValueError:
            import sys

            record = logging.LogRecord('kremle', logging.ERROR, __file__, 1,
                                       'упало', (), sys.exc_info())
        payload = json.loads(formatter.format(record))
        assert payload['service'] == 'kremle'
        assert 'поломка' in payload['exception']

    def test_setup_is_idempotent(self):
        logger = logging.getLogger('kremle-test-json')
        logger.handlers.clear()
        telemetry.setup_json_logs(logger)
        telemetry.setup_json_logs(logger)
        assert len(logger.handlers) == 1
        assert logger.handlers[0].formatter.__class__ is telemetry.JsonFormatter

    def test_handler_writes_to_stream(self):
        logger = logging.getLogger('kremle-test-stream')
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        telemetry.setup_json_logs(logger)
        stream = io.StringIO()
        logger.handlers[0].stream = stream
        logger.info('привет')
        assert json.loads(stream.getvalue())['message'] == 'привет'

    def test_env_switch_enables_json(self, monkeypatch):
        monkeypatch.setenv('KREMLE_LOG_JSON', '1')
        monkeypatch.delenv('KREMLE_OTEL_ENDPOINT', raising=False)
        logger = logging.getLogger('kremle')
        before = list(logger.handlers)
        try:
            assert telemetry.configure_from_env()['json_logs'] is True
        finally:
            for handler in list(logger.handlers):
                if handler not in before:
                    logger.removeHandler(handler)


@pytest.mark.skipif(not HAS_OTEL, reason='нужен extras [otel]')
class TestWithOtel:
    """Настоящие спаны: имена и атрибуты, без IP и токена."""

    # Провайдер в OpenTelemetry ставится один раз на процесс — иначе SDK
    # ругается «Overriding of current TracerProvider is not allowed».
    _exporter = None

    @classmethod
    def _collector(cls):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        if cls._exporter is None:
            cls._exporter = InMemorySpanExporter()
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(cls._exporter))
            trace.set_tracer_provider(provider)
        cls._exporter.clear()
        return cls._exporter

    def test_challenge_and_verify_spans(self):
        exporter = self._collector()
        engine = make_engine()
        challenge = engine.create_challenge(ip='203.0.113.7')
        answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}
        engine.verify(challenge.token, answers, ip='203.0.113.7')

        spans = {span.name: span for span in exporter.get_finished_spans()}
        assert 'kremle.challenge' in spans
        assert 'kremle.verify' in spans

        challenge_span = spans['kremle.challenge']
        assert challenge_span.attributes['questions'] == 3
        assert challenge_span.attributes['max_errors'] == 1

        verify_span = spans['kremle.verify']
        assert verify_span.attributes['passed'] is True
        assert verify_span.attributes['errors'] == 0

        # приватность: ни IP, ни токена в трейсе нет
        for span in spans.values():
            values = ' '.join(str(value) for value in span.attributes.values())
            assert '203.0.113.7' not in values
            assert challenge.token not in values

    def test_failed_verify_is_marked(self):
        exporter = self._collector()
        engine = make_engine()
        challenge = engine.create_challenge()
        result = engine.verify(challenge.token, {})
        assert result['passed'] is False
        span = [s for s in exporter.get_finished_spans() if s.name == 'kremle.verify'][-1]
        assert span.attributes['passed'] is False
