# -*- coding: utf-8 -*-
"""Тесты метрик, /stats, /metrics и health-check."""

from kremle_detect import CaptchaEngine, MemoryStorage
from kremle_detect.metrics import Metrics, health_payload
from kremle_detect.storage import RedisStorage


class TestCounters:
    def test_all_counters(self):
        m = Metrics(MemoryStorage())
        m.count_request()
        m.count_request()
        m.count_detect('yandex_browser', 'challenge')
        m.count_detect('yandex_bot', 'block')
        m.count_allow()
        m.count_challenge()
        m.count_verify()
        m.count_pass()
        m.count_fail()
        m.count_blocked('rate_limited')

        snap = m.snapshot()
        assert snap['requests_total'] == 2
        assert snap['detected_total'] == 2
        assert snap['detected_by_reason']['yandex_browser'] == 1
        assert snap['detected_by_reason']['yandex_bot'] == 1
        assert snap['allowed_total'] == 1
        assert snap['actions']['challenge'] == 1
        assert snap['actions']['block'] == 1
        assert snap['challenges_issued'] == 1
        assert snap['verify_total'] == 1
        assert snap['pass_total'] == 1
        assert snap['fail_total'] == 1
        assert snap['blocked_by_reason']['rate_limited'] == 1
        assert snap['pass_rate'] == 1.0

    def test_pass_rate_none_without_verifies(self):
        assert Metrics(MemoryStorage()).snapshot()['pass_rate'] is None

    def test_disabled(self):
        m = Metrics(MemoryStorage(), enabled=False)
        m.count_request()
        m.count_pass()
        assert m.snapshot()['requests_total'] == 0

    def test_counters_survive_without_ttl(self):
        """Метрики не должны истекать, как челленджи."""
        storage = MemoryStorage()
        m = Metrics(storage)
        m.count_request()
        entry = storage._data['stats:requests']
        assert entry[1] is None

    def test_redis_uses_plain_incr(self):
        class FakeRedis:
            def __init__(self):
                self.data = {}
                self.expires = 0

            def incr(self, key):
                self.data[key] = int(self.data.get(key, 0)) + 1
                return self.data[key]

            def get(self, key):
                return str(self.data[key]).encode() if key in self.data else None

            def expire(self, key, ttl):
                self.expires += 1

            def eval(self, *args):
                raise AssertionError('для метрик TTL не нужен')

        client = FakeRedis()
        m = Metrics(RedisStorage(redis_client=client))
        m.count_request()
        m.count_request()
        assert m.snapshot()['requests_total'] == 2
        assert client.expires == 0


class TestPrometheus:
    def test_format(self):
        m = Metrics(MemoryStorage())
        m.count_request()
        m.count_detect('yandex_browser', 'monitor')
        m.count_pass()
        text = m.prometheus()

        assert '# TYPE kremle_requests_total counter' in text
        assert 'kremle_requests_total 1' in text
        assert 'kremle_detected_total{reason="yandex_browser"} 1' in text
        assert 'kremle_action_total{action="monitor"} 1' in text
        assert 'kremle_captcha_total{result="pass"} 1' in text
        assert text.endswith('\n')

    def test_all_reasons_present(self):
        text = Metrics(MemoryStorage()).prometheus()
        for reason in ('yandex_bot', 'yandex_browser', 'yandex_referrer', 'yandex_client_hints'):
            assert f'reason="{reason}"' in text


class TestHealth:
    def test_ok(self):
        payload = health_payload('2.7.0', MemoryStorage(), 'memory')
        assert payload['status'] == 'ok'
        assert payload['version'] == '2.7.0'
        assert payload['storage_ok'] is True
        assert payload['storage'] == 'memory'

    def test_broken_storage(self):
        class Broken(MemoryStorage):
            def set(self, key, value, ttl):
                raise RuntimeError('redis down')

        payload = health_payload('2.7.0', Broken(), 'redis')
        assert payload['status'] == 'degraded'
        assert payload['storage_ok'] is False

    def test_extra_fields(self):
        payload = health_payload('2.7.0', extra={'sample_rate': 0.3})
        assert payload['sample_rate'] == 0.3


class TestEngineMetrics:
    def test_challenge_and_verify_counted(self):
        engine = CaptchaEngine(
            categories=['math'], question_count=3, max_errors=1, secret='s',
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        engine.verify(ch.token, answers)

        snap = engine.metrics.snapshot()
        assert snap['challenges_issued'] == 1
        assert snap['verify_total'] == 1
        assert snap['pass_total'] == 1
        assert snap['pass_rate'] == 1.0

    def test_fail_counted(self):
        engine = CaptchaEngine(
            categories=['math'], question_count=3, max_errors=0, secret='s', rate_limit=0,
        )
        ch = engine.create_challenge()
        engine.verify(ch.token, {str(i): 99 for i in range(3)})
        assert engine.metrics.snapshot()['fail_total'] == 1

    def test_rate_limited_counted(self):
        engine = CaptchaEngine(
            categories=['math'], question_count=3, max_errors=0, secret='s',
            rate_limit=0, rate_window=60,
        )
        engine.rate_limit = 1
        for _ in range(2):
            ch = engine.create_challenge()
            engine.verify(ch.token, {}, ip='1.2.3.4')
        snap = engine.metrics.snapshot()
        assert snap['blocked_by_reason']['rate_limited'] == 1
