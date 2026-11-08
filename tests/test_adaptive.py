# -*- coding: utf-8 -*-
"""Адаптивная сложность: серия провалов делает капчу строже.

Идея простая и по-человечески честная: первый провал ничего не меняет (мог
ошибиться), три подряд — уже не случайность. Ужесточаем постепенно, а не
блокируем сразу: rate limit и блоклист остаются последней линией.
"""

import pytest

from kremle_detect.captcha import ADAPTIVE_MAX_LEVEL, ADAPTIVE_STREAK_TTL, CaptchaEngine
from kremle_detect.storage import MemoryStorage

IP = '203.0.113.7'


def extra(count):
    return [
        {'q': f'вопрос {i}', 'opts': ['a', 'b', 'c', 'd'], 'ans': 0}
        for i in range(count)
    ]


def make_engine(**kwargs):
    params = dict(
        secret='test', only_extra=True, extra_questions=extra(40),
        question_count=5, max_errors=2, challenge_rate_limit=0,
    )
    params.update(kwargs)
    return CaptchaEngine(**params)


def fail_once(engine, ip=IP):
    """Получить челлендж и провалить его (все ответы неверные)."""
    challenge = engine.create_challenge(ip=ip)
    answers = {str(i): (q['ans'] + 1) % len(q['opts'])
               for i, q in enumerate(challenge.questions)}
    return engine.verify(challenge.token, answers, ip=ip)


def pass_once(engine, ip=IP):
    challenge = engine.create_challenge(ip=ip)
    answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}
    return engine.verify(challenge.token, answers, ip=ip)


class TestStreak:
    def test_first_fail_changes_nothing(self):
        engine = make_engine()
        fail_once(engine)
        assert engine.fail_streak(IP) == 1
        assert engine.adaptive_level(IP) == 0
        assert engine.difficulty(IP)['question_count'] == 5

    def test_three_fails_raise_level(self):
        engine = make_engine()
        for _ in range(3):
            fail_once(engine)
        assert engine.fail_streak(IP) == 3
        assert engine.adaptive_level(IP) == 1
        plan = engine.difficulty(IP)
        assert plan['question_count'] == 7      # +2 вопроса
        assert plan['max_errors'] == 1          # строже на единицу

    def test_level_grows_and_is_capped(self):
        engine = make_engine(adaptive_extra_questions=1, question_count=2)
        for _ in range(30):
            fail_once(engine)
        assert engine.adaptive_level(IP) == ADAPTIVE_MAX_LEVEL
        assert engine.difficulty(IP)['max_errors'] == 0

    def test_success_resets_streak(self):
        engine = make_engine()
        fail_once(engine)
        fail_once(engine)
        assert engine.fail_streak(IP) == 2
        pass_once(engine)
        assert engine.fail_streak(IP) == 0
        assert engine.adaptive_level(IP) == 0

    def test_streak_is_per_ip(self):
        engine = make_engine()
        for _ in range(3):
            fail_once(engine, ip=IP)
        assert engine.adaptive_level('198.51.100.1') == 0

    def test_streak_expires(self):
        storage = MemoryStorage()
        engine = make_engine(storage=storage)
        for _ in range(3):
            fail_once(engine)
        assert engine.adaptive_level(IP) == 1
        # окно серии истекло — человек вернулся позже, история не тянется
        storage.delete(f'streak:{IP}')
        assert engine.adaptive_level(IP) == 0

    def test_streak_ttl_is_short(self):
        assert ADAPTIVE_STREAK_TTL <= 3600

    def test_disabled_adaptive_never_raises_level(self):
        engine = make_engine(adaptive=False)
        for _ in range(10):
            fail_once(engine)
        assert engine.fail_streak(IP) == 0
        assert engine.difficulty(IP) == {
            'level': 0, 'question_count': 5, 'max_errors': 2,
        }

    def test_threshold_is_configurable(self):
        engine = make_engine(adaptive_threshold=1)
        fail_once(engine)
        assert engine.adaptive_level(IP) == 1


