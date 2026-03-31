# -*- coding: utf-8 -*-
"""
CLI для kremle-detect.

Использование:
    kremle-detect check-ua "Mozilla/5.0 YaBrowser/24.1"
    kremle-detect check-ref "https://yandex.ru/search?q=test"
    kremle-detect check-hints '"YaBrowser";v="24"'
    kremle-detect questions --category math --count 3
"""

from __future__ import annotations

import argparse
import json
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

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
