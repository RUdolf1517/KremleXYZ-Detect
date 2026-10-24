# -*- coding: utf-8 -*-
"""Тесты защиты ядра: валидация настроек, одноразовые токены, rate limit."""

import pytest

from kremle_detect import CaptchaEngine, MemoryStorage


def make_engine(**kwargs):
    params = dict(
        categories=['math'],
        question_count=5,
        max_errors=1,
        secret='test',
        storage=MemoryStorage(),
    )
    params.update(kwargs)
    return CaptchaEngine(**params)


def right_answers(challenge):
    return {str(i): q['ans'] for i, q in enumerate(challenge.questions)}


class TestConfigValidation:
    def test_max_errors_equal_question_count_rejected(self):
        with pytest.raises(ValueError, match='max_errors'):
            make_engine(question_count=3, max_errors=3)

    def test_max_errors_greater_than_question_count_rejected(self):
        with pytest.raises(ValueError, match='max_errors'):
            make_engine(question_count=2, max_errors=10)

    def test_question_count_must_be_positive(self):
        with pytest.raises(ValueError, match='question_count'):
            make_engine(question_count=0, max_errors=0)

    def test_question_count_type_checked(self):
        with pytest.raises(ValueError, match='question_count'):
            make_engine(question_count='5', max_errors=1)

    def test_bool_is_not_int_here(self):
        with pytest.raises(ValueError, match='question_count'):
            make_engine(question_count=True, max_errors=0)

    def test_negative_max_errors(self):
        with pytest.raises(ValueError, match='max_errors'):
            make_engine(max_errors=-1)

    def test_negative_rate_limit(self):
        with pytest.raises(ValueError, match='rate_limit'):
            make_engine(rate_limit=-1)

    def test_zero_rate_window(self):
        with pytest.raises(ValueError, match='rate_window'):
            make_engine(rate_window=0)

    def test_pool_too_small_for_max_errors(self):
        """15 вопросов в math + question_count=20 → 15 вопросов, max_errors=15 — дыра."""
        engine = CaptchaEngine(
            categories=['math'],
            question_count=20,
            max_errors=14,
            secret='test',
            storage=MemoryStorage(),
        )
        # 15 реальных вопросов > 14 ошибок — ок, но 14 ошибок из 15 это почти
        # свободный проход; проверим что совсем дырявый конфиг падает.
        engine2 = CaptchaEngine(
            categories=['math'],
            question_count=20,
            max_errors=16,
            secret='test',
            storage=MemoryStorage(),
        )
        assert engine.question_count == 20
        with pytest.raises(ValueError, match='max_errors'):
            engine2.create_challenge()

    def test_small_pool_with_only_extra(self):
        engine = CaptchaEngine(
            extra_questions=[
                {'q': 'A?', 'opts': ['1', '2'], 'ans': 0},
                {'q': 'B?', 'opts': ['1', '2'], 'ans': 0},
            ],
            only_extra=True,
            question_count=5,
            max_errors=2,
            secret='test',
        )
        with pytest.raises(ValueError, match='В пуле только 2'):
            engine.create_challenge()


class TestSingleUseToken:
    def test_token_consumed_after_pass(self):
        engine = make_engine()
        ch = engine.create_challenge()
        assert engine.verify(ch.token, right_answers(ch))['passed'] is True
        assert engine.verify(ch.token, right_answers(ch))['error'] == 'invalid_token'

    def test_token_consumed_after_fail(self):
        """Провал тоже сжигает токен — иначе один челлендж = бесконечные попытки."""
        engine = make_engine(max_errors=0, rate_limit=0)
        ch = engine.create_challenge()
        assert engine.verify(ch.token, {str(i): 99 for i in range(5)})['passed'] is False
        result = engine.verify(ch.token, right_answers(ch))
        assert result['passed'] is False
        assert result['error'] == 'invalid_token'