class TestChallenge:
    def test_hard_challenge_is_longer(self):
        engine = make_engine()
        normal = engine.create_challenge(ip=IP)
        assert len(normal.questions) == 5
        assert normal.max_errors == 2

        for _ in range(3):
            fail_once(engine)
        hard = engine.create_challenge(ip=IP)
        assert len(hard.questions) == 7
        assert hard.max_errors == 1

    def test_challenge_without_ip_is_normal(self):
        engine = make_engine()
        for _ in range(3):
            fail_once(engine)
        assert len(engine.create_challenge().questions) == 5

    def test_client_sees_the_real_threshold(self):
        engine = make_engine()
        for _ in range(3):
            fail_once(engine)
        challenge = engine.create_challenge(ip=IP)
        data = challenge.to_dict(max_errors=challenge.max_errors)
        assert data['max_errors'] == 1

    def test_verify_judges_by_challenge_threshold(self):
        """Строгий челлендж нельзя пройти по мягкому порогу движка."""
        engine = make_engine(max_errors=2)
        for _ in range(3):
            fail_once(engine)
        challenge = engine.create_challenge(ip=IP)
        # одна ошибка: по настройкам движка (2) прошли бы, по выданному
        # порогу (1) — тоже; делаем две ошибки
        answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}
        for i in (0, 1):
            answers[str(i)] = (challenge.questions[i]['ans'] + 1) % len(
                challenge.questions[i]['opts']
            )
        result = engine.verify(challenge.token, answers, ip=IP)
        assert result['passed'] is False
        assert result['max_errors'] == 1

    def test_threshold_survives_storage_roundtrip(self):
        engine = make_engine()
        for _ in range(3):
            fail_once(engine)
        challenge = engine.create_challenge(ip=IP)
        restored = engine.get_challenge(challenge.token)
        assert restored is not None
        assert restored.max_errors == 1

    def test_old_challenge_without_threshold_still_verifies(self):
        engine = make_engine()
        challenge = engine.create_challenge(ip=IP)
        stored = engine.storage.get(f'challenge:{challenge.token}')
        stored.pop('max_errors', None)          # как челлендж из 2.11
        engine.storage.set(f'challenge:{challenge.token}', stored, 900)
        answers = {str(i): q['ans'] for i, q in enumerate(challenge.questions)}
        assert engine.verify(challenge.token, answers, ip=IP)['passed'] is True

    def test_pool_smaller_than_requested_count(self):
        """Если вопросов меньше плана — берём сколько есть, а не падаем."""
        engine = make_engine(extra_questions=extra(6), question_count=5)
        for _ in range(3):
            fail_once(engine)
        challenge = engine.create_challenge(ip=IP)
        assert len(challenge.questions) == 6     # весь пул, план был 7
        assert challenge.max_errors <= 5


class TestInterplayWithRateLimit:
    def test_adaptive_comes_before_rate_limit(self):
        engine = make_engine(rate_limit=10)
        for _ in range(3):
            fail_once(engine)
        # ещё не заблокирован, но уже строже
        assert engine.check_rate_limit(IP) is False
        assert engine.adaptive_level(IP) == 1

    def test_rate_limit_still_blocks(self):
        engine = make_engine(rate_limit=3)
        for _ in range(3):
            fail_once(engine)
        assert engine.check_rate_limit(IP) is True

    def test_admin_reset_via_verify_pass(self):
        engine = make_engine(rate_limit=10)
        for _ in range(3):
            fail_once(engine)
        assert engine.adaptive_level(IP) == 1
        pass_once(engine)
        assert engine.adaptive_level(IP) == 0


class TestValidation:
    @pytest.mark.parametrize('kwargs', [
        {'adaptive_threshold': 0},
        {'adaptive_threshold': -1},
        {'adaptive_extra_questions': -1},
        {'adaptive_threshold': 1.5},
    ])
    def test_bad_values_raise(self, kwargs):
        with pytest.raises(ValueError):
            make_engine(**kwargs)


