# -*- coding: utf-8 -*-
"""
Локальный кеш картинок из условий заданий.

Зачем: задания «Решу ЕГЭ» иногда содержат рисунок (график, чертёж, схему).
По умолчанию движок показывает их горячей ссылкой на портал — это работает,
пока портал отдаёт файл посторонним сайтам. Как только он этого не делает,
капча деградирует до «[рисунок не загрузился]», а условие без рисунка решить
нельзя. Плюс каждый показ такой капчи сообщает порталу IP пользователя.

Этот модуль решает обе проблемы: картинки скачиваются заранее
(``kremle-detect questions sync --images --download``) и отдаются своим
роутом ``/kremle/img/<key>`` из локального кеша.

Ключ — первые 32 hex sha256 от исходного URL, поэтому повторная синхронизация
идемпотентна: уже скачанное не перекачивается.

Кеш лежит рядом с кешем вопросов (``$KREMLE_CACHE_DIR`` или
``~/.cache/kremle-detect``), в подкаталоге ``images``:

    images/<key>        — сами байты
    images/<key>.json   — метаданные: url, content_type, size, fetched_at

Безопасность: качаем только http(s), только снаружи (внутренние адреса
отклоняются — иначе это SSRF), только ``image/*``, не больше
``MAX_IMAGE_BYTES``. Отдаём всегда с ``nosniff``, без сниффинга типа.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .questions.sdamgia import USER_AGENT, default_cache_dir

#: Префикс URL, по которому интеграции отдают картинки из кеша.
DEFAULT_PREFIX = '/kremle/img/'

#: Ключ кеша: 32 hex-символа sha256 от URL.
KEY_RE = re.compile(r'^[0-9a-f]{32}$')

#: Больше этого файл не примем — капча не должна тянуть мегабайты.
MAX_IMAGE_BYTES = 3 * 1024 * 1024

DEFAULT_TIMEOUT = 10.0

#: Сколько редиректов проходим, проверяя каждый. Портал отдаёт файлы напрямую,
#: больше двух хопов не встречается; ограничение нужно, чтобы цикл не крутился.
MAX_REDIRECTS = 3

#: Заголовки ответа роута картинок: ключ — хеш содержимого, поэтому кеш
#: «навсегда»; nosniff и sandbox — на случай SVG, который может нести скрипт.
RESPONSE_HEADERS = {
    'Cache-Control': 'public, max-age=31536000, immutable',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; sandbox",
}

#: Расширение по content-type (нужно только для удобства отладки).
CONTENT_TYPES: Dict[str, str] = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
}

#: Сигнатуры форматов — на случай, если сервер врёт про content-type.
_SIGNATURES: Tuple[Tuple[bytes, str], ...] = (
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
)

#: Fetcher: url -> (bytes, content_type). Подменяется в тестах.
Fetcher = Callable[[str], Tuple[bytes, str]]


class ImageError(Exception):
    """Картинку не удалось скачать или сохранить."""


# ── Пути и ключи ─────────────────────────────────────────────────────────────

def image_key(url: str) -> str:
    """Ключ кеша для URL: 32 hex-символа sha256."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def images_dir(cache_dir: Optional[str] = None) -> str:
    """Каталог кеша картинок (внутри общего кеша)."""
    return os.path.join(cache_dir or default_cache_dir(), 'images')


def _key_of(url_or_key: str) -> str:
    value = (url_or_key or '').strip()
    if KEY_RE.match(value):
        return value
    return image_key(value)


def _data_path(key: str, cache_dir: Optional[str]) -> str:
    return os.path.join(images_dir(cache_dir), key)


def _meta_path(key: str, cache_dir: Optional[str]) -> str:
    return os.path.join(images_dir(cache_dir), f'{key}.json')


def local_url(key: str, prefix: str = DEFAULT_PREFIX) -> str:
    """Публичный URL картинки в кеше."""
    if not prefix.endswith('/'):
        prefix += '/'
    return prefix + key


# ── Чтение ──────────────────────────────────────────────────────────────────

def has_image(url_or_key: str, cache_dir: Optional[str] = None) -> bool:
    """Есть ли картинка в кеше (принимает URL или ключ)."""
    if not url_or_key:
        return False
    return os.path.isfile(_data_path(_key_of(url_or_key), cache_dir))


