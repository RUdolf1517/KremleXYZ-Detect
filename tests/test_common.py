# -*- coding: utf-8 -*-
"""Тесты разбора Accept и формата JSON-ответов API-клиентам."""

import pytest

from kremle_detect.integrations._common import (
    accepts_json, blocked_payload, challenge_payload, no_store_headers, wants_json,
)


class TestAcceptsJson:
    @pytest.mark.parametrize('header', [
        'application/json',
        'application/json, text/plain, */*',
        'application/hal+json',
        'text/plain;q=0.5, application/json',
    ])
    def test_json(self, header):
        assert accepts_json(header) is True

    @pytest.mark.parametrize('header', [
        'text/html',
        'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        '*/*',
        '',
        None,
    ])
    def test_not_json(self, header):
        assert accepts_json(header) is False

    def test_html_wins_when_first(self):
        assert accepts_json('text/html, application/json') is False

    def test_json_wins_when_first(self):
        assert accepts_json('application/json, text/html') is True


class TestWantsJson:
    def test_accept(self):
        assert wants_json('application/json') is True

    def test_xhr(self):
        assert wants_json(None, 'XMLHttpRequest') is True
        assert wants_json(None, 'xmlhttprequest') is True
        assert wants_json(None, 'fetch') is False

    def test_api_path(self):
        assert wants_json('text/html', None, '/api/orders') is True
        assert wants_json('text/html', None, '/api') is True
        assert wants_json('text/html', None, '/v1/users') is True
        assert wants_json('text/html', None, '/graphql') is True

    def test_normal_page(self):
        assert wants_json('text/html', None, '/') is False
        assert wants_json('text/html', None, '/blog/post-1') is False

    def test_custom_prefixes(self):
        assert wants_json('text/html', None, '/rpc/x', api_prefixes=('/rpc',)) is True
        assert wants_json('text/html', None, '/api/x', api_prefixes=()) is False


class TestPayloads:
    def test_challenge(self):
        payload = challenge_payload('yandex_browser')
        assert payload == {
            'error': 'captcha_required',
            'action': 'challenge',
            'challenge_url': '/kremle/challenge',
            'reason': 'yandex_browser',
        }

    def test_challenge_without_reason(self):
        assert 'reason' not in challenge_payload(None)

    def test_blocked(self):
        payload = blocked_payload('blacklisted')
        assert payload['error'] == 'blocked'
        assert payload['action'] == 'block'
        assert payload['challenge_url'] is None
        assert payload['reason'] == 'blacklisted'

    def test_blocked_default_reason_omitted(self):
        assert 'reason' not in blocked_payload('blocked')

    def test_no_store(self):
        headers = no_store_headers()
        assert 'no-store' in headers['Cache-Control']
        assert headers['Pragma'] == 'no-cache'
        # возвращается копия: изменили — не задели константу
        headers['Cache-Control'] = 'public'
        assert 'no-store' in no_store_headers()['Cache-Control']
