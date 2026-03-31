# -*- coding: utf-8 -*-
"""Тесты ядра капчи."""

import time

from kremle_detect import CaptchaEngine, MemoryStorage
from kremle_detect.captcha import Challenge


class TestChallenge:
    def test_create(self):
        questions = [
            {'q': 'Test?', 'opts': ['A', 'B', 'C'], 'ans': 0, 'category': 'test'},
        ]
        ch = Challenge(questions, 'secret')
        assert ch.token
        assert len(ch.safe_questions) == 1
        assert 'ans' not in ch.safe_questions[0]
        assert ch.safe_questions[0]['q'] == 'Test?'
        assert ch.safe_questions[0]['category'] == 'test'

    def test_to_dict(self):
        questions = [{'q': 'Q?', 'opts': ['A', 'B'], 'ans': 0}]
        ch = Challenge(questions, 'secret')
        d = ch.to_dict()
        assert 'questions' in d
        assert 'token' in d
        assert 'created_at' in d

    def test_serialize_deserialize(self):
        questions = [{'q': 'Q?', 'opts': ['A', 'B'], 'ans': 1}]
        ch = Challenge(questions, 'secret')
        data = ch._serialize()
        ch2 = Challenge._deserialize(data)
        assert ch2.token == ch.token
        assert ch2.questions == ch.questions
        assert ch2.created_at == ch.created_at


