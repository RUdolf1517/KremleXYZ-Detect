# -*- coding: utf-8 -*-
"""Переключатель источников вопросов (#34): свои / «Решу ЕГЭ» / оба вместе.

Проверяем пропорцию, добор при пустом источнике и то, что происхождение
каждого вопроса видно в JSON челленджа.
"""

import pytest

from kremle_detect.captcha import CaptchaEngine
from kremle_detect.questions import (
    MIXED_SOURCE,
    SOURCE_ALIASES,
    get_questions,
    normalize_source,
    validate_mixed_ratio,
)
from kremle_detect.questions.sdamgia import write_cache

PORTAL_QUESTIONS = [
    {
        'q': f'Задание портала {i}',
        'opts': ['a', 'b', 'c', 'd'],
        'ans': 0,
        'problem_id': str(1000 + i),
        'source': {'name': 'РешуЕГЭ', 'url': 'https://sdamgia.ru/'},
    }
    for i in range(20)
]


@pytest.fixture
def cache_dir(tmp_path):
    """Кеш портала на 20 заданий (кеш категории math)."""
    write_cache('math', PORTAL_QUESTIONS, cache_dir=str(tmp_path))
    return str(tmp_path)


@pytest.fixture
def empty_cache(tmp_path):
    return str(tmp_path)


class TestSourceNames:
    def test_public_names(self):
        assert normalize_source('own') == 'own'
        assert normalize_source('sdamgia') == 'sdamgia'
        assert normalize_source(MIXED_SOURCE) == MIXED_SOURCE

    def test_builtin_is_alias_of_own(self):
        """Алиас ещё работает, но уже предупреждает: удаление — в 3.0."""
        assert SOURCE_ALIASES['builtin'] == 'own'
        with pytest.warns(DeprecationWarning):
            assert normalize_source('builtin') == 'own'

    def test_unknown_source_rejected(self):
        with pytest.raises(ValueError) as excinfo:
            normalize_source('yandex')
        assert 'own+sdamgia' in str(excinfo.value)

    def test_ratio_validation(self):
        assert validate_mixed_ratio(0.5) == 0.5
        assert validate_mixed_ratio(0) == 0.0
        assert validate_mixed_ratio(1) == 1.0
        for bad in (-0.1, 1.1, 'много', None):
            with pytest.raises(ValueError):
                validate_mixed_ratio(bad)


class TestMixedPool:
    def test_half_and_half(self, cache_dir):
        pool = get_questions(['math'], count=10, source=MIXED_SOURCE,
                             cache_dir=cache_dir, mixed_ratio=0.5)
        kinds = [q['source_kind'] for q in pool]
        assert len(pool) == 10
        assert kinds.count('sdamgia') == 5
        assert kinds.count('own') == 5

    def test_ratio_is_respected(self, cache_dir):
        pool = get_questions(['math'], count=10, source=MIXED_SOURCE,
                             cache_dir=cache_dir, mixed_ratio=0.3)
        assert [q['source_kind'] for q in pool].count('sdamgia') == 3

    def test_ratio_zero_means_own_only(self, cache_dir):
        pool = get_questions(['math'], count=10, source=MIXED_SOURCE,
                             cache_dir=cache_dir, mixed_ratio=0)
        assert {q['source_kind'] for q in pool} == {'own'}

    def test_ratio_one_means_portal_only(self, cache_dir):
        pool = get_questions(['math'], count=10, source=MIXED_SOURCE,
                             cache_dir=cache_dir, mixed_ratio=1)
        assert {q['source_kind'] for q in pool} == {'sdamgia'}

    def test_empty_portal_falls_back_to_own(self, empty_cache):
        pool = get_questions(['math'], count=10, source=MIXED_SOURCE,
                             cache_dir=empty_cache, mixed_ratio=0.5)
        assert len(pool) == 10
        assert {q['source_kind'] for q in pool} == {'own'}

    def test_small_portal_cache_is_topped_up(self, tmp_path):
        write_cache('math', PORTAL_QUESTIONS[:2], cache_dir=str(tmp_path))
        pool = get_questions(['math'], count=10, source=MIXED_SOURCE,
                             cache_dir=str(tmp_path), mixed_ratio=0.5)
        kinds = [q['source_kind'] for q in pool]
        assert len(pool) == 10
        assert kinds.count('sdamgia') == 2
        assert kinds.count('own') == 8

    def test_portal_questions_keep_attribution(self, cache_dir):
        pool = get_questions(['math'], count=4, source=MIXED_SOURCE,
                             cache_dir=cache_dir, mixed_ratio=1)
        assert all(q['source']['name'] == 'РешуЕГЭ' for q in pool)
        assert {q['source_kind'] for q in pool} == {'sdamgia'}

    def test_mono_sources_mark_kind(self, cache_dir):
        own = get_questions(['math'], count=3, source='own')
        assert {q['source_kind'] for q in own} == {'own'}
        portal = get_questions(['math'], count=3, source='sdamgia', cache_dir=cache_dir)
        assert {q['source_kind'] for q in portal} == {'sdamgia'}


