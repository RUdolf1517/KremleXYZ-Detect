# -*- coding: utf-8 -*-
"""Health знает о вопросах: сколько их и когда обновлялся кеш.

Обычный health отвечает «процесс жив, хранилище отвечает». Про тихо умерший
`sync` он молчал: кеш «Решу ЕГЭ» месячной давности отдавался как ни в чём не
бывало, а `status: ok` успокаивал ровно до того момента, когда банк опустеет.
"""

import json
import time

import pytest

from kremle_detect.captcha import CaptchaEngine
from kremle_detect.metrics import health_payload
from kremle_detect.questions import (
    DEFAULT_STALE_CACHE_HOURS, questions_health,
)
from kremle_detect.questions.sdamgia import cache_path, clear_cache_memo, write_cache

CACHED_QUESTION = {
    'q': 'Сколько будет 2 + 2?',
    'opts': ['4', '5', '22', '0'],
    'ans': 0,
    'images': [],
}
IMAGE_QUESTION = {
    'q': 'Найдите площадь фигуры на рисунке',
    'opts': ['1', '2', '3', '4'],
    'ans': 2,
    'images': ['https://example.invalid/fig.png'],
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Кеш во временном каталоге — тесты не трогают домашний."""
    monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path))
    clear_cache_memo()
    yield tmp_path
    clear_cache_memo()


def write_sdamgia_cache(path, questions, age_hours=0.0, category='math'):
    """Положить кеш «Решу ЕГЭ» с заданным возрастом."""
    write_cache(category, questions, cache_dir=str(path))
    target = cache_path(category, cache_dir=str(path))
    with open(target, encoding='utf-8') as handle:
        data = json.load(handle)
    data['fetched_at'] = time.time() - age_hours * 3600
    with open(target, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False)
    clear_cache_memo()


class TestQuestionsHealth:
    def test_own_source_ignores_cache(self, cache_dir):
        health = questions_health(['math'], source='own')
        assert health['reason'] is None
        assert health['stale'] is False
        assert health['age_hours'] is None
        assert health['count'] > 0
        assert health['cached'] == 0

    def test_auto_without_cache_is_not_degraded(self, cache_dir):
        # auto без кеша — штатный режим: работает встроенный банк
        health = questions_health(['math'], source='auto')
        assert health['reason'] is None
        assert health['count'] > 0
        assert health['missing_cache'] == ['math']

    def test_sdamgia_without_cache_is_degraded(self, cache_dir):
        health = questions_health(['math'], source='sdamgia')
        assert health['reason'] == 'no_cache'
        assert health['count'] == 0

    def test_mixed_without_cache_is_degraded(self, cache_dir):
        assert questions_health(['math'], source='own+sdamgia')['reason'] == 'no_cache'

    def test_fresh_cache_is_ok(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=1)
        health = questions_health(['math'], source='sdamgia')
        assert health['reason'] is None
        assert health['stale'] is False
        assert health['count'] == 1
        assert 0.9 < health['age_hours'] < 2.1

    def test_stale_cache_is_reported(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=50)
        health = questions_health(['math'], source='sdamgia')
        assert health['stale'] is True
        assert health['reason'] == 'stale_cache'
        assert health['age_hours'] > DEFAULT_STALE_CACHE_HOURS
        # устаревший кеш всё равно отдаётся: пустой банк хуже
        assert health['count'] == 1

    def test_stale_cache_also_degrades_auto(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=200)
        assert questions_health(['math'], source='auto')['reason'] == 'stale_cache'

    def test_oldest_category_wins(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=1, category='math')
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=100, category='physics')
        health = questions_health(['math', 'physics'], source='sdamgia')
        assert health['age_hours'] > 99
        assert health['stale'] is True

    def test_threshold_is_configurable(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=10)
        assert questions_health(['math'], source='sdamgia')['stale'] is False
        strict = questions_health(['math'], source='sdamgia', stale_after_hours=5)
        assert strict['stale'] is True

    def test_images_are_filtered_unless_enabled(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION, IMAGE_QUESTION])
        assert questions_health(['math'], source='sdamgia')['count'] == 1
        assert questions_health(
            ['math'], source='sdamgia', allow_images=True
        )['count'] == 2

    def test_extra_questions_count_as_own(self, cache_dir):
        extra = [dict(CACHED_QUESTION, q='свой вопрос')]
        base = questions_health(['math'], source='own')['count']
        assert questions_health(['math'], source='own', extra_questions=extra)['count'] == base + 1

    def test_only_extra_ignores_cache(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=500)
        health = questions_health(
            ['math'], source='sdamgia', only_extra=True,
            extra_questions=[dict(CACHED_QUESTION)]
        )
        assert health['count'] == 1
        assert health['reason'] is None


class TestEngineHealth:
    def test_engine_reports_its_own_settings(self, cache_dir):
        engine = CaptchaEngine(categories=['math'], questions_source='sdamgia',
                               challenge_rate_limit=0)
        assert engine.questions_health()['source'] == 'sdamgia'
        assert engine.questions_health()['reason'] == 'no_cache'

    def test_engine_sees_fresh_cache(self, cache_dir):
        write_sdamgia_cache(cache_dir, [CACHED_QUESTION], age_hours=2)
        engine = CaptchaEngine(categories=['math'], questions_source='sdamgia',
                               challenge_rate_limit=0)
        health = engine.questions_health()
        assert health['count'] == 1
        assert health['stale'] is False


class TestHealthPayload:
    def test_ok_when_everything_alive(self):
        payload = health_payload('test', questions={'count': 5, 'reason': None})
        assert payload['status'] == 'ok'
        assert payload['reasons'] == []
        assert payload['questions'] == {'count': 5, 'reason': None}

    def test_stale_questions_degrade_status(self):
        payload = health_payload('test', questions={'count': 5, 'reason': 'stale_cache'})
        assert payload['status'] == 'degraded'
        assert payload['reasons'] == ['questions:stale_cache']
        # хранилище живо — 200, а не 503: устаревший кеш не повод гасить под
        assert payload['storage_ok'] is True

    def test_empty_bank_degrades_status(self):
        payload = health_payload('test', questions={'count': 0, 'reason': 'no_cache'})
        assert payload['status'] == 'degraded'
        assert payload['reasons'] == ['questions:no_cache', 'questions:empty']

    def test_questions_block_is_optional(self):
        # обратная совместимость: без questions payload как раньше
        payload = health_payload('test')
        assert payload['status'] == 'ok'
        assert 'questions' not in payload

    def test_storage_and_questions_reasons_together(self):
        class Broken:
            def set(self, *a, **k):
                raise RuntimeError('нет связи')

            def get(self, *a, **k):
                raise RuntimeError('нет связи')

            def delete(self, *a, **k):
                pass

        payload = health_payload('test', storage=Broken(), questions={'count': 0})
        assert payload['status'] == 'degraded'
        assert payload['storage_ok'] is False
        assert payload['reasons'] == ['storage', 'questions:empty']
