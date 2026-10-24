# -*- coding: utf-8 -*-
"""
Вопросы из открытого банка «Решу ЕГЭ» (СДАМ ГИА, sdamgia.ru).

Провайдер работает в offline-first режиме: вопросы один раз скачиваются в
локальный кеш (CLI ``kremle-detect questions sync``), а во время запроса
читаются с диска. Если кеша нет или он устарел — используется встроенный
банк вопросов, приложение продолжает работать без сети.

Атрибуция обязательна: каждый вопрос получает поле ``source``, а на карточке
капчи показывается ссылка на первоисточник. Условия использования материалов
портала — на стороне оператора: см. NOTICE.md.

Что скачивается:
    * ``newapi/general`` — JSON со списком предметов и вариантами;
    * страница варианта — из неё берутся ссылки на отдельные задания;
    * ``/problem?id=<id>`` — страница задания (условие + ответ).

Множественный выбор строится из числового ответа: правильный вариант плюс
три правдоподобных искажения (сдвиг, масштаб, смена знака). Задания с
текстовым ответом пропускаются — для капчи они не годятся.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from html.parser import HTMLParser
from typing import Callable, Dict, Iterable, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger('kremle')

SOURCE = {
    'name': 'Решу ЕГЭ (СДАМ ГИА)',
    'short': 'РешуЕГЭ',
    'url': 'https://sdamgia.ru/',
    'author': 'Д. Д. Гущин и авторы портала',
    'license_note': (
        'Задания принадлежат порталу «Решу ЕГЭ» / СДАМ ГИА. Используйте '
        'с указанием источника и на условиях портала (см. NOTICE.md).'
    ),
}

# Поддомены предметов: ключ категории kremle-detect → предмет sdamgia.
SUBJECTS: Dict[str, str] = {
    'math': 'math',
    'physics': 'phys',
    'russian': 'rus',
    'literature': 'lit',
}

BASE_URLS: Dict[str, str] = {
    'math': 'https://math-ege.sdamgia.ru',
    'phys': 'https://phys-ege.sdamgia.ru',
    'rus': 'https://rus-ege.sdamgia.ru',
    'lit': 'https://lit-ege.sdamgia.ru',
}

DEFAULT_CACHE_TTL = 30 * 86400  # 30 дней
DEFAULT_TIMEOUT = 10.0
USER_AGENT = 'kremle-detect/2.7 (+https://github.com/RUdolf1517/KremleXYZ-Detect)'


# ── Кеш ──────────────────────────────────────────────────────────────────────

def default_cache_dir() -> str:
    """
    Каталог кеша: ``$KREMLE_CACHE_DIR`` или ``~/.cache/kremle-detect``
    (XDG_CACHE_HOME учитывается).
    """
    explicit = os.environ.get('KREMLE_CACHE_DIR')
    if explicit:
        return explicit
    xdg = os.environ.get('XDG_CACHE_HOME')
    base = xdg if xdg else os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'kremle-detect')


def cache_path(category: str, cache_dir: Optional[str] = None) -> str:
    """Путь к файлу кеша для категории."""
    return os.path.join(cache_dir or default_cache_dir(), f'sdamgia-{category}.json')


def read_cache(category: str, cache_dir: Optional[str] = None) -> Optional[dict]:
    """
    Читает кеш. Возвращает ``{'questions': [...], 'fetched_at': ts}`` или None.

    Пример:
        data = read_cache('math')
        if data:
            questions = data['questions']
    """
    path = cache_path(category, cache_dir)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('questions'), list):
        return None
    return data


def write_cache(category: str, questions: Sequence[dict], cache_dir: Optional[str] = None) -> str:
    """Атомарно пишет кеш (через временный файл). Возвращает путь."""
    path = cache_path(category, cache_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        'category': category,
        'source': SOURCE,
        'fetched_at': time.time(),
        'questions': list(questions),
    }
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def cache_age(category: str, cache_dir: Optional[str] = None) -> Optional[float]:
    """Возраст кеша в секундах или None, если кеша нет."""
    data = read_cache(category, cache_dir)
    if not data:
        return None
    fetched = data.get('fetched_at')
    if not isinstance(fetched, (int, float)):
        return None
    return max(0.0, time.time() - float(fetched))


def load_cached_questions(
    categories: Optional[Iterable[str]] = None,
    cache_dir: Optional[str] = None,
    max_age: Optional[float] = DEFAULT_CACHE_TTL,
) -> List[dict]:
    """
    Вопросы из кеша без обращения к сети.

    Просроченный кеш всё равно возвращается, если других вариантов нет:
    лучше устаревшая капча, чем пустой банк.

    Пример:
        load_cached_questions(['math'])   # → [{'q': ..., 'source': {...}}, ...]
    """
    cats = list(categories or SUBJECTS.keys())
    result: List[dict] = []
    for category in cats:
        if category not in SUBJECTS:
            continue
        data = read_cache(category, cache_dir)
        if not data:
            continue
        age = cache_age(category, cache_dir)
        if max_age is not None and age is not None and age > max_age:
            logger.info('Кеш вопросов %s устарел (%.1f дней) — нужен sync', category, age / 86400)
        result.extend(data['questions'])
    return result


# ── Разбор страницы задания ──────────────────────────────────────────────────

class _ProblemHTMLParser(HTMLParser):
    """
    Достаёт из страницы задания условие и ответ.

    Структура портала: ``div.prob_maindiv`` → несколько ``div.pbody``
    (условие, затем решение) и ``div.answer`` с текстом ``Ответ: 0,95``.
    Условие — первый ``pbody``, поэтому остальные игнорируются.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._main_depth: Optional[int] = None
        self._capture: Optional[str] = None
        self._capture_depth: Optional[int] = None
        self._buf: List[str] = []
        self._pbody_count = 0
        self.condition = ''
        self.answer = ''
        #: Картинки из условия: у «Решу ЕГЭ» часть заданий без рисунка не решить.
        self.images: List[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            self._depth += 1
            classes = set((dict(attrs).get('class') or '').split())

            if 'prob_maindiv' in classes:
                self._main_depth = self._depth
                return

            if self._main_depth is None:
                return

            # Интересуют только прямые потомки блока задания
            if self._depth != self._main_depth + 1:
                return

            if 'pbody' in classes:
                self._pbody_count += 1
                if self._pbody_count == 1 and not self.condition:
                    self._capture = 'condition'
                    self._capture_depth = self._depth
                    self._buf = []
            elif 'answer' in classes:
                self._capture = 'answer'
                self._capture_depth = self._depth
                self._buf = []
        elif self._capture and tag in ('br', 'p'):
            self._buf.append(' ')
        elif self._capture == 'condition' and tag == 'img':
            attrs_map = dict(attrs)
            src = (attrs_map.get('src') or '').strip()
            if src:
                self.images.append({'url': src, 'alt': (attrs_map.get('alt') or '').strip()})

    def handle_endtag(self, tag):
        if tag != 'div':
            return

        if self._capture and self._capture_depth == self._depth:
            text = re.sub(r'\s+', ' ', ''.join(self._buf)).strip()
            if self._capture == 'condition':
                self.condition = text
            else:
                self.answer = text
            self._capture = None
            self._capture_depth = None
            self._buf = []

        self._depth -= 1
        if self._main_depth is not None and self._depth < self._main_depth:
            self._main_depth = None

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def parse_problem_html(html: str, base_url: Optional[str] = None) -> Optional[dict]:
    """
    Возвращает ``{'condition', 'answer', 'images'}`` или None.

    ``images`` — картинки из условия (например чертёж или график). У «Решу ЕГЭ»
    часть заданий без рисунка не имеет смысла, поэтому их нельзя молча терять.

    Пример:
        parse_problem_html(open('problem.html').read(), 'https://math-ege.sdamgia.ru')
        # → {'condition': 'На рисунке изображён график...', 'answer': '0,95',
        #    'images': [{'url': 'https://math-ege.sdamgia.ru/img/1.png', 'alt': ''}]}
    """
    parser = _ProblemHTMLParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — битая разметка не должна ронять приложение
        return None

    condition = parser.condition
    answer = parser.answer
    answer = re.sub(r'^\s*Ответ\s*:\s*', '', answer, flags=re.IGNORECASE).strip()
    if not condition or not answer:
        return None

    images = []
    seen = set()
    for image in parser.images:
        url = image['url']
        if base_url and url.startswith('/'):
            url = f'{base_url}{url}'
        elif base_url and not url.startswith(('http://', 'https://', 'data:')):
            url = f'{base_url}/{url}'
        if url in seen:
            continue
        seen.add(url)
        images.append({'url': url, 'alt': image.get('alt', '')})

    return {'condition': condition, 'answer': answer, 'images': images}


# ── Построение вариантов ответа ──────────────────────────────────────────────

_NUM_RE = re.compile(r'^-?\d+(?:[.,]\d+)?$')


def _to_number(answer: str) -> Optional[float]:
    text = answer.strip().replace(' ', '')
    # «0,95» → «0.95», «−3» → «-3»
    text = text.replace('−', '-').replace(',', '.')
    if not _NUM_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_like(value: float, sample: str) -> str:
    """Форматирует число в стиле исходного ответа (запятая, знаки после точки)."""
    sample_clean = sample.replace('−', '-').replace(' ', '')
    decimals = 0
    if '.' in sample_clean or ',' in sample_clean:
        decimals = len(re.split(r'[.,]', sample_clean)[1])
    text = f'{value:.{decimals}f}' if decimals else f'{value:.0f}'
    if ',' in sample and '.' not in sample:
        text = text.replace('.', ',')
    return text


def build_distractors(answer: str, count: int = 3, rng=None) -> Optional[List[str]]:
    """
    Строит ``count`` неверных вариантов для числового ответа.

    Для текстовых ответов возвращает None: угадывать «похожие слова» нельзя,
    это ломает смысл вопроса.

    Пример:
        build_distractors('0,95')   # → ['0,85', '1,95', '–0,95'] (порядок случаен)
    """
    import random as _random

    rng = rng or _random
    number = _to_number(answer)
    if number is None:
        return None

    decimals = 0
    cleaned = answer.replace('−', '-').replace(' ', '')
    if '.' in cleaned or ',' in cleaned:
        decimals = len(re.split(r'[.,]', cleaned)[1])
    step = 10 ** (-decimals) if decimals else 1.0
    eps = step / 2

    candidates: List[float] = [
        number + step,
        number - step,
        number * 2,
        number / 2 if number else number + 2 * step,
        -number,
        number + 10 * step,
    ]

    result: List[str] = []
    seen = {_format_like(number, answer)}
    for cand in candidates:
        if len(result) >= count:
            break
        if abs(cand - number) < eps:
            continue
        formatted = _format_like(cand, answer)
        if formatted in seen:
            continue
        seen.add(formatted)
        result.append(formatted)

    while len(result) < count:
        # запасной вариант: сдвиг на случайные шаги
        cand = number + step * rng.randint(count, 20) * rng.choice((-1, 1))
        formatted = _format_like(cand, answer)
        if formatted in seen:
            continue
        seen.add(formatted)
        result.append(formatted)

    return result


def build_question(
    problem: dict,
    category: str,
    problem_id: str,
    base_url: str,
    rng=None,
    allow_images: bool = False,
) -> Optional[dict]:
    """
    Превращает задачу портала в вопрос капчи с 4 вариантами.

    Возвращает None, если ответ не числовой, условие слишком длинное или в
    условии есть картинка, а ``allow_images=False`` (по умолчанию: горячие
    ссылки на изображения портала не должны попадать в капчу без спроса).
    """
    import random as _random

    rng = rng or _random

    condition = (problem.get('condition') or '').strip()
    answer = (problem.get('answer') or '').strip()
    images = [i for i in (problem.get('images') or []) if isinstance(i, dict) and i.get('url')]
    if not condition or not answer:
        return None
    if images and not allow_images:
        return None
    if len(condition) > 400:
        return None

    distractors = build_distractors(answer, 3, rng=rng)
    if not distractors:
        return None

    opts = [answer] + distractors
    rng.shuffle(opts)

    question = {
        'q': condition,
        'opts': opts,
        'ans': opts.index(answer),
        'category': category,
        'problem_id': str(problem_id),
        'source': {
            'name': SOURCE['short'],
            'url': f'{base_url}/problem?id={problem_id}',
            'author': SOURCE['author'],
        },
    }
    if images:
        question['images'] = images
    return question


# ── Сеть ─────────────────────────────────────────────────────────────────────

def http_get(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """
    GET с таймаутом и нашим User-Agent.

    Отдельная функция, чтобы её можно было подменить в тестах и в CLI.
    """
    request = Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/html;q=0.9, */*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9',
    })
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 — только https-хосты sdamgia
        charset = response.headers.get_content_charset() or 'utf-8'
        return response.read().decode(charset, 'replace')


def fetch_general(
    base_url: str, get: Optional[Callable[[str], str]] = None,
) -> Optional[dict]:
    """JSON ``/newapi/general`` — метаданные предмета. None при любой ошибке."""
    get = get or http_get
    try:
        raw = get(f'{base_url}/newapi/general')
        data = json.loads(raw)
    except (HTTPError, URLError, OSError, ValueError, TypeError) as exc:
        logger.warning('РешуЕГЭ: не удалось получить newapi/general (%s)', exc)
        return None
    return data if isinstance(data, dict) else None


PROBLEM_LINK_RE = re.compile(r'/problem\?id=(\d+)')

#: С какого id начинать перебор, если портал не отдал список заданий.
#: Идентификаторы заданий в банке «Решу ЕГЭ» — сквозные числа, самые старые
#: задания лежат в начале диапазона.
SEED_PROBLEM_IDS: Dict[str, int] = {
    'math': 1001,
    'phys': 1001,
    'rus': 1001,
    'lit': 1001,
}

#: Сколько подряд идущих id пробовать, если список заданий неизвестен.
PROBE_WINDOW = 40


def parse_problem_ids(html: str, limit: Optional[int] = None) -> List[str]:
    """
    Вытаскивает id заданий из любой страницы портала (вариант, каталог).

    Пример:
        ids = parse_problem_ids(html, limit=10)
    """
    ids: List[str] = []
    seen = set()
    for pid in PROBLEM_LINK_RE.findall(html or ''):
        if pid not in seen:
            seen.add(pid)
            ids.append(pid)
            if limit is not None and len(ids) >= limit:
                break
    return ids


def variant_hrefs(general: dict) -> List[str]:
    """
    Ссылки на варианты из ``newapi/general``.

    ``id`` в ответе API — идентификатор варианта, а не задания, поэтому
    качать по нему ``/problem?id=`` нельзя: сначала открываем вариант и
    собираем ссылки на задания из него.
    """
    hrefs: List[str] = []
    for key in ('larinVariants', 'probVariants', 'ourVariants'):
        for variant in (general.get(key) or []):
            if not isinstance(variant, dict):
                continue
            href = variant.get('href')
            if isinstance(href, str) and href.startswith('/'):
                hrefs.append(href)
    return hrefs


def discover_problem_ids(
    category: str,
    limit: int,
    get: Optional[Callable[[str], str]] = None,
) -> List[str]:
    """
    Ищет id заданий: варианты из API → перебор ближайших id от seed.

    Портал отдаёт содержимое страниц вариантов в обфусцированном виде, но
    ссылки на отдельные задания в разметке остаются. Если и это не сработало
    (портал сменил вёрстку), перебираем ближайшие id — задания с текстовым
    ответом всё равно отсеются при разборе.
    """
    get = get or http_get
    base_url = BASE_URLS[SUBJECTS[category]]
    ids: List[str] = []
    seen = set()

    general = fetch_general(base_url, get=get)
    if general:
        for href in variant_hrefs(general)[:5]:
            try:
                html = get(f'{base_url}{href}')
            except (HTTPError, URLError, OSError) as exc:
                logger.debug('РешуЕГЭ: вариант %s не открылся (%s)', href, exc)
                continue
            for pid in parse_problem_ids(html):
                if pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
            if len(ids) >= limit:
                return ids[:limit]

    # Перебор ближайших id: первая страница, которая не разобралась, ещё не
    # повод останавливаться — в банке бывают «дыры».
    seed = SEED_PROBLEM_IDS[category]
    for offset in range(PROBE_WINDOW):
        if len(ids) >= limit:
            break
        pid = str(seed + offset)
        if pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)

    return ids[:limit]


def fetch_questions(
    category: str,
    limit: int = 60,
    problem_ids: Optional[Sequence[str]] = None,
    get: Optional[Callable[[str], str]] = None,
    rng=None,
    allow_images: bool = False,
) -> List[dict]:
    """
    Скачивает задания и превращает их в вопросы капчи.

    Args:
        category: ключ категории kremle-detect (math/physics/russian/literature).
        limit: сколько вопросов максимум вернуть.
        problem_ids: конкретные id заданий; None → взять из ``newapi/general``.
        get: функция HTTP-запроса (подменяется в тестах).

    Пример:
        questions = fetch_questions('math', limit=20)
    """
    if category not in SUBJECTS:
        raise ValueError(
            f'Нет источника для категории {category!r}. Доступны: {", ".join(SUBJECTS)}'
        )
    get = get or http_get
    if limit <= 0:
        return []

    base_url = BASE_URLS[SUBJECTS[category]]

    ids = list(problem_ids or [])
    if not ids:
        ids = discover_problem_ids(category, limit=limit, get=get)

    questions: List[dict] = []
    for pid in ids:
        if len(questions) >= limit:
            break
        try:
            html = get(f'{base_url}/problem?id={pid}')
        except (HTTPError, URLError, OSError) as exc:
            logger.warning('РешуЕГЭ: задание %s не скачалось (%s)', pid, exc)
            continue
        parsed = parse_problem_html(html, base_url=base_url)
        if not parsed:
            continue
        question = build_question(
            parsed, category, str(pid), base_url, rng=rng, allow_images=allow_images,
        )
        if question:
            questions.append(question)

    logger.info('РешуЕГЭ: скачано %d вопрос(ов) для %s', len(questions), category)
    return questions


def sync(
    categories: Optional[Iterable[str]] = None,
    limit: int = 60,
    cache_dir: Optional[str] = None,
    get: Optional[Callable[[str], str]] = None,
    rng=None,
    problem_ids: Optional[Sequence[str]] = None,
    allow_images: bool = False,
) -> Dict[str, int]:
    """
    Скачивает вопросы и пишет их в кеш.

    Возвращает ``{category: количество_вопросов}``. Категории, которые не
    удалось скачать, в результат не попадают (кеш не затирается).

    Пример:
        sync(['math', 'physics'], limit=100)
    """
    get = get or http_get
    cats = list(categories or SUBJECTS.keys())
    result: Dict[str, int] = {}
    for category in cats:
        if category not in SUBJECTS:
            logger.warning('РешуЕГЭ: пропускаю неизвестную категорию %s', category)
            continue
        try:
            questions = fetch_questions(
                category, limit=limit, problem_ids=problem_ids, get=get,
                rng=rng, allow_images=allow_images,
            )
        except ValueError as exc:
            logger.warning('%s', exc)
            continue
        if not questions:
            logger.warning('РешуЕГЭ: для %s ничего не скачалось — кеш не изменён', category)
            continue
        write_cache(category, questions, cache_dir)
        result[category] = len(questions)
    return result
