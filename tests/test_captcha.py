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
            max_errors=1,
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
            max_errors=1,
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
            max_errors=1,
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
            max_errors=1,
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


def _extra(n_questions, prefix='q', category=None):
    return [
        {'q': f'{prefix}{i}', 'opts': ['1', '2', '3', '4'], 'ans': 0,
         **({'category': category} if category else {})}
        for i in range(n_questions)
    ]


class TestQuestionPool:
    """Качество набора: без повторов и с ротацией."""

    def test_duplicates_are_removed(self):
        question = {'q': 'Один и тот же вопрос', 'opts': ['1', '2', '3', '4'], 'ans': 0}
        engine = CaptchaEngine(
            question_count=4, max_errors=0, secret='test', only_extra=True,
            extra_questions=[question, dict(question), dict(question), dict(question)],
        )
        ch = engine.create_challenge()
        assert len(ch.questions) == 1
        assert [q['q'] for q in ch.safe_questions] == ['Один и тот же вопрос']

    def test_normalised_duplicates_are_removed(self):
        """Повтор с другими пробелами/регистром — тот же вопрос."""
        engine = CaptchaEngine(
            question_count=3, max_errors=0, secret='test', only_extra=True,
            extra_questions=[
                {'q': 'Найдите  ответ', 'opts': ['1', '2', '3', '4'], 'ans': 0},
                {'q': 'найдите ОТВЕТ ', 'opts': ['1', '2', '3', '4'], 'ans': 0},
                {'q': 'Другой вопрос', 'opts': ['1', '2', '3', '4'], 'ans': 0},
            ],
        )
        assert len(engine.create_challenge().questions) == 2

    def test_rotation_does_not_repeat_questions(self):
        """Пока в пуле есть непоказанные вопросы, они идут первыми."""
        engine = CaptchaEngine(
            question_count=5, max_errors=0, secret='test', only_extra=True,
            extra_questions=_extra(30),
        )
        seen = []
        for _ in range(3):
            seen.extend(q['q'] for q in engine.create_challenge().questions)
        assert len(seen) == 15
        assert len(set(seen)) == 15, 'вопросы повторились, хотя в пуле было 30'

    def test_rotation_resets_when_pool_exhausted(self):
        engine = CaptchaEngine(
            question_count=5, max_errors=0, secret='test', only_extra=True,
            extra_questions=_extra(10),
        )
        for _ in range(2):   # первые два челленджа покрывают пул
            engine.create_challenge()
        # третий снова может повторять — важно, что он вообще создаётся
        assert len(engine.create_challenge().questions) == 5

    def test_small_pool_warns_once(self, caplog):
        import logging

        engine = CaptchaEngine(
            question_count=10, max_errors=2, secret='test', only_extra=True,
            extra_questions=_extra(10),
        )
        with caplog.at_level(logging.WARNING, logger='kremle'):
            engine.create_challenge()
            engine.create_challenge()
        warnings = [r for r in caplog.records if 'ротация невозможна' in r.getMessage()]
        assert len(warnings) == 1, 'предупреждение должно быть одно, а не на каждый челлендж'

    def test_rotation_survives_broken_storage(self):
        """Падение storage не должно ломать выдачу капчи."""
        engine = CaptchaEngine(
            question_count=3, max_errors=0, secret='test', only_extra=True,
            extra_questions=_extra(10),
        )

        real_get, real_set = engine.storage.get, engine.storage.set

        def broken_get(key, *args, **kwargs):
            if str(key).startswith('recentq:'):
                raise RuntimeError('storage down')
            return real_get(key, *args, **kwargs)

        def broken_set(key, *args, **kwargs):
            if str(key).startswith('recentq:'):
                raise RuntimeError('storage down')
            return real_set(key, *args, **kwargs)

        engine.storage.get = broken_get
        engine.storage.set = broken_set
        assert len(engine.create_challenge().questions) == 3


class TestVerifyPayload:
    """Сервер сам говорит порог и срок жизни — клиент не угадывает."""

    def test_max_errors_in_verify_result(self):
        engine = CaptchaEngine(
            question_count=5, max_errors=2, secret='test', only_extra=True,
            extra_questions=_extra(5),
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        for i in range(3):
            answers[str(i)] = (ch.questions[i]['ans'] + 1) % 4

        result = engine.verify(ch.token, answers, ip='1.2.3.4')
        assert result['passed'] is False
        assert result['errors'] == 3
        assert result['max_errors'] == 2

    def test_max_errors_capped_by_question_count(self):
        engine = CaptchaEngine(
            question_count=2, max_errors=5, secret='test', only_extra=True,
            extra_questions=_extra(2),
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        result = engine.verify(ch.token, answers)
        assert result['max_errors'] == 1   # нельзя ошибиться во всех вопросах

    def test_strict_mode_does_not_leak_threshold(self):
        """Строгий режим судит жёстче, но клиенту отдаём настроенный порог."""
        engine = CaptchaEngine(
            question_count=5, max_errors=2, secret='test', only_extra=True,
            extra_questions=_extra(5),
        )
        ch = engine.create_challenge()
        answers = {str(i): q['ans'] for i, q in enumerate(ch.questions)}
        answers['0'] = (ch.questions[0]['ans'] + 1) % 4

        result = engine.verify(ch.token, answers, ip='1.2.3.4',
                               fingerprint={'yaBrands': True})
        assert result['passed'] is False
        assert result['max_errors'] == 2

    def test_to_dict_has_ttl_and_threshold(self):
        engine = CaptchaEngine(
            question_count=3, max_errors=1, secret='test', only_extra=True,
            extra_questions=_extra(3),
        )
        ch = engine.create_challenge()
        data = ch.to_dict(max_errors=engine.max_errors)
        assert data['max_errors'] == 1
        assert 0 < data['expires_in'] <= 900
        assert 'token' in data and 'questions' in data

    def test_to_dict_without_max_errors_keeps_compatibility(self):
        engine = CaptchaEngine(
            question_count=1, max_errors=0, secret='test', only_extra=True,
            extra_questions=_extra(1),
        )
        data = engine.create_challenge().to_dict()
        assert 'max_errors' not in data
        assert 'expires_in' in data
