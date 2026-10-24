# -*- coding: utf-8 -*-
"""
Резолвинг IP клиента и проверка IP-списков.

Главное правило: ``X-Forwarded-For`` доверяем только если запрос пришёл
от доверенного прокси (``trusted_proxies``). Иначе любой клиент может
подставить произвольный IP и обойти rate limit / подставить чужой адрес
в блоклист.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable, List, Optional, Sequence, Union

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


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


def _is_trusted(addr, nets: Sequence[IPNetwork]) -> bool:
    return any(addr in net for net in nets)


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

    Поведение:
        * ``peer`` не от доверенного прокси → возвращается ``peer``,
          ``X-Forwarded-For`` игнорируется (защита от подделки).
        * ``peer`` доверенный → цепочка XFF читается справа налево,
          доверенные хопы пропускаются, возвращается первый недоверенный.
        * мусор в XFF → возвращается ``peer``.

    Пример:
        client_ip('10.0.0.5', '203.0.113.7, 10.0.0.5', ['10.0.0.0/8'])
        # → '203.0.113.7'
    """
    peer_addr = _parse_ip(peer)
    if peer_addr is None:
        return (peer or '').strip()

    nets = parse_trusted_proxies(trusted_proxies)
    if not nets or not _is_trusted(peer_addr, nets):
        return str(peer_addr)

    if not xff:
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