class TestRateLimit:
    def test_failed_attempts_are_counted(self):
        engine = make_engine(max_errors=0, rate_limit=2, rate_window=600)
        ip = '203.0.113.9'
        for _ in range(2):
            ch = engine.create_challenge()
            assert engine.verify(ch.token, {}, ip=ip)['passed'] is False
        ch = engine.create_challenge()
        assert engine.verify(ch.token, right_answers(ch), ip=ip)['error'] == 'rate_limited'

    def test_successful_passes_do_not_consume_limit(self):
        """Раньше честный пользователь блокировал себя сам после N проходов."""
        engine = make_engine(max_errors=0, rate_limit=2, rate_window=600)
        ip = '203.0.113.10'
        for _ in range(6):
            ch = engine.create_challenge()
            result = engine.verify(ch.token, right_answers(ch), ip=ip)
            assert result['passed'] is True
            assert result.get('error') != 'rate_limited'

    def test_pass_clears_failure_counter(self):
        engine = make_engine(max_errors=0, rate_limit=2, rate_window=600)
        ip = '203.0.113.11'
        ch = engine.create_challenge()
        engine.verify(ch.token, {}, ip=ip)          # 1 провал
        ch = engine.create_challenge()
        assert engine.verify(ch.token, right_answers(ch), ip=ip)['passed'] is True
        # счётчик сброшен — следующие 2 провала снова допустимы
        for _ in range(2):
            ch = engine.create_challenge()
            assert engine.verify(ch.token, {}, ip=ip).get('error') != 'rate_limited'
        ch = engine.create_challenge()
        assert engine.verify(ch.token, {}, ip=ip)['error'] == 'rate_limited'

    def test_disabled(self):
        engine = make_engine(max_errors=0, rate_limit=0)
        ip = '203.0.113.12'
        for _ in range(30):
            ch = engine.create_challenge()
            assert engine.verify(ch.token, {}, ip=ip).get('error') != 'rate_limited'

    def test_no_ip_never_limited(self):
        engine = make_engine(max_errors=0, rate_limit=1)
        for _ in range(5):
            ch = engine.create_challenge()
            assert engine.verify(ch.token, {}).get('error') != 'rate_limited'


class TestChallengeRateLimit:
    def test_limit(self):
        engine = make_engine(challenge_rate_limit=2)
        ip = '203.0.113.13'
        assert engine.check_challenge_limit(ip) is False
        engine.track_challenge(ip)
        engine.track_challenge(ip)
        assert engine.check_challenge_limit(ip) is True

    def test_disabled(self):
        engine = make_engine(challenge_rate_limit=0)
        for _ in range(100):
            engine.track_challenge('203.0.113.14')
        assert engine.check_challenge_limit('203.0.113.14') is False


class TestAutoBlacklist:
    def test_fail_threshold_bans(self):
        engine = make_engine(max_errors=0, rate_limit=0, fail_threshold=2, blacklist_ttl=3600)
        ip = '203.0.113.20'
        for _ in range(2):
            ch = engine.create_challenge()
            engine.verify(ch.token, {}, ip=ip)
        assert engine.is_blacklisted(ip) is True
        ch = engine.create_challenge()
        assert engine.verify(ch.token, {}, ip=ip)['error'] == 'blacklisted'

    def test_fail_threshold_with_forever_ttl(self):
        """blacklist_ttl=0 — бан навсегда; счётчик провалов не должен истекать сразу."""
        engine = make_engine(max_errors=0, rate_limit=0, fail_threshold=2, blacklist_ttl=0)
        ip = '203.0.113.21'
        for _ in range(2):
            ch = engine.create_challenge()
            engine.verify(ch.token, {}, ip=ip)
        assert engine.is_blacklisted(ip) is True

    def test_success_resets_fail_counter(self):
        engine = make_engine(max_errors=0, rate_limit=0, fail_threshold=2)
        ip = '203.0.113.22'
        ch = engine.create_challenge()
        engine.verify(ch.token, {}, ip=ip)
        ch = engine.create_challenge()
        engine.verify(ch.token, right_answers(ch), ip=ip)
        ch = engine.create_challenge()
        engine.verify(ch.token, {}, ip=ip)
        assert engine.is_blacklisted(ip) is False


class TestAnswersPayload:
    def test_answers_list_rejected(self):
        engine = make_engine()
        ch = engine.create_challenge()
        result = engine.verify(ch.token, [0, 1, 2])
        assert result['error'] == 'invalid_answers'

    def test_answers_none_rejected(self):
        engine = make_engine()
        ch = engine.create_challenge()
        assert engine.verify(ch.token, None)['error'] == 'invalid_answers'

    def test_fingerprint_not_dict_is_ignored(self):
        engine = make_engine(max_errors=1)
        ch = engine.create_challenge()
        answers = right_answers(ch)
        answers['0'] = 99
        result = engine.verify(ch.token, answers, fingerprint='honeypot')
        assert result['passed'] is True

    def test_non_numeric_answer_counts_as_error(self):
        engine = make_engine(max_errors=0)
        ch = engine.create_challenge()
        answers = right_answers(ch)
        answers['0'] = 'maybe'
        result = engine.verify(ch.token, answers)
        assert result['passed'] is False
        assert result['errors'] == 1


class TestStrictFingerprint:
    """Строгий режим — задуманное поведение: Яндекс-браузер сдаёт идеально."""

    def test_ya_signal_forces_zero_errors(self):
        engine = make_engine(max_errors=1)
        ch = engine.create_challenge()
        answers = right_answers(ch)
        answers['0'] = 99
        assert engine.verify(ch.token, answers, fingerprint={'yaBrands': True})['passed'] is False

    def test_without_signal_same_answers_pass(self):
        engine = make_engine(max_errors=1)
        ch = engine.create_challenge()
        answers = right_answers(ch)
        answers['0'] = 99
        assert engine.verify(ch.token, answers)['passed'] is True
