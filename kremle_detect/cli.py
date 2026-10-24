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

    # Вопросы из «Решу ЕГЭ»
    kremle-detect questions sync  --limit 60
    kremle-detect questions check 1001     # проверить одно задание (и картинки)
    kremle-detect questions cache          # состояние кеша

    # Логи событий (detect / shadow / pass / fail / blocked)
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


def cmd_serve(args):
    """Демо-сервер одной командой: `kremle-detect serve`."""
    from .demo import main as run_demo

    run_demo(host=args.host, port=args.port,
             questions_images=True if args.images else None,
             sample_image=True if args.sample_image else None)


def cmd_help(args):
    text = """\
kremle-detect — управление KremleDetect из командной строки

ДИАГНОСТИКА
  kremle-detect check-ua   "<User-Agent>"     Проверить User-Agent строку
  kremle-detect check-ref  "<URL>"            Проверить Referer URL
  kremle-detect check-hints "<Sec-CH-UA>"     Проверить Client Hints заголовок
  kremle-detect questions  [-c <кат>] [-n N]  Показать вопросы из банка
  kremle-detect questions sync [-c <кат>] [-n N] [--ids 1001,1002] [--dry-run]
                               [--images] [--download]  Скачать вопросы «Решу ЕГЭ»
  kremle-detect questions check <id> [--images] [--download]
                                             Проверить одно задание и его картинки
  kremle-detect questions cache              Состояние кеша вопросов
  kremle-detect questions images [--prune <МиБ>|--clear]
                                             Кеш рисунков: размер и чистка

БЛОКЛИСТ
  kremle-detect blacklist list    [--redis URL]           Все заблокированные IP
  kremle-detect blacklist add     <IP> [--ttl N]          Заблокировать IP
  kremle-detect blacklist remove  <IP>                    Разблокировать IP

ВАЙТЛИСТ
  kremle-detect whitelist list    [--redis URL]           Все разрешённые IP
  kremle-detect whitelist add     <IP>                    Добавить в вайтлист
  kremle-detect whitelist remove  <IP>                    Убрать из вайтлиста

ДЕМО
  kremle-detect serve [--port 8000]          Демо-сайт + капча + /stats в браузере
  kremle-detect serve --images               ... с заданиями, у которых есть рисунок
  kremle-detect serve --sample-image         ... с одним встроенным рисунком (без сети)

ЛОГИ
  kremle-detect logs  [-n N] [--no-color]     Последние N событий (по умолч. 50)
    Типы событий: ПРОШЁЛ | ПРОВАЛ | ДЕТЕКТ | ТЕНЬ (monitor) | ЗАБЛОК

Redis URL указывается через флаг или переменную окружения:
  --redis redis://localhost:6379/0
  KREMLE_REDIS_URL=redis://localhost:6379/0 kremle-detect logs

Для справки по конкретной команде: kremle-detect <команда> --help
"""
    print(text.rstrip())


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
            ttl_of = getattr(storage, 'ttl', None)
            for ip in sorted(ips):
                suffix = ''
                remaining = ttl_of(f'blacklist:{ip}') if callable(ttl_of) else None
                if remaining == 0:
                    suffix = '  (навсегда)'
                elif remaining:
                    suffix = f'  (осталось {_human_ttl(remaining)})'
                print(f'  {ip}{suffix}')
    elif args.bl_action == 'add':
        # 0 — осознанный «навсегда», поэтому проверяем именно на None
        ttl = args.ttl if args.ttl is not None else 86400
        storage.blacklist_add(args.ip, ttl)
        print(f'Добавлено в блоклист: {args.ip} (TTL {ttl if ttl else "навсегда"})')
    elif args.bl_action == 'remove':
        existed = storage.blacklist_check(args.ip)
        storage.blacklist_remove(args.ip)
        if existed:
            print(f'Удалено из блоклиста: {args.ip}')
        else:
            print(f'IP не найден в блоклисте: {args.ip}', file=sys.stderr)
            sys.exit(1)


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
        existed = storage.whitelist_check(args.ip)
        storage.whitelist_remove(args.ip)
        if existed:
            print(f'Удалено из вайтлиста: {args.ip}')
        else:
            print(f'IP не найден в вайтлисте: {args.ip}', file=sys.stderr)
            sys.exit(1)


