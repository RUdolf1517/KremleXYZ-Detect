# -*- coding: utf-8 -*-
"""Тесты резолвинга IP и проверки IP-списков."""

import pytest

from kremle_detect.ip import (
    DEFAULT_TRUSTED_NETWORKS,
    client_ip,
    ip_matches,
    parse_trusted_proxies,
    resolve_trusted_proxies,
)


class TestClientIp:
    def test_no_xff(self):
        assert client_ip('203.0.113.5') == '203.0.113.5'

    def test_public_peer_cannot_spoof_xff(self):
        """Публичный клиент не может подставить себе IP через XFF (по умолчанию)."""
        assert client_ip('203.0.113.5', '1.2.3.4') == '203.0.113.5'

    def test_loopback_proxy_trusted_by_default(self):
        """nginx на том же хосте работает без настройки."""
        assert client_ip('127.0.0.1', '203.0.113.7') == '203.0.113.7'

    def test_private_proxy_trusted_by_default(self):
        assert client_ip('10.0.0.5', '203.0.113.7') == '203.0.113.7'
        assert client_ip('192.168.1.10', '203.0.113.7') == '203.0.113.7'
        assert client_ip('172.16.0.2', '203.0.113.7') == '203.0.113.7'

    def test_explicit_empty_list_disables_trust(self):
        assert client_ip('127.0.0.1', '203.0.113.7', trusted_proxies=[]) == '127.0.0.1'

    def test_explicit_public_proxy(self):
        """Внешний балансировщик указывается явно и заменяет авто-список."""
        assert client_ip(
            '203.0.113.10', '198.51.100.7', trusted_proxies=['203.0.113.10']
        ) == '198.51.100.7'
        # loopback больше не в списке — не доверяем
        assert client_ip(
            '127.0.0.1', '198.51.100.7', trusted_proxies=['203.0.113.10']
        ) == '127.0.0.1'

    def test_xff_ignored_from_untrusted_peer(self):
        assert client_ip(
            '203.0.113.5', '1.2.3.4', trusted_proxies=['10.0.0.0/8']
        ) == '203.0.113.5'

    def test_xff_honored_from_trusted_proxy(self):
        assert client_ip(
            '10.0.0.1', '198.51.100.7', trusted_proxies=['10.0.0.0/8']
        ) == '198.51.100.7'

    def test_chain_skips_trusted_hops(self):
        # Клиент → CDN (10.0.0.1) → nginx (10.0.0.2) → приложение
        xff = '198.51.100.7, 10.0.0.1'
        assert client_ip('10.0.0.2', xff, trusted_proxies=['10.0.0.0/8']) == '198.51.100.7'

    def test_all_hops_trusted(self):
        assert client_ip('10.0.0.2', '10.0.0.1', trusted_proxies=['10.0.0.0/8']) == '10.0.0.1'

    def test_garbage_xff_falls_back_to_peer(self):
        assert client_ip('10.0.0.1', 'not-an-ip', trusted_proxies=['10.0.0.0/8']) == '10.0.0.1'

    def test_garbage_hop_in_chain(self):
        xff = '198.51.100.7, garbage, 10.0.0.1'
        assert client_ip('10.0.0.2', xff, trusted_proxies=['10.0.0.0/8']) == '10.0.0.2'

    def test_empty_peer(self):
        assert client_ip('') == ''
        assert client_ip(None) == ''

    def test_non_ip_peer(self):
        # Starlette TestClient отдаёт 'testclient'
        assert client_ip('testclient', '1.2.3.4') == 'testclient'

    def test_ipv6(self):
        assert client_ip('2001:db8::1', '198.51.100.7', trusted_proxies=['2001:db8::/32']) == '198.51.100.7'


class TestResolveTrustedProxies:
    def test_none_means_defaults(self):
        nets = resolve_trusted_proxies(None)
        assert len(nets) == len(DEFAULT_TRUSTED_NETWORKS)

    def test_empty_means_nobody(self):
        assert resolve_trusted_proxies([]) == ()

    def test_explicit_list(self):
        assert len(resolve_trusted_proxies(['203.0.113.10'])) == 1


class TestTrustedProxiesParsing:
    def test_single_ip_becomes_network(self):
        nets = parse_trusted_proxies(['127.0.0.1'])
        assert len(nets) == 1

    def test_cidr(self):
        nets = parse_trusted_proxies(['10.0.0.0/8'])
        assert len(nets) == 1

    def test_invalid_ignored(self):
        assert parse_trusted_proxies(['nope', '10.0.0.0/8']) != ()
        assert parse_trusted_proxies(['nope']) == ()

    def test_none(self):
        assert parse_trusted_proxies(None) == ()


class TestIpMatches:
    @pytest.mark.parametrize('ip,entries,expected', [
        ('10.1.2.3', ['10.0.0.0/8'], True),
        ('11.1.2.3', ['10.0.0.0/8'], False),
        ('127.0.0.1', ['127.0.0.1'], True),
        ('127.0.0.2', ['127.0.0.1'], False),
        ('127.0.0.1', ['not-an-ip', '127.0.0.1'], True),
        ('127.0.0.1', [], False),
        ('', ['127.0.0.1'], False),
        ('garbage', ['0.0.0.0/0'], False),
    ])
    def test_matches(self, ip, entries, expected):
        assert ip_matches(ip, entries) is expected
