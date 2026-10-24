# -*- coding: utf-8 -*-
"""Тесты состояния «капча пройдена»: TTL, привязка к клиенту, logout."""

import time

from kremle_detect.session import (
    build_verification, is_verified, remaining_seconds, ua_fingerprint,
)

UA = 'Mozilla/5.0 YaBrowser/24.1'


class TestUaFingerprint:
    def test_stable(self):
        assert ua_fingerprint(UA) == ua_fingerprint(UA)

    def test_differs(self):
        assert ua_fingerprint(UA) != ua_fingerprint('Mozilla/5.0 Chrome/120')

    def test_empty(self):
        assert ua_fingerprint(None) == ''
        assert ua_fingerprint('') == ''


class TestVerifiedState:
    def test_fresh_state_is_valid(self):
        state = build_verification(ip='1.2.3.4', ua=UA, ttl=3600)
        assert is_verified(state, ip='1.2.3.4', ua=UA) is True

    def test_legacy_true_is_rejected(self):
        """Старый формат (True) не даёт вечного прохода — один раз перепройти."""
        assert is_verified(True, ua=UA) is False

    def test_garbage(self):
        assert is_verified(None) is False
        assert is_verified('yes') is False
        assert is_verified({}) is False
        assert is_verified({'ok': False, 'exp': time.time() + 100}) is False

    def test_expired(self):
        state = build_verification(ua=UA, ttl=1)
        state['exp'] = time.time() - 1
        assert is_verified(state, ua=UA) is False

    def test_ttl_zero_means_forever(self):
        state = build_verification(ua=UA, ttl=0)
        state['exp'] = 0
        assert is_verified(state, ua=UA) is True
        assert remaining_seconds(state) is None

    def test_remaining_seconds(self):
        state = build_verification(ua=UA, ttl=60)
        remaining = remaining_seconds(state)
        assert remaining is not None and 55 <= remaining <= 60

    def test_ip_binding_enabled(self):
        state = build_verification(ip='1.2.3.4', ua=UA, ttl=3600)
        assert is_verified(state, ip='1.2.3.4', ua=UA, bind_ip=True) is True
        assert is_verified(state, ip='5.6.7.8', ua=UA, bind_ip=True) is False

    def test_ip_binding_disabled(self):
        state = build_verification(ip='1.2.3.4', ua=UA, ttl=3600)
        assert is_verified(state, ip='5.6.7.8', ua=UA, bind_ip=False) is True

    def test_ua_binding(self):
        state = build_verification(ua=UA, ttl=3600)
        assert is_verified(state, ua=UA, bind_ua=True) is True
        assert is_verified(state, ua='Chrome/120', bind_ua=True) is False
        assert is_verified(state, ua='Chrome/120', bind_ua=False) is True

    def test_missing_ua_in_state_is_tolerant(self):
        state = build_verification(ua='', ttl=3600)
        assert is_verified(state, ua='Chrome/120', bind_ua=True) is True

    def test_missing_ip_in_state_is_tolerant(self):
        state = build_verification(ip='', ua=UA, ttl=3600)
        assert is_verified(state, ip='1.2.3.4', ua=UA, bind_ip=True) is True