def _human_ttl(seconds: int) -> str:
    """«3600» → «1 ч», «86400» → «1 дн.». Мелочь, но читать логи/списки проще."""
    if seconds < 60:
        return f'{seconds} с'
    if seconds < 3600:
        return f'{seconds // 60} мин.'
    if seconds < 86400:
        return f'{seconds // 3600} ч'
    return f'{seconds // 86400} дн.'


_EVENT_LABELS = {
    'pass':     'ПРОШЁЛ  ',
    'fail':     'ПРОВАЛ  ',
    'detect':   'ДЕТЕКТ  ',
    'shadow':   'ТЕНЬ    ',
    'blocked':  'ЗАБЛОК  ',
}

_EVENT_COLORS = {
    'pass':    '\033[32m',   # зелёный
    'fail':    '\033[31m',   # красный
    'detect':  '\033[33m',   # жёлтый
    'shadow':  '\033[36m',   # голубой — monitor-режим
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
        elif event in ('detect', 'shadow'):
            extra = f"  причина: {ev.get('reason', '?')}"
            if ev.get('action'):
                extra += f"  действие: {ev['action']}"
        elif event == 'blocked':
            extra = f"  причина: {ev.get('reason', '?')}"

        print(f'{dt}  {label}  {ip}{extra}')


def cmd_questions(args):
    from .questions import get_questions

    # Подкоманда `questions show` и старый `questions --count 5` одновременно
    category = getattr(args, 'category', None) or getattr(args, 'legacy_category', None)
    count = getattr(args, 'count', None)
    if count is None:
        count = getattr(args, 'legacy_count', None) or 5
    no_shuffle = getattr(args, 'no_shuffle', False) or getattr(args, 'legacy_no_shuffle', False)
    source = getattr(args, 'source', None) or getattr(args, 'legacy_source', None) or 'auto'

    cats = [category] if category else None
    qs = get_questions(categories=cats, count=count, shuffle=not no_shuffle, source=source)
    if not qs:
        print('Вопросов нет. Для загрузки из «Решу ЕГЭ»: kremle-detect questions sync',
              file=sys.stderr)
        sys.exit(1)

    for i, q in enumerate(qs):
        cat = q.get('category', '')
        src = (q.get('source') or {}).get('name')
        suffix = f' · {src}' if src else ''
        print(f'\n[{i+1}] [{cat}{suffix}] {q["q"]}')
        for j, opt in enumerate(q['opts']):
            marker = '✓' if j == q['ans'] else ' '
            print(f'  {marker} {j}. {opt}')


def cmd_questions_sync(args):
    from .questions.sdamgia import SUBJECTS, sync

    cats = [args.category] if args.category else list(SUBJECTS.keys())
    ids = [i.strip() for i in (getattr(args, 'ids', None) or '').split(',') if i.strip()]

    print(f'Скачиваю вопросы: {", ".join(cats)} (до {args.limit} на категорию)...')
    if ids:
        print(f'  задания: {", ".join(ids)}')
    if args.dry_run:
        from .questions.sdamgia import fetch_questions
        for cat in cats:
            questions = fetch_questions(
                cat, limit=args.limit, problem_ids=ids or None,
                allow_images=args.images,
            )
            print(f'  {cat}: {len(questions)} вопрос(ов) — кеш не записан (--dry-run)')
        return

    result = sync(cats, limit=args.limit, cache_dir=args.cache_dir,
                  problem_ids=ids or None, allow_images=args.images or args.download)
    if not result:
        print('Ничего не скачано. Проверьте сеть и доступность sdamgia.ru.', file=sys.stderr)
        sys.exit(1)
    for cat, count in result.items():
        print(f'  {cat}: {count} вопрос(ов) записано в кеш')

    if args.download:
        _download_images(cats, args.cache_dir, args)

    print('Готово. Вопросы будут использоваться автоматически (questions_source="auto").')
    if not args.download:
        print('Рисунки остаются горячими ссылками на портал. '
              'Локальный кеш: kremle-detect questions sync --images --download')


def _download_images(cats, cache_dir, args) -> None:
    """Скачивает картинки вопросов из кеша в локальный кеш картинок."""
    from .images import cache_questions, stats
    from .questions.sdamgia import read_cache

    questions = []
    for cat in cats:
        data = read_cache(cat, cache_dir)
        if data:
            questions.extend(data.get('questions') or [])

    total = sum(1 for _ in questions)
    print(f'Скачиваю рисунки ({total} задани(й) в кеше)...')
    result = cache_questions(questions, cache_dir=cache_dir, force=args.force_images)
    cached, skipped = result['cached'], result['skipped']
    print(f'  скачано: {cached}, уже было: {skipped}, ошибок: {len(result["failed"])}')
    for failure in result['failed'][:10]:
        print(f'  ! {failure["url"]}: {failure["error"]}', file=sys.stderr)
    if len(result['failed']) > 10:
        print(f'  ! … и ещё {len(result["failed"]) - 10} ошибок', file=sys.stderr)

    info = stats(cache_dir)
    print(f'Кеш рисунков: {info["count"]} файл(ов), {info["bytes"] / 1024:.0f} КиБ '
          f'({info["dir"]})')
    if result['failed']:
        print('Неудачные рисунки останутся горячими ссылками на портал '
              '— это не ломает капчу.', file=sys.stderr)


def cmd_questions_check(args):
    """
    Проверка одного задания портала: скачать, разобрать, показать картинки.

    Самая простая проверка «а что придёт с „Решу ЕГЭ“»: одна команда, один id.
    """
    from .questions.sdamgia import (
        BASE_URLS, SUBJECTS, build_question, http_get, parse_problem_html,
    )

    category = args.category or 'math'
    base_url = BASE_URLS[SUBJECTS[category]]
    url = f'{base_url}/problem?id={args.problem_id}'
    if not args.json:
        print(f'GET {url}')

    try:
        html = http_get(url)
    except Exception as exc:  # noqa: BLE001 — CLI не должен падать трейсбеком
        print(f'Не удалось скачать: {exc}', file=sys.stderr)
        print('Проверьте сеть/прокси: портал доступен не из каждой сети.', file=sys.stderr)
        sys.exit(1)

    parsed = parse_problem_html(html, base_url=base_url)
    if not parsed:
        print('Страница скачалась, но условие/ответ не разобрались.', file=sys.stderr)
        print('Скорее всего портал сменил вёрстку — см. prompts в sdamgia.py.', file=sys.stderr)
        sys.exit(2)

    images = parsed.get('images') or []
    question = build_question(
        parsed, category, args.problem_id, base_url,
        allow_images=args.images or args.download,
    )

    downloaded = []
    if args.download and images:
        from .images import download_image, ImageError, image_key, local_url

        for image in images:
            try:
                stored = download_image(image['url'])
            except ImageError as exc:
                downloaded.append({'url': image['url'], 'ok': False, 'error': str(exc)})
                continue
            downloaded.append({
                'url': image['url'], 'ok': True, 'key': stored['key'],
                'size': stored['size'], 'content_type': stored['content_type'],
                'local': local_url(image_key(image['url'])),
            })

    if args.json:
        print(json.dumps({
            'problem_id': args.problem_id,
            'category': category,
            'url': url,
            'condition': parsed['condition'],
            'answer': parsed['answer'],
            'images': images,
            'images_cached': downloaded or None,
            'usable': question is not None,
            'question': question,
        }, ensure_ascii=False, indent=2))
        return

    print()
    print(f'Условие: {parsed["condition"]}')
    print(f'Ответ:   {parsed["answer"]}')
    print(f'Картинок в условии: {len(images)}')
    for image in images:
        print(f'  - {image["url"]}' + (f'  (alt: {image["alt"]})' if image['alt'] else ''))
    if downloaded:
        print('  В локальном кеше:')
        for item in downloaded:
            if item['ok']:
                print(f'    + {item["local"]}  ({item["size"] / 1024:.0f} КиБ)')
            else:
                print(f'    ! {item["url"]}: {item["error"]}')
    print()

    if question is None:
        if images and not args.images:
            print('В капчу НЕ пойдёт: есть картинка, а --images не указан.')
            print('Проверить как пригодное: kremle-detect questions check %s --images'
                  % args.problem_id)
        elif not str(parsed['answer']).strip():
            print('В капчу НЕ пойдёт: нет ответа.')
        else:
            print('В капчу НЕ пойдёт: ответ не числовой или условие слишком длинное.')
        sys.exit(3)

    print('В капчу пойдёт. Варианты:')
    for j, opt in enumerate(question['opts']):
        marker = '✓' if j == question['ans'] else ' '
        print(f'  {marker} {j}. {opt}')
    if images and not args.images:
        print()
        print('Внимание: в кеш такое задание попадёт только с `questions sync --images`.')


def cmd_questions_images(args):
    """
    Кеш рисунков: размер, чистка по возрасту, полное удаление.

    Рисунки копятся без срока жизни (задание могло исчезнуть с портала),
    поэтому место возвращаем вручную.
    """
    from .images import clear, prune, stats

    if args.clear:
        removed = clear(args.cache_dir)
        print(f'Кеш рисунков очищен: удалено {removed} файл(ов).')
        return

    if args.prune is not None:
        limit = int(args.prune * 1024 * 1024)
        result = prune(limit, args.cache_dir)
        if not result['removed']:
            print(f'Чистить нечего: {result["bytes"] / 1024:.0f} КиБ — это в пределах '
                  f'{args.prune:g} МиБ.')
            return
        print(f'Удалено {result["removed"]} старых рисунков '
              f'({result["freed"] / 1024:.0f} КиБ).')
        print(f'Осталось: {result["count"]} файл(ов), {result["bytes"] / 1024:.0f} КиБ.')
        return

    info = stats(args.cache_dir)
    print(f'Кеш рисунков ({info["dir"]}):')
    if not info['count']:
        print('  пусто — скачать: kremle-detect questions sync --images --download')
        return
    print(f'  {info["count"]} файл(ов), {info["bytes"] / 1024:.0f} КиБ')


def cmd_questions_cache(args):
    from .questions.sdamgia import SUBJECTS, cache_age, cache_path, read_cache

    rows = []
    for cat in SUBJECTS:
        data = read_cache(cat, args.cache_dir)
        if not data:
            rows.append((cat, 0, None, cache_path(cat, args.cache_dir)))
            continue
        rows.append((cat, len(data['questions']), cache_age(cat, args.cache_dir),
                     cache_path(cat, args.cache_dir)))

    print(f'Кеш вопросов «Решу ЕГЭ» ({rows[0][3].rsplit("/", 1)[0] if rows else "-"}):')
    for cat, count, age, path in rows:
        if not count:
            print(f'  {cat:11} — пусто')
            continue
        age_text = 'только что' if age is not None and age < 60 else (
            f'{age / 86400:.1f} дн.' if age else '?'
        )
        print(f'  {cat:11} {count:4} вопрос(ов), обновлён {age_text}')
    from .images import stats as image_stats

    info = image_stats(args.cache_dir)
    if info['count']:
        print(f'  рисунки     {info["count"]:4} файл(ов), {info["bytes"] / 1024:.0f} КиБ')
    else:
        print('  рисунки     — пусто (kremle-detect questions sync --images --download)')
    print('\nОбновить: kremle-detect questions sync')


def main():
    from . import __version__

    parser = argparse.ArgumentParser(
        prog='kremle-detect',
        description='Утилита для диагностики детекции Яндекс-пользователей.',
    )
    parser.add_argument('--version', action='version',
                        version=f'kremle-detect {__version__}')
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
    q_sub = p_q.add_subparsers(dest='q_action')

    q_show = q_sub.add_parser('show', help='Показать вопросы (по умолчанию)')
    q_show.add_argument('--category', '-c',
                        choices=['math', 'physics', 'russian', 'literature'],
                        help='Категория вопросов')
    q_show.add_argument('--count', '-n', type=int, default=5,
                        help='Количество вопросов (по умолч. 5)')
    q_show.add_argument('--no-shuffle', action='store_true', help='Не перемешивать')
    q_show.add_argument('--source', choices=['auto', 'builtin', 'sdamgia'], default='auto',
                        help='Источник вопросов (по умолч. auto)')
    q_show.set_defaults(func=cmd_questions)

    q_sync = q_sub.add_parser('sync', help='Скачать вопросы «Решу ЕГЭ» в кеш')
    q_sync.add_argument('--category', '-c',
                        choices=['math', 'physics', 'russian', 'literature'],
                        help='Только одна категория (по умолч. все)')
    q_sync.add_argument('--limit', '-n', type=int, default=60,
                        help='Сколько вопросов на категорию (по умолч. 60)')
    q_sync.add_argument('--cache-dir', metavar='PATH', help='Каталог кеша')
    q_sync.add_argument('--ids', metavar='ID[,ID...]',
                        help='Конкретные id заданий вместо поиска по каталогу')
    q_sync.add_argument('--images', action='store_true',
                        help='Сохранять задания с рисунком (картинки грузятся с портала)')
    q_sync.add_argument('--download', action='store_true',
                        help='Скачать рисунки заданий в локальный кеш (включает --images)')
    q_sync.add_argument('--force-images', action='store_true',
                        help='Перекачать рисунки, даже если они уже в кеше')
    q_sync.add_argument('--dry-run', action='store_true', help='Скачать, но не записывать')
    q_sync.set_defaults(func=cmd_questions_sync)

    q_check = q_sub.add_parser('check', help='Проверить одно задание портала (и картинки)')
    q_check.add_argument('problem_id', help='id задания, например 1001')
    q_check.add_argument('--category', '-c',
                         choices=['math', 'physics', 'russian', 'literature'],
                         default='math', help='Предмет (по умолч. math)')
    q_check.add_argument('--images', action='store_true',
                         help='Учитывать задания с картинкой как пригодные')
    q_check.add_argument('--download', action='store_true',
                         help='Скачать рисунки задания в локальный кеш (включает --images)')
    q_check.add_argument('--json', action='store_true', help='Вывод в JSON')
    q_check.set_defaults(func=cmd_questions_check)

    q_cache = q_sub.add_parser('cache', help='Состояние кеша вопросов')
    q_cache.add_argument('--cache-dir', metavar='PATH', help='Каталог кеша')

    q_images = q_sub.add_parser('images', help='Кеш рисунков: размер и чистка')
    q_images.add_argument('--cache-dir', metavar='PATH', help='Каталог кеша')
    q_images_group = q_images.add_mutually_exclusive_group()
    q_images_group.add_argument('--prune', type=float, metavar='МИБ',
                                help='Удалить самые старые рисунки, пока кеш не станет '
                                     'не больше указанного размера')
    q_images_group.add_argument('--clear', action='store_true',
                                help='Удалить все рисунки из кеша')
    q_cache.set_defaults(func=cmd_questions_cache)
    q_images.set_defaults(func=cmd_questions_images)

    # обратная совместимость: kremle-detect questions --count 5
    p_q.add_argument('--category', '-c', dest='legacy_category',
                     choices=['math', 'physics', 'russian', 'literature'],
                     help=argparse.SUPPRESS)
    p_q.add_argument('--count', '-n', type=int, dest='legacy_count',
                     help=argparse.SUPPRESS)
    p_q.add_argument('--no-shuffle', action='store_true', dest='legacy_no_shuffle',
                     help=argparse.SUPPRESS)
    p_q.add_argument('--source', dest='legacy_source', choices=['auto', 'builtin', 'sdamgia'],
                     help=argparse.SUPPRESS)
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
    bl_add.add_argument('--ttl', type=int, default=None,
                        help='Время бана в секундах (по умолч. 86400 = 1 день, 0 = навсегда)')
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

    # help
    p_serve = sub.add_parser('serve', help='Запустить демо-сервер (FastAPI + капча)')
    p_serve.add_argument('--host', default='0.0.0.0', help='Адрес (по умолч. 0.0.0.0)')
    p_serve.add_argument('--port', '-p', type=int, default=None,
                         help='Порт (по умолч. 8000 или $KREMLE_DEMO_PORT)')
    p_serve.add_argument('--images', action='store_true',
                         help='Показывать задания с рисунком (кеш «Решу ЕГЭ»)')
    p_serve.add_argument('--sample-image', action='store_true',
                         help='Одно встроенное задание с рисунком (SVG, без сети)')
    p_serve.set_defaults(func=cmd_serve)

    p_help = sub.add_parser('help', help='Показать справку по всем командам')
    p_help.set_defaults(func=cmd_help)

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
