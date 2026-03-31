# -*- coding: utf-8 -*-
"""
CLI для kremle-detect.

Использование:
    kremle-detect check-ua "Mozilla/5.0 YaBrowser/24.1"
    kremle-detect check-ref "https://yandex.ru/search?q=test"
    kremle-detect check-hints '"YaBrowser";v="24"'
    kremle-detect questions --category math --count 3

    # Управление блоклистом (Redis)
    kremle-detect blacklist list   --redis redis://localhost:6379/0
    kremle-detect blacklist add    1.2.3.4 --redis redis://localhost:6379/0
    kremle-detect blacklist remove 1.2.3.4 --redis redis://localhost:6379/0

    # Управление вайтлистом (Redis)
    kremle-detect whitelist list
    kremle-detect whitelist add    1.2.3.4
    kremle-detect whitelist remove 1.2.3.4

    # Логи событий (detect / pass / fail / blocked)
    kremle-detect logs --redis redis://localhost:6379/0
    kremle-detect logs -n 100

    # Переменная окружения вместо флага --redis:
    KREMLE_REDIS_URL=redis://localhost:6379/0 kremle-detect logs
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def cmd_check_ua(args):
    from .detector import detect

    result = detect({'User-Agent': args.value})
    _print_result(result, 'User-Agent', args.value)


def cmd_check_ref(args):
    from .detector import detect

    result = detect({'Referer': args.value})
    _print_result(result, 'Referer', args.value)


def cmd_check_hints(args):
    from .detector import detect

    result = detect({'Sec-CH-UA': args.value})
    _print_result(result, 'Sec-CH-UA', args.value)


def _print_result(result, field, value):
    status = 'DETECTED' if result.detected else 'clean'
    print(f'{field}: {value[:80]}')
    print(f'Result:  {status}')
    if result.detected:
        print(f'Reason:  {result.reason}')
        signals = []
        if result.browser:       signals.append('browser')
        if result.bot:           signals.append('bot')
        if result.referrer:      signals.append('referrer')
        if result.client_hints:  signals.append('client_hints')
        print(f'Signals: {", ".join(signals)}')
        sys.exit(1)


def _get_storage(args):
    """Создаёт RedisStorage из --redis флага или KREMLE_REDIS_URL env."""
    from .storage import RedisStorage, MemoryStorage
    url = getattr(args, 'redis', None) or os.environ.get('KREMLE_REDIS_URL')
    if url:
        return RedisStorage(url=url)
    # Fallback: MemoryStorage (только для текущего процесса — полезно для тестов)
    print('Предупреждение: --redis не указан, используется MemoryStorage (данные не сохранятся между запусками).',
          file=sys.stderr)
    return MemoryStorage()


def cmd_blacklist(args):
    storage = _get_storage(args)
    if args.bl_action == 'list':
        ips = storage.blacklist_list()
        if not ips:
            print('Блоклист пуст.')
        else:
            print(f'Заблокировано IP ({len(ips)}):')
            for ip in sorted(ips):
                print(f'  {ip}')
    elif args.bl_action == 'add':
        ttl = args.ttl if args.ttl else 86400
        storage.blacklist_add(args.ip, ttl)
        print(f'Добавлено в блоклист: {args.ip} (TTL {ttl}с)')
    elif args.bl_action == 'remove':
        storage.blacklist_remove(args.ip)
        print(f'Удалено из блоклиста: {args.ip}')


def cmd_whitelist(args):
    storage = _get_storage(args)
    if args.wl_action == 'list':
        ips = storage.whitelist_list()
        if not ips:
            print('Вайтлист пуст.')
        else:
            print(f'Разрешённые IP ({len(ips)}):')
            for ip in sorted(ips):
                print(f'  {ip}')
    elif args.wl_action == 'add':
        storage.whitelist_add(args.ip)
        print(f'Добавлено в вайтлист: {args.ip}')
    elif args.wl_action == 'remove':
        storage.whitelist_remove(args.ip)
        print(f'Удалено из вайтлиста: {args.ip}')


_EVENT_LABELS = {
    'pass':     'ПРОШЁЛ  ',
    'fail':     'ПРОВАЛ  ',
    'detect':   'ДЕТЕКТ  ',
    'blocked':  'ЗАБЛОК  ',
}

_EVENT_COLORS = {
    'pass':    '\033[32m',   # зелёный
    'fail':    '\033[31m',   # красный
    'detect':  '\033[33m',   # жёлтый
    'blocked': '\033[35m',   # пурпурный
}
_RESET = '\033[0m'


def cmd_logs(args):
    import datetime
    storage = _get_storage(args)
    events = storage.log_get(args.n)
    if not events:
        print('Событий нет.')
        return

    use_color = sys.stdout.isatty() and not args.no_color
    for ev in events:
        ts = ev.get('ts', 0)
        dt = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        event = ev.get('event', '?')
        ip = ev.get('ip') or '-'
        label = _EVENT_LABELS.get(event, event.upper().ljust(8))

        if use_color:
            color = _EVENT_COLORS.get(event, '')
            label = f'{color}{label}{_RESET}'

        extra = ''
        if event in ('pass', 'fail'):
            extra = f"  ошибок: {ev.get('errors', '?')}/{ev.get('total', '?')}"
        elif event == 'detect':
            extra = f"  причина: {ev.get('reason', '?')}"
        elif event == 'blocked':
            extra = f"  причина: {ev.get('reason', '?')}"

        print(f'{dt}  {label}  {ip}{extra}')


def cmd_questions(args):
    from .questions import get_questions

    cats = [args.category] if args.category else None
    qs = get_questions(categories=cats, count=args.count, shuffle=not args.no_shuffle)

    for i, q in enumerate(qs):
        cat = q.get('category', '')
        print(f'\n[{i+1}] [{cat}] {q["q"]}')
        for j, opt in enumerate(q['opts']):
            marker = '✓' if j == q['ans'] else ' '
            print(f'  {marker} {j}. {opt}')


def main():
    parser = argparse.ArgumentParser(
        prog='kremle-detect',
        description='Утилита для диагностики детекции Яндекс-пользователей.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # check-ua
    p_ua = sub.add_parser('check-ua', help='Проверить User-Agent строку')
    p_ua.add_argument('value', help='User-Agent строка')
    p_ua.set_defaults(func=cmd_check_ua)

    # check-ref
    p_ref = sub.add_parser('check-ref', help='Проверить Referer URL')
    p_ref.add_argument('value', help='Referer URL')
    p_ref.set_defaults(func=cmd_check_ref)

    # check-hints
    p_hints = sub.add_parser('check-hints', help='Проверить Sec-CH-UA заголовок')
    p_hints.add_argument('value', help='Значение Sec-CH-UA')
    p_hints.set_defaults(func=cmd_check_hints)

    # questions
    p_q = sub.add_parser('questions', help='Показать вопросы из банка')
    p_q.add_argument('--category', '-c',
                     choices=['math', 'physics', 'russian', 'literature'],
                     help='Категория вопросов')
    p_q.add_argument('--count', '-n', type=int, default=5, help='Количество вопросов (по умолч. 5)')
    p_q.add_argument('--no-shuffle', action='store_true', help='Не перемешивать')
    p_q.set_defaults(func=cmd_questions)

    _REDIS_HELP = 'Redis URL (или env KREMLE_REDIS_URL)'

    # blacklist
    p_bl = sub.add_parser('blacklist', help='Управление блоклистом IP')
    bl_sub = p_bl.add_subparsers(dest='bl_action', required=True)

    bl_list = bl_sub.add_parser('list', help='Показать все заблокированные IP')
    bl_list.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    bl_list.set_defaults(func=cmd_blacklist)

    bl_add = bl_sub.add_parser('add', help='Добавить IP в блоклист')
    bl_add.add_argument('ip', help='IP-адрес')
    bl_add.add_argument('--ttl', type=int, default=86400,
                        help='Время бана в секундах (по умолч. 86400 = 1 день)')
    bl_add.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    bl_add.set_defaults(func=cmd_blacklist)

    bl_rm = bl_sub.add_parser('remove', help='Удалить IP из блоклиста')
    bl_rm.add_argument('ip', help='IP-адрес')
    bl_rm.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    bl_rm.set_defaults(func=cmd_blacklist)

    # whitelist
    p_wl = sub.add_parser('whitelist', help='Управление вайтлистом IP')
    wl_sub = p_wl.add_subparsers(dest='wl_action', required=True)

    wl_list = wl_sub.add_parser('list', help='Показать все разрешённые IP')
    wl_list.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    wl_list.set_defaults(func=cmd_whitelist)

    wl_add = wl_sub.add_parser('add', help='Добавить IP в вайтлист')
    wl_add.add_argument('ip', help='IP-адрес')
    wl_add.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    wl_add.set_defaults(func=cmd_whitelist)

    wl_rm = wl_sub.add_parser('remove', help='Удалить IP из вайтлиста')
    wl_rm.add_argument('ip', help='IP-адрес')
    wl_rm.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    wl_rm.set_defaults(func=cmd_whitelist)

    # logs
    p_logs = sub.add_parser('logs', help='Показать последние события (detect/pass/fail)')
    p_logs.add_argument('--redis', metavar='URL', help=_REDIS_HELP)
    p_logs.add_argument('-n', type=int, default=50, help='Количество событий (по умолч. 50)')
    p_logs.add_argument('--no-color', action='store_true', help='Без цветового выделения')
    p_logs.set_defaults(func=cmd_logs)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