def read_image(key: str, cache_dir: Optional[str] = None) -> Optional[dict]:
    """
    Читает картинку по ключу для отдачи клиенту.

    Returns:
        ``{'key', 'bytes', 'content_type', 'size', 'url'}`` или None.
        Ключ проверяется регуляркой — по имени файла из запроса ничего,
        кроме ``[0-9a-f]{32}``, прочитать нельзя.
    """
    if not KEY_RE.match(key or ''):
        return None
    path = _data_path(key, cache_dir)
    try:
        with open(path, 'rb') as f:
            data = f.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        return None

    meta: dict = {}
    try:
        with open(_meta_path(key, cache_dir), encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}

    content_type = _normalize_type(meta.get('content_type')) or _sniff(data)
    if not content_type:
        return None
    return {
        'key': key,
        'bytes': data,
        'content_type': content_type,
        'size': len(data),
        'url': meta.get('url', ''),
    }


def localize_image(url: str, cache_dir: Optional[str] = None,
                   prefix: str = DEFAULT_PREFIX) -> Optional[dict]:
    """
    Описание картинки для клиента: локальный URL, если файл в кеше.

    Returns:
        ``{'url': ..., 'remote_url': ...}`` или None, если URL пустой.
        Когда картинки в кеше нет — ``{'url': url}``: ссылка на портал,
        как и до появления кеша.
    """
    if not url:
        return None
    if has_image(url, cache_dir):
        return {'url': local_url(image_key(url), prefix), 'remote_url': url}
    # не скачано — ведём себя как раньше, без лишних полей
    return {'url': url}


# ── Запись ──────────────────────────────────────────────────────────────────

def _normalize_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    base = str(value).split(';')[0].strip().lower()
    return base if base in CONTENT_TYPES else None


def _sniff(data: bytes) -> Optional[str]:
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    head = data[:512].lstrip()
    if head.startswith(b'<svg') or (head.startswith(b'<?xml') and b'<svg' in head):
        return 'image/svg+xml'
    return None


def store_image(url: str, data: bytes, content_type: Optional[str] = None,
                cache_dir: Optional[str] = None,
                max_bytes: int = MAX_IMAGE_BYTES) -> dict:
    """
    Кладёт картинку в кеш (атомарно). Возвращает описание записи.

    Raises:
        ImageError: слишком большой файл или это не картинка.
    """
    if not url:
        raise ImageError('пустой URL картинки')
    if len(data) > max_bytes:
        raise ImageError(f'файл больше {max_bytes} байт: {len(data)}')

    resolved = _normalize_type(content_type) or _sniff(data)
    if not resolved:
        raise ImageError('ответ не похож на картинку (нет сигнатуры и типа)')

    key = image_key(url)
    target_dir = images_dir(cache_dir)
    os.makedirs(target_dir, exist_ok=True)

    data_path = _data_path(key, cache_dir)
    tmp = f'{data_path}.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, data_path)

    meta = {
        'url': url,
        'content_type': resolved,
        'size': len(data),
        'fetched_at': time.time(),
    }
    meta_path = _meta_path(key, cache_dir)
    tmp_meta = f'{meta_path}.tmp'
    with open(tmp_meta, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp_meta, meta_path)

    return {'key': key, 'path': data_path, 'content_type': resolved,
            'size': len(data), 'url': url}


# ── Скачивание ──────────────────────────────────────────────────────────────

def _assert_public_url(url: str, allow_private: bool = False) -> None:
    """
    Проверяет, что URL ведёт наружу по http(s).

    Без этого CLI превращается в SSRF-прокси: достаточно подсунуть задание
    с картинкой ``http://127.0.0.1:8080/admin``, чтобы сервер сходил туда сам.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ImageError(f'поддерживаются только http(s): {url!r}')
    host = parsed.hostname
    if not host:
        raise ImageError(f'в URL нет хоста: {url!r}')
    if allow_private:
        return

    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ImageError(f'не удалось разрешить {host}: {exc}') from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - экзотика от резолвера
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ImageError(
                f'{host} ведёт на внутренний адрес {ip} — скачивание запрещено'
            )


class _NoRedirectHandler(HTTPRedirectHandler):
    """
    Обработчик, который не ходит по редиректам сам.

    ``urlopen`` по умолчанию выполняет 302 за нас — и тогда проверка адреса
    видит только первый хоп. Публичный URL мог бы увести на ``127.0.0.1``
    или ``169.254.169.254``. Поэтому редирект возвращаем вызывающему коду,
    он проверит новый адрес тем же ``_assert_public_url``.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = build_opener(_NoRedirectHandler())

_REDIRECT_CODES = (301, 302, 303, 307, 308)


