# -*- coding: utf-8 -*-
"""Тесты политики сегментов, monitor-режима и сэмплирования."""

import pytest

from kremle_detect import CaptchaEngine, MemoryStorage, detect
from kremle_detect.policy import (
    ALLOW, BLOCK, CHALLENGE, DEFAULT_POLICY, MONITOR, Decision, normalize_policy,
    reasons_from_hits, validate_sample_rate,
)

YA_UA = {'User-Agent': 'Mozilla/5.0 YaBrowser/24.1'}


def make_engine(**kwargs):
    params = dict(
        categories=['math'], question_count=5, max_errors=1,
        secret='test', storage=MemoryStorage(),
    )
    params.update(kwargs)
    return CaptchaEngine(**params)


class TestNormalizePolicy:
    def test_defaults(self):
        assert normalize_policy(None) == DEFAULT_POLICY

    def test_override_one_signal(self):
        policy = normalize_policy({'yandex_bot': 'block'})
        assert policy['yandex_bot'] == 'block'
        assert policy['yandex_browser'] == CHALLENGE

    def test_case_insensitive_action(self):
        assert normalize_policy({'yandex_bot': 'BLOCK'})['yandex_bot'] == BLOCK

    def test_unknown_action(self):
        with pytest.raises(ValueError, match='Неизвестное действие'):
            normalize_policy({'yandex_bot': 'ban-forever'})

    def test_unknown_signal_allowed(self):
        """Свой сигнал — ок: политика расширяемая."""
        assert normalize_policy({'my_signal': 'monitor'})['my_signal'] == MONITOR


class TestSampleRate:
    @pytest.mark.parametrize('value', [0, 0.5, 1, 0.0, 1.0])
    def test_valid(self, value):
        assert validate_sample_rate(value) == float(value)

    @pytest.mark.parametrize('value', [-0.1, 1.1, '0.5', None, True])
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_sample_rate(value)


class TestDecision:
    def test_bool(self):
        assert bool(Decision(CHALLENGE, 'x')) is True
        assert bool(Decision(ALLOW, None)) is False

    def test_should_block(self):
        assert Decision(CHALLENGE, 'x').should_block is True
        assert Decision(BLOCK, 'x').should_block is True
        assert Decision(MONITOR, 'x').should_block is False
        assert Decision(ALLOW, None).should_block is False

    def test_shadow(self):
        assert Decision(MONITOR, 'x').is_shadow is True
        assert Decision(CHALLENGE, 'x').is_shadow is False

    def test_repr(self):
        assert 'monitor' in repr(Decision(MONITOR, 'yandex_browser'))


class TestReasons:
    def test_priority_order(self):
        assert list(reasons_from_hits(True, True, True, True)) == [
            'yandex_bot', 'yandex_browser', 'yandex_client_hints', 'yandex_referrer',
        ]

    def test_only_true(self):
        assert list(reasons_from_hits(False, False, False, True)) == ['yandex_client_hints']

    def test_none(self):
        assert list(reasons_from_hits(False, False, False, False)) == []


class TestEngineDecide:
    def test_no_signals_is_allow(self):
        engine = make_engine()
        decision = engine.decide(detect({'User-Agent': 'Chrome/120'}))
        assert decision.action == ALLOW
        assert decision.reason is None

    def test_default_is_challenge(self):
        engine = make_engine()
        assert engine.decide(detect(YA_UA)).action == CHALLENGE

    def test_bot_policy_block(self):
        engine = make_engine(policy={'yandex_bot': 'block'})
        decision = engine.decide(detect({'User-Agent': 'YandexBot/3.0'}))
        assert decision.action == BLOCK
        assert decision.reason == 'yandex_bot'

    def test_monitor_does_not_block(self):
        engine = make_engine(policy={'yandex_browser': 'monitor'})
        decision = engine.decide(detect(YA_UA))
        assert decision.action == MONITOR
        assert decision.should_block is False

    def test_allow_means_ignore(self):
        engine = make_engine(policy={'yandex_referrer': 'allow'})
        decision = engine.decide(detect({'Referer': 'https://yandex.ru/search?q=x'}))
        assert decision.action == ALLOW

    def test_first_non_allow_wins(self):
        engine = make_engine(policy={'yandex_bot': 'allow', 'yandex_browser': 'block'})
        decision = engine.decide(detect({'User-Agent': 'YandexBot/3.0 YaBrowser/24.1'}))
        assert decision.action == BLOCK
        assert decision.reason == 'yandex_bot'

    def test_sample_rate_zero_is_shadow(self):
        engine = make_engine(sample_rate=0.0)
        decision = engine.decide(detect(YA_UA))
        assert decision.action == MONITOR
        assert decision.sampled is False

    def test_sample_rate_one_always_challenge(self):
        engine = make_engine(sample_rate=1.0)
        for _ in range(10):
            assert engine.decide(detect(YA_UA)).action == CHALLENGE

    def test_sample_rate_partial(self):
        engine = make_engine(sample_rate=0.5)
        actions = [engine.decide(detect(YA_UA)).action for _ in range(200)]
        challenged = actions.count(CHALLENGE)
        assert 60 < challenged < 140   # ~100 из 200

    def test_sample_rate_does_not_affect_block(self):
        engine = make_engine(policy={'yandex_bot': 'block'}, sample_rate=0.1)
        for _ in range(20):
            assert engine.decide(detect({'User-Agent': 'YandexBot/3.0'})).action == BLOCK

    def test_metrics_counted(self):
        engine = make_engine(policy={'yandex_browser': 'monitor'})
        engine.decide(detect(YA_UA))
        snap = engine.metrics.snapshot()
        assert snap['detected_by_reason']['yandex_browser'] == 1
        assert snap['actions']['monitor'] == 1
        assert snap['shadow_total'] == 1

    def test_shadow_event_logged(self):
        engine = make_engine(policy={'yandex_browser': 'monitor'})
        decision = engine.decide(detect(YA_UA))
        engine.record_decision(decision, ip='1.2.3.4')
        events = engine.storage.log_get(10)
        assert events[0]['event'] == 'shadow'
        assert events[0]['ip'] == '1.2.3.4'
        assert events[0]['action'] == 'monitor'
