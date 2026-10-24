# -*- coding: utf-8 -*-
"""
Резолвинг IP клиента и проверка IP-списков.

Главное правило: ``X-Forwarded-For`` доверяем только если запрос пришёл
от доверенного прокси. Иначе любой клиент может подставить произвольный IP
и обойти rate limit / подставить чужой адрес в блоклист.

Доверенные прокси по умолчанию — локальные и приватные сети: nginx на том же
хосте, docker/k8s-сеть, внутренний балансировщик. Это покрывает типовой деплой
без настройки. Публичный балансировщик (Cloudflare, облачный LB) нужно указать
явно.
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence, Union

logger = logging.getLogger('kremle')

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# Кому доверяем X-Forwarded-For, если trusted_proxies не задан явно.
DEFAULT_TRUSTED_NETWORKS: tuple = (
    '127.0.0.0/8',      # loopback
    '::1/128',
    '10.0.0.0/8',       # приватные сети
    '172.16.0.0/12',
    '192.168.0.0/16',
    '169.254.0.0/16',   # link-local
    'fc00::/7',         # IPv6 ULA
    'fe80::/10',        # IPv6 link-local
)

# Чтобы предупреждение о недоверенном прокси не превратилось в лог-шторм.
_warned_peers: set = set()
_WARNED_PEERS_MAX = 8


def _parse_ip(value: Optional[str]):
    """ip_address или None."""
    if value is None:
        return None
    try:
        return ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None


def parse_trusted_proxies(entries: Optional[Iterable[str]]) -> tuple:
    """
    Превращает список IP/CIDR в кортеж ip_network. Некорректные записи
    молча пропускаются (как и в whitelist).

    Пример:
        parse_trusted_proxies(['127.0.0.1', '10.0.0.0/8'])
    """
    nets: List[IPNetwork] = []
    for entry in entries or ():
        try:
            nets.append(ipaddress.ip_network(str(entry).strip(), strict=False))
        except ValueError:
            continue
    return tuple(nets)


@lru_cache(maxsize=32)
def _parse_cached(entries: tuple) -> tuple:
    """Кеш разбора: список прокси не меняется от запроса к запросу."""
    return parse_trusted_proxies(entries)


def resolve_trusted_proxies(
    entries: Optional[Iterable[str]] = None,
) -> tuple:
    """
    Итоговый список доверенных прокси.

    * ``None`` — режим по умолчанию: loopback + приватные сети;
    * пустой список — не доверять никому (XFF игнорируется полностью);
    * список IP/CIDR — только он.

    Пример:
        resolve_trusted_proxies()                 # DEFAULT_TRUSTED_NETWORKS
        resolve_trusted_proxies([])               # никому
        resolve_trusted_proxies(['203.0.113.10']) # только внешнему LB
    """
    if entries is None:
        return _DEFAULT_NETS
    if isinstance(entries, str):  # одна строка вместо списка — не разбираем по буквам
        entries = (entries,)
    return _parse_cached(tuple(entries))


_DEFAULT_NETS = parse_trusted_proxies(DEFAULT_TRUSTED_NETWORKS)


def _is_trusted(addr, nets: Sequence[IPNetwork]) -> bool:
    return any(addr in net for net in nets)


def _warn_untrusted(peer: str) -> None:
    if peer in _warned_peers or len(_warned_peers) >= _WARNED_PEERS_MAX:
        return
    _warned_peers.add(peer)
    logger.warning(
        'X-Forwarded-For пришёл от недоверенного адреса %s — заголовок игнорируется. '
        'Если это ваш прокси/CDN, добавьте его в trusted_proxies '
        '(Django: KREMLE_TRUSTED_PROXIES).',
        peer,
    )


def client_ip(
    peer: Optional[str],
    xff: Optional[str] = None,
    trusted_proxies: Optional[Iterable[str]] = None,
) -> str:
    """
    Возвращает настоящий IP клиента.

    Args:
        peer: адрес непосредственного соединения (``request.remote_addr``,
              ``request.client.host``, ``REMOTE_ADDR``).
        xff: значение заголовка ``X-Forwarded-For`` (может быть None).
        trusted_proxies: IP/CIDR прокси, которым разрешено присылать XFF.
              ``None`` (по умолчанию) — loopback и приватные сети.
              ``[]`` — не доверять никому.

    Поведение:
        * ``peer`` не от доверенного прокси → возвращается ``peer``,
          ``X-Forwarded-For`` игнорируется (защита от подделки).
        * ``peer`` доверенный → цепочка XFF читается справа налево,
          доверенные хопы пропускаются, возвращается первый недоверенный.
        * мусор в XFF → возвращается ``peer``.

    Пример:
        # nginx на том же хосте — работает без настройки
        client_ip('127.0.0.1', '203.0.113.7')                 # → '203.0.113.7'

        # внешний балансировщик указан явно
        client_ip('10.0.0.5', '203.0.113.7, 10.0.0.5', ['10.0.0.0/8'])
        # → '203.0.113.7'

        # публичный клиент подделывает заголовок — не верим
        client_ip('198.51.100.9', '203.0.113.7')              # → '198.51.100.9'
    """
    peer_str = (peer or '').strip()

    # Без X-Forwarded-For резолвить нечего: не тратим разбор IP на каждом
    # обычном запросе (это самый частый путь).
    if not xff:
        return peer_str

    peer_addr = _parse_ip(peer)
    if peer_addr is None:
        return peer_str

    nets = resolve_trusted_proxies(trusted_proxies)
    if not _is_trusted(peer_addr, nets):
        _warn_untrusted(str(peer_addr))
        return str(peer_addr)

    hops = [h.strip() for h in str(xff).split(',') if h.strip()]
    result = peer_addr
    for hop in reversed(hops):
        addr = _parse_ip(hop)
        if addr is None:
            # Цепочке с мусором доверять нельзя — возвращаем прямой peer.
            return str(peer_addr)
        result = addr
        if not _is_trusted(addr, nets):
            return str(addr)
    return str(result)


def ip_matches(ip: str, entries: Optional[Iterable[str]]) -> bool:
    """
    True если ``ip`` есть в списке IP/CIDR ``entries``.

    Пример:
        ip_matches('10.1.2.3', ['10.0.0.0/8'])  # → True
    """
    addr = _parse_ip(ip)
    if addr is None:
        return False
    for entry in entries or ():
        try:
            if '/' in str(entry):
                if addr in ipaddress.ip_network(str(entry), strict=False):
                    return True
            elif addr == ipaddress.ip_address(str(entry)):
                return True
        except ValueError:
            continue
    return False