def _fetch_once(url: str, timeout: float,
                max_bytes: int) -> Tuple[Optional[Tuple[bytes, str]], Optional[str]]:
    """
    Один HTTP-запрос без автоматических редиректов.

    Returns:
        ``((data, content_type), None)`` или ``(None, location)`` для 3xx.
    """
    request = Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5',
    })
    try:
        with _OPENER.open(request, timeout=timeout) as response:  # noqa: S310 — схема проверена
            content_type = response.headers.get_content_type()
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        location = exc.headers.get('Location') if exc.headers else None
        if exc.code in _REDIRECT_CODES and location:
            return None, urljoin(url, location)
        raise ImageError(f'{url}: HTTP {exc.code}') from exc

    if len(data) > max_bytes:
        raise ImageError(f'файл больше {max_bytes} байт')
    return (data, content_type), None


def _http_get_image(url: str, timeout: float = DEFAULT_TIMEOUT,
                    max_bytes: int = MAX_IMAGE_BYTES,
                    allow_private: bool = False) -> Tuple[bytes, str]:
    """
    Скачивает картинку, проверяя **каждый** хоп редиректа.

    Проверять только исходный URL мало: публичный сервер может ответить
    ``302 → http://127.0.0.1/...``, и это уже SSRF.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _assert_public_url(current, allow_private=allow_private)
        result, redirect = _fetch_once(current, timeout, max_bytes)
        if redirect is None and result is not None:
            return result
        current = redirect  # type: ignore[assignment]
    raise ImageError(f'слишком много редиректов (>{MAX_REDIRECTS}): {url}')


def download_image(url: str, cache_dir: Optional[str] = None,
                   timeout: float = DEFAULT_TIMEOUT,
                   max_bytes: int = MAX_IMAGE_BYTES,
                   get: Optional[Fetcher] = None,
                   force: bool = False,
                   allow_private: bool = False) -> dict:
    """
    Скачивает картинку и кладёт в кеш.

    Args:
        get: подмена загрузчика ``url -> (bytes, content_type)``; тесты
             передают свою функцию, чтобы не ходить в сеть.
        force: перекачать, даже если файл уже в кеше.
        allow_private: разрешить внутренние адреса (только для своих тестовых
             стендов; по умолчанию запрещено).

    Raises:
        ImageError: сеть, формат, размер или запрещённый адрес.
    """
    key = image_key(url)
    if not force and has_image(key, cache_dir):
        return {'key': key, 'path': _data_path(key, cache_dir), 'cached': True,
                'content_type': _normalize_type(_read_meta(key, cache_dir).get('content_type')),
                'size': os.path.getsize(_data_path(key, cache_dir)), 'url': url}

    if url.startswith('data:'):
        raise ImageError('data-URI уже встроен в условие, скачивать нечего')

    try:
        if get is not None:
            data, content_type = get(url)
        else:
            # адрес (и каждый хоп редиректа) проверяется внутри
            data, content_type = _http_get_image(
                url, timeout=timeout, max_bytes=max_bytes, allow_private=allow_private,
            )
    except ImageError:
        raise
    except Exception as exc:  # noqa: BLE001 — любая сетевая ошибка = ImageError
        raise ImageError(f'не удалось скачать {url}: {exc}') from exc

    stored = store_image(url, data, content_type, cache_dir=cache_dir, max_bytes=max_bytes)
    stored['cached'] = False
    return stored


def _read_meta(key: str, cache_dir: Optional[str]) -> dict:
    try:
        with open(_meta_path(key, cache_dir), encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


# ── Работа с вопросами ──────────────────────────────────────────────────────

def question_images(question: dict) -> List[str]:
    """URL'ы картинок вопроса (без дублей, в исходном порядке)."""
    urls: List[str] = []
    for img in question.get('images') or []:
        if isinstance(img, dict):
            url = img.get('url')
        else:
            url = img
        if isinstance(url, str) and url and url not in urls:
            urls.append(url)
    return urls