class TestCaptchaEngine:
    def test_create_challenge(self):
        engine = CaptchaEngine(
            categories=['math'],
            question_count=5,
            secret='test',
        )
        ch = engine.create_challenge()
        assert len(ch.questions) == 5
        assert ch.token

    def test_verify_correct(self):
        engine = CaptchaEngine(
            categories=['physics'],
            question_count=3,
            max_errors=0,
            secret='test',
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        result = engine.verify(ch.token, answers)
        assert result['passed'] is True
        assert result['errors'] == 0
        assert result['total'] == 3

    def test_verify_wrong(self):
        engine = CaptchaEngine(
            categories=['math'],
            question_count=3,
            max_errors=0,
            secret='test',
        )
        ch = engine.create_challenge()
        answers = {str(i): 99 for i in range(3)}
        result = engine.verify(ch.token, answers)
        assert result['passed'] is False
        assert result['errors'] == 3

    def test_verify_within_max_errors(self):
        engine = CaptchaEngine(
            categories=['russian'],
            question_count=5,
            max_errors=2,
            secret='test',
        )
        ch = engine.create_challenge()
        answers = {}
        for i, q in enumerate(ch.questions):
            if i < 2:
                answers[str(i)] = 99  # 2 ошибки
            else:
                answers[str(i)] = q['ans']
        result = engine.verify(ch.token, answers)
        assert result['passed'] is True
        assert result['errors'] == 2

    def test_verify_invalid_token(self):
        engine = CaptchaEngine(secret='test')
        result = engine.verify('nonexistent-token', {})
        assert result['passed'] is False
        assert result['error'] == 'invalid_token'

    def test_token_consumed_after_pass(self):
        engine = CaptchaEngine(
            categories=['math'],
            question_count=2,
            max_errors=2,
            secret='test',
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        engine.verify(ch.token, answers)
        # Повторная попытка — токен уже удалён
        result2 = engine.verify(ch.token, answers)
        assert result2['error'] == 'invalid_token'

    def test_extra_questions(self):
        my_q = [
            {'q': 'Custom?', 'opts': ['A', 'B'], 'ans': 0},
            {'q': 'Custom2?', 'opts': ['X', 'Y'], 'ans': 1},
        ]
        engine = CaptchaEngine(
            extra_questions=my_q,
            only_extra=True,
            question_count=2,
            secret='test',
        )
        ch = engine.create_challenge()
        assert len(ch.questions) == 2
        texts = {q['q'] for q in ch.questions}
        assert texts == {'Custom?', 'Custom2?'}

    def test_extra_mixed(self):
        my_q = [{'q': 'Mine?', 'opts': ['A', 'B'], 'ans': 0}]
        engine = CaptchaEngine(
            categories=['math'],
            extra_questions=my_q,
            question_count=50,
            secret='test',
        )
        ch = engine.create_challenge()
        texts = {q['q'] for q in ch.questions}
        assert 'Mine?' in texts
        assert len(ch.questions) > 1

    def test_validate_bad_questions(self):
        import pytest
        with pytest.raises(ValueError, match='opts'):
            CaptchaEngine(extra_questions=[{'q': 'Q', 'opts': ['A'], 'ans': 0}])

    def test_all_categories(self):
        engine = CaptchaEngine(question_count=60, secret='test')
        ch = engine.create_challenge()
        cats = {q.get('category') for q in ch.questions}
        assert 'math' in cats
        assert 'physics' in cats
        assert 'russian' in cats
        assert 'literature' in cats


class TestRateLimit:
    def test_rate_limit_blocks(self):
        engine = CaptchaEngine(
            categories=['math'],
            question_count=2,
            max_errors=0,
            secret='test',
            rate_limit=3,
            rate_window=60,
        )
        ip = '192.168.1.100'
        for _ in range(3):
            ch = engine.create_challenge()
            engine.verify(ch.token, {}, ip=ip)

        ch = engine.create_challenge()
        result = engine.verify(ch.token, {}, ip=ip)
        assert result['passed'] is False
        assert result['error'] == 'rate_limited'

    def test_rate_limit_different_ips(self):
        engine = CaptchaEngine(
            categories=['math'],
            question_count=2,
            max_errors=0,
            secret='test',
            rate_limit=1,
            rate_window=60,
        )
        # IP #1 — исчерпал лимит
        ch = engine.create_challenge()
        engine.verify(ch.token, {}, ip='10.0.0.1')

        # IP #2 — свежий лимит
        ch2 = engine.create_challenge()
        result = engine.verify(ch2.token, {str(i): q['ans'] for i, q in enumerate(ch2.questions)}, ip='10.0.0.2')
        # Не rate limited (хотя может не пройти по ответам — главное не rate_limited)
        assert result.get('error') != 'rate_limited'

    def test_rate_limit_disabled(self):
        engine = CaptchaEngine(
            categories=['math'],
            question_count=2,
            max_errors=10,
            secret='test',
            rate_limit=0,
        )
        ip = '1.2.3.4'
        for _ in range(20):
            ch = engine.create_challenge()
            result = engine.verify(ch.token, {}, ip=ip)
            assert result.get('error') != 'rate_limited'


class TestCallbacks:
    def test_on_pass_called(self):
        calls = []

        def on_pass(ip, errors, total):
            calls.append(('pass', ip, errors, total))

        engine = CaptchaEngine(
            categories=['math'],
            question_count=2,
            max_errors=2,
            secret='test',
            on_pass=on_pass,
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        engine.verify(ch.token, answers, ip='1.2.3.4')
        assert len(calls) == 1
        assert calls[0][0] == 'pass'
        assert calls[0][1] == '1.2.3.4'

    def test_on_fail_called(self):
        calls = []

        def on_fail(ip, errors, total):
            calls.append(('fail', ip, errors, total))

        engine = CaptchaEngine(
            categories=['math'],
            question_count=2,
            max_errors=0,
            secret='test',
            on_fail=on_fail,
        )
        ch = engine.create_challenge()
        engine.verify(ch.token, {str(i): 99 for i in range(2)}, ip='5.6.7.8')
        assert len(calls) == 1
        assert calls[0][0] == 'fail'

    def test_on_detect_called(self):
        from kremle_detect import detect
        calls = []

        def on_detect(result, ip):
            calls.append((result.reason, ip))

        engine = CaptchaEngine(secret='test', on_detect=on_detect)
        r = detect({'User-Agent': 'YaBrowser/24'})
        engine.notify_detect(r, ip='9.8.7.6')
        assert len(calls) == 1
        assert calls[0] == ('yandex_browser', '9.8.7.6')


class TestStorage:
    def test_memory_storage_set_get(self):
        s = MemoryStorage()
        s.set('k1', {'a': 1}, ttl=60)
        assert s.get('k1') == {'a': 1}

    def test_memory_storage_ttl(self):
        s = MemoryStorage()
        s.set('k2', {'a': 1}, ttl=0)
        # TTL=0 → уже истёк
        import time
        time.sleep(0.01)
        assert s.get('k2') is None

    def test_memory_storage_delete(self):
        s = MemoryStorage()
        s.set('k3', {'a': 1}, ttl=60)
        s.delete('k3')
        assert s.get('k3') is None

    def test_memory_storage_increment(self):
        s = MemoryStorage()
        assert s.increment('counter', ttl=60) == 1
        assert s.increment('counter', ttl=60) == 2
        assert s.increment('counter', ttl=60) == 3

    def test_memory_storage_get_missing(self):
        s = MemoryStorage()
        assert s.get('nonexistent') is None