class TestEngineMixedSource:
    def make_engine(self, **kwargs):
        params = dict(secret='test', question_count=6, max_errors=2)
        params.update(kwargs)
        return CaptchaEngine(**params)

    def test_engine_accepts_mixed_source(self):
        engine = self.make_engine(questions_source=MIXED_SOURCE, mixed_ratio=0.5,
                                  categories=['math'])
        assert engine.questions_source == MIXED_SOURCE
        assert engine.mixed_ratio == 0.5

    def test_builtin_alias_kept(self):
        """Движок принимает старый алиас, пока не вышло 3.0."""
        with pytest.warns(DeprecationWarning):
            engine = self.make_engine(questions_source='builtin')
        assert engine.questions_source == 'own'

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            self.make_engine(questions_source='portal')

    def test_invalid_ratio_rejected(self):
        with pytest.raises(ValueError):
            self.make_engine(questions_source=MIXED_SOURCE, mixed_ratio=2)

    def test_challenge_has_full_set_and_kinds(self, monkeypatch, cache_dir):
        import kremle_detect.captcha as captcha_module

        # движок читает кеш через get_questions(...) — подставляем свой каталог
        real_get_questions = captcha_module.get_questions

        def patched(*args, **kwargs):
            kwargs.setdefault('cache_dir', cache_dir)
            return real_get_questions(*args, **kwargs)

        monkeypatch.setattr(captcha_module, 'get_questions', patched)
        engine = self.make_engine(questions_source=MIXED_SOURCE, mixed_ratio=0.5,
                                  categories=['math'])
        challenge = engine.create_challenge()
        assert len(challenge.questions) == 6
        kinds = [q['source_kind'] for q in challenge.questions]
        assert kinds.count('sdamgia') == 3

        payload = challenge.to_dict()
        assert all('source_kind' in q for q in payload['questions'])
        # ответы по-прежнему не утекают
        assert all('ans' not in q for q in payload['questions'])

    def test_extra_questions_are_own(self):
        engine = self.make_engine(
            questions_source=MIXED_SOURCE, mixed_ratio=0.5, question_count=2,
            categories=['math'],
            extra_questions=[{'q': 'Свой вопрос?', 'opts': ['да', 'нет'], 'ans': 0}],
            only_extra=True,
        )
        challenge = engine.create_challenge()
        assert {q['source_kind'] for q in challenge.questions} == {'own'}

    def test_attribution_counts_by_fact(self, monkeypatch, cache_dir):
        import kremle_detect.captcha as captcha_module

        real_get_questions = captcha_module.get_questions

        def patched(*args, **kwargs):
            kwargs.setdefault('cache_dir', cache_dir)
            return real_get_questions(*args, **kwargs)

        monkeypatch.setattr(captcha_module, 'get_questions', patched)
        engine = self.make_engine(questions_source=MIXED_SOURCE, mixed_ratio=1.0,
                                  categories=['math'], question_count=4)
        payload = engine.create_challenge().to_dict()
        assert payload['sources'][0]['name'] == 'РешуЕГЭ'
        assert 'РешуЕГЭ' in payload['attribution']
        # атрибуция строится по факту: у своих вопросов источника нет
        assert len(payload['sources']) == 1

    def test_own_only_challenge_has_no_attribution(self):
        engine = self.make_engine(questions_source='own', categories=['math'],
                                  question_count=4)
        payload = engine.create_challenge().to_dict()
        assert payload['attribution'] == ''
        assert payload['sources'] == []


class TestIntegrationParity:
    """Один и тот же переключатель во всех трёх интеграциях."""

    def test_flask_passes_mixed_ratio(self):
        pytest.importorskip('flask')
        from flask import Flask

        from kremle_detect.integrations.flask_ext import KremleFlask

        app = Flask(__name__)
        kremle = KremleFlask(app, questions_source=MIXED_SOURCE, mixed_ratio=0.3,
                             categories=['math'])
        assert kremle.engine.questions_source == MIXED_SOURCE
        assert kremle.engine.mixed_ratio == 0.3

    def test_fastapi_passes_mixed_ratio(self):
        pytest.importorskip('fastapi')
        from fastapi import FastAPI

        from kremle_detect.integrations.fastapi_ext import KremleFastAPI

        app = FastAPI()
        kremle = KremleFastAPI(app, questions_source=MIXED_SOURCE, mixed_ratio=0.3,
                               categories=['math'])
        assert kremle.engine.questions_source == MIXED_SOURCE
        assert kremle.engine.mixed_ratio == 0.3

    def test_django_setting(self):
        django = pytest.importorskip('django')
        from django.conf import settings as dj_settings

        if not dj_settings.configured:
            import tests.test_django_integration  # noqa: F401 — общая настройка

        from django.test import override_settings

        from kremle_detect.integrations import django_ext

        with override_settings(KREMLE_QUESTIONS_SOURCE=MIXED_SOURCE,
                               KREMLE_MIXED_RATIO=0.4):
            engine = django_ext._get_engine(dj_settings)
        assert engine.questions_source == MIXED_SOURCE
        assert engine.mixed_ratio == 0.4
        assert django.VERSION  # настройка подтянулась из django.conf

    def test_cli_accepts_mixed_source(self):
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, '-m', 'kremle_detect.cli', 'questions', 'show',
             '-n', '2', '--source', 'own+sdamgia', '--mixed-ratio', '0.5'],
            cwd=root, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert '[1]' in result.stdout