def cache_questions(
    questions: Sequence[dict],
    cache_dir: Optional[str] = None,
    force: bool = False,
    get: Optional[Fetcher] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_IMAGE_BYTES,
    allow_private: bool = False,
) -> dict:
    """
    Скачивает картинки всех вопросов в кеш.

    Returns:
        ``{'total', 'cached', 'skipped', 'failed': [{'url', 'error'}]}``,
        где ``cached`` — скачано сейчас, ``skipped`` — уже было в кеше,
        ``failed`` — не получилось (капча при этом продолжит работать,
        картинка просто останется горячей ссылкой).
    """
    stats: Dict[str, object] = {'total': 0, 'cached': 0, 'skipped': 0, 'failed': []}
    failed: List[dict] = stats['failed']  # type: ignore[assignment]

    for question in questions:
        for url in question_images(question):
            stats['total'] += 1  # type: ignore[operator]
            if url.startswith('data:'):
                stats['skipped'] += 1  # type: ignore[operator]
                continue
            try:
                result = download_image(
                    url, cache_dir=cache_dir, timeout=timeout,
                    max_bytes=max_bytes, get=get, force=force,
                    allow_private=allow_private,
                )
            except ImageError as exc:
                failed.append({'url': url, 'error': str(exc)})
                continue
            stats['skipped' if result.get('cached') else 'cached'] += 1  # type: ignore[operator]
    return stats


def rewrite_questions(
    questions: Iterable[dict],
    cache_dir: Optional[str] = None,
    prefix: str = DEFAULT_PREFIX,
) -> List[dict]:
    """
    Копия вопросов, где URL картинок заменены на локальные, если файл в кеше.

    Вопросы без картинок возвращаются как есть (тот же объект — экономия копий).
    """
    result: List[dict] = []
    for question in questions:
        urls = question_images(question)
        if not urls:
            result.append(question)
            continue
        localized = []
        for img in question.get('images') or []:
            url = img.get('url') if isinstance(img, dict) else img
            alt = img.get('alt', '') if isinstance(img, dict) else ''
            item = localize_image(url, cache_dir, prefix) if isinstance(url, str) else None
            if item is None:
                continue
            item['alt'] = alt
            localized.append(item)
        if not localized:
            result.append(question)
            continue
        copy = dict(question)
        copy['images'] = localized
        result.append(copy)
    return result


# ── Обслуживание ────────────────────────────────────────────────────────────

def stats(cache_dir: Optional[str] = None) -> dict:
    """Сколько файлов и сколько байт лежит в кеше картинок."""
    directory = images_dir(cache_dir)
    count = 0
    total = 0
    try:
        for name in os.listdir(directory):
            if name.endswith('.json') or not KEY_RE.match(name):
                continue
            path = os.path.join(directory, name)
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
            count += 1
    except OSError:
        return {'count': 0, 'bytes': 0, 'dir': directory}
    return {'count': count, 'bytes': total, 'dir': directory}


def _entry_age(key: str, cache_dir: Optional[str]) -> float:
    """Чем свежее скачано, тем больше число (для сортировки «старые первыми»)."""
    fetched = _read_meta(key, cache_dir).get('fetched_at')
    if isinstance(fetched, (int, float)):
        return float(fetched)
    try:
        return os.path.getmtime(_data_path(key, cache_dir))
    except OSError:
        return 0.0


def prune(max_bytes: int, cache_dir: Optional[str] = None) -> dict:
    """
    Удаляет самые старые картинки, пока кеш не станет не больше ``max_bytes``.

    Кеш картинок не имеет естественного срока жизни: задание могло исчезнуть
    с портала, а файл останется навсегда. Чистка по возрасту — самый
    предсказуемый способ вернуть место, не ломая свежие задания.

    Returns:
        ``{'removed', 'freed', 'count', 'bytes'}`` — удалено файлов и байт,
        сколько осталось.
    """
    if max_bytes < 0:
        raise ValueError('max_bytes должен быть >= 0')

    directory = images_dir(cache_dir)
    try:
        names = [n for n in os.listdir(directory) if KEY_RE.match(n)]
    except OSError:
        return {'removed': 0, 'freed': 0, 'count': 0, 'bytes': 0}

    entries = []
    total = 0
    for name in names:
        path = os.path.join(directory, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        total += size
        entries.append((_entry_age(name, cache_dir), size, name))

    removed = 0
    freed = 0
    for _, size, name in sorted(entries):  # старые первыми
        if total <= max_bytes:
            break
        data_path = os.path.join(directory, name)
        meta_path = os.path.join(directory, f'{name}.json')
        try:
            os.remove(data_path)
        except OSError:
            continue
        try:
            os.remove(meta_path)
        except OSError:
            pass
        total -= size
        removed += 1
        freed += size

    return {'removed': removed, 'freed': freed, 'count': len(names) - removed,
            'bytes': max(total, 0)}


def clear(cache_dir: Optional[str] = None) -> int:
    """Удаляет кеш картинок. Возвращает число удалённых файлов."""
    directory = images_dir(cache_dir)
    removed = 0
    try:
        for name in os.listdir(directory):
            if name == 'images':
                continue
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                continue
            removed += 1
    except OSError:
        return 0
    return removed
