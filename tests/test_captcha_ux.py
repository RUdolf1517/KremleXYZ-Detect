# -*- coding: utf-8 -*-
"""
Качество и UX капчи: честный результат, таймер, доступность.

Проверки статические (шаблон) и через Flask test client (что реально уходит
браузеру) — шаблон один для Flask/Django/FastAPI, ломается он одинаково.
"""

import json
import os
import re

import pytest

from kremle_detect.captcha import CaptchaEngine
from kremle_detect.storage import MemoryStorage

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'kremle_detect', 'templates', 'kremle_captcha.html',
)


@pytest.fixture(scope='module')
def template():
    with open(TEMPLATE, encoding='utf-8') as f:
        return f.read()


def _extra(n, prefix='q'):
    return [
        {'q': f'{prefix}{i}', 'opts': ['1', '2', '3', '4'], 'ans': 0}
        for i in range(n)
    ]


class TestHonestResult:
    """Клиент показывает тот порог, по которому сервер реально судил."""

    def test_template_uses_server_threshold(self, template):
        assert 'data.max_errors' in template
        assert 'SERVER_MAX_ERRORS' in template

    def test_template_falls_back_for_old_server(self, template):
        """Старый сервер без max_errors — прежнее поведение, а не поломка."""
        assert 'data.errors > data.total / 2' in template

    def test_failed_verdict_within_threshold_is_not_almost(self, template):
        """Провал больше не называется «Почти»."""
        assert 'Проверка не пройдена.' in template
        assert 'допустимо не больше' in template


class TestNoQuestions:
    def test_empty_bank_is_explained(self, template):
        """Пустой банк — поломка сервера, клиент не должен видеть «ошибка: …». """
        assert "data.error === 'no_questions'" in template
        assert 'Капча недоступна.' in template


class TestTimer:
    def test_template_has_countdown(self, template):
        assert 'id="timer"' in template
        assert 'startTimer' in template
        assert 'stopTimer' in template
        assert 'expires_in' in template

    def test_timer_warns_before_expiry(self, template):
        assert 'left <= 60' in template
        assert 'время истекло' in template

    def test_timer_stops_on_result(self, template):
        """Таймер не должен тикать поверх экрана результата."""
        result_fn = template.split('function showResult(data) {')[1].split('\n}')[0]
        assert 'stopTimer()' in result_fn


class TestAccessibility:
    def test_options_are_a_radiogroup(self, template):
        assert 'role="radiogroup"' in template
        assert "setAttribute('role', 'radio')" in template
        assert "setAttribute('aria-checked'" in template

    def test_question_change_is_announced(self, template):
        assert 'aria-live="polite"' in template
        assert 'qtext' in template and 'focus()' in template

    def test_tap_targets_are_large_enough(self, template):
        assert 'min-height: 44px' in template

    def test_keyboard_focus_is_visible(self, template):
        assert ':focus-visible' in template

    def test_noscript_explains_javascript_requirement(self, template):
        assert '<noscript>' in template
        assert 'Нужен JavaScript' in template

    def test_no_script_placeholder_is_replaced(self, template):
        assert template.count('{{ questions_json }}') == 1


class TestChallengePayload:
    """Что реально получает браузер от сервера."""

    def _engine(self, **kwargs):
        params = dict(
            categories=['math'], question_count=5, max_errors=2,
            secret='test', storage=MemoryStorage(),
            questions_source='own',
        )
        params.update(kwargs)
        return CaptchaEngine(**params)

    def test_payload_has_threshold_and_ttl(self):
        ch = self._engine().create_challenge()
        data = ch.to_dict(max_errors=2)
        assert data['max_errors'] == 2
        assert 0 < data['expires_in'] <= 900

    def test_answers_never_leave_the_server(self):
        ch = self._engine().create_challenge()
        payload = json.dumps(ch.to_dict(max_errors=2), ensure_ascii=False)
        assert '"ans"' not in payload

    def test_flask_endpoint_sends_threshold(self):
        pytest.importorskip('flask')
        from flask import Flask

        from kremle_detect.integrations.flask_ext import KremleFlask

        app = Flask(__name__)
        app.secret_key = 's'
        KremleFlask(
            app, categories=['math'], question_count=5, max_errors=2,
            storage=MemoryStorage(), secret='test', questions_source='own',
        )
        html = app.test_client().get('/kremle/challenge').data.decode()
        match = re.search(r'var DATA = (\{.*?\});\n', html, re.S)
        assert match, 'в шаблоне нет DATA'
        data = json.loads(match.group(1))
        assert data['max_errors'] == 2
        assert data['expires_in'] > 0


class TestRotationInPayload:
    """Соседние выдачи не повторяют вопросы, пока в пуле есть свежие."""

    def test_two_challenges_differ(self):
        engine = CaptchaEngine(
            question_count=3, max_errors=0, secret='test',
            storage=MemoryStorage(), only_extra=True, extra_questions=_extra(20),
        )
        first = [q['q'] for q in engine.create_challenge().questions]
        second = [q['q'] for q in engine.create_challenge().questions]
        assert not set(first) & set(second)