class TestIntegrationFlask:
    """Через настоящий роут: три провала → следующий челлендж строже."""

    @pytest.fixture
    def app(self):
        flask = pytest.importorskip('flask')
        from kremle_detect.integrations.flask_ext import KremleFlask

        flask_app = flask.Flask(__name__)
        flask_app.secret_key = 'test'
        KremleFlask(
            flask_app, categories=['math'], question_count=3, max_errors=2,
            secret='test', only_extra=True, extra_questions=extra(20),
            challenge_rate_limit=0, rate_limit=10,
        )
        return flask_app

    def test_three_fails_make_next_challenge_stricter(self, app):
        client = app.test_client()
        env = {'REMOTE_ADDR': IP}

        def challenge():
            return client.get('/kremle/challenge', environ_overrides=env,
                              headers={'Accept': 'application/json'}).get_json()

        baseline = challenge()
        assert len(baseline['questions']) == 3
        assert baseline['max_errors'] == 2

        # три провала подряд: пустые ответы — это заведомо все ошибки
        for _ in range(3):
            current = challenge()
            result = client.post('/kremle/verify',
                                 json={'token': current['token'], 'answers': {}},
                                 environ_overrides=env).get_json()
            assert result['passed'] is False

        harder = challenge()
        assert len(harder['questions']) == 5        # +2 вопроса
        assert harder['max_errors'] == 1            # строже на единицу
        assert 'Adaptive difficulty' not in harder  # внутреннее — не в payload

    def test_success_returns_captcha_to_normal(self, app):
        client = app.test_client()
        env = {'REMOTE_ADDR': IP}
        engine = app.extensions['kremle'].engine

        for _ in range(3):
            current = client.get('/kremle/challenge', environ_overrides=env,
                                 headers={'Accept': 'application/json'}).get_json()
            client.post('/kremle/verify', json={'token': current['token'], 'answers': {}},
                        environ_overrides=env)

        stricter = client.get('/kremle/challenge', environ_overrides=env,
                              headers={'Accept': 'application/json'}).get_json()
        assert len(stricter['questions']) == 5

        # проходим: ответы берём у сервера, клиенту они не отдаются
        stored = engine.get_challenge(stricter['token'])
        assert stored is not None
        answers = {str(i): q['ans'] for i, q in enumerate(stored.questions)}
        client.post('/kremle/verify', json={'token': stricter['token'], 'answers': answers},
                    environ_overrides=env)

        after = client.get('/kremle/challenge', environ_overrides=env,
                           headers={'Accept': 'application/json'}).get_json()
        assert len(after['questions']) == 3
        assert after['max_errors'] == 2


class TestIntegrationDjango:
    def test_settings_unlock_adaptive(self):
        pytest.importorskip('django')
        from django.conf import settings as dj_settings
        if not dj_settings.configured:
            import tests.test_django_integration  # noqa: F401 — общая настройка

        from django.test import RequestFactory, override_settings

        from kremle_detect.integrations import django_ext

        def request():
            req = RequestFactory().get('/')
            req.session = {}
            return req

        view = {p.name: p.callback for p in django_ext.kremle_urls()[0]}['kremle_challenge']
        with override_settings(
            KREMLE_QUESTION_COUNT=3, KREMLE_MAX_ERRORS=2, KREMLE_ONLY_EXTRA=True,
            KREMLE_EXTRA_QUESTIONS=extra(20), KREMLE_CHALLENGE_RATE_LIMIT=0,
        ):
            engine = django_ext._get_engine(dj_settings)
            baseline = engine.create_challenge(ip=IP)
            assert len(baseline.questions) == 3

            for _ in range(3):
                engine._track_streak_fail(IP)
            harder = engine.create_challenge(ip=IP)
            assert len(harder.questions) == 5
            assert harder.max_errors == 1
            assert view is not None   # вьюха на месте, роут не сломан


class TestRotationKeepsAdaptiveLength:
    def test_rotation_does_not_shrink_the_challenge(self):
        """Ротация сравнивала «свежие» с базовым question_count, а не с нужным.

        После серии провалов челлендж должен быть длиннее — но если «свежих»
        вопросов ровно question_count, движок отдавал их и обрезал капчу до
        базовой длины вместо того, чтобы добрать из уже показанных.
        """
        pool = extra(20)
        engine = make_engine(extra_questions=pool, adaptive_threshold=1,
                             adaptive_extra_questions=3, question_count=5)
        fail_once(engine)
        assert engine.difficulty(IP)['question_count'] == 8

        shown = [q['q'].lower() for q in pool[5:]]
        engine.storage.set(engine._rotation_key(), {'texts': shown}, 600)

        challenge = engine.create_challenge(ip=IP)
        assert len(challenge.questions) == 8
