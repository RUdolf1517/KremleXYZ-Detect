# -*- coding: utf-8 -*-
"""
Банк вопросов по категориям.

Категории:
  - math       — задания из ЕГЭ по профильной математике
  - physics    — задания из ЕГЭ по физике
  - russian    — каверзные вопросы по русскому языку
  - literature — сложные вопросы по литературе
"""

from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional, Sequence

from .literature import QUESTIONS as LITERATURE_QUESTIONS
from .math import QUESTIONS as MATH_QUESTIONS
from .physics import QUESTIONS as PHYSICS_QUESTIONS
from .russian import QUESTIONS as RUSSIAN_QUESTIONS
from .sdamgia import (  # noqa: F401 — публичный API провайдера
    BASE_URLS, SOURCE as SDAMGIA_SOURCE, SUBJECTS as SDAMGIA_SUBJECTS,
    build_distractors, build_question, cache_age, cache_path, default_cache_dir,
    fetch_questions as fetch_sdamgia_questions, load_cached_questions,
    parse_problem_html, read_cache, sync as sync_sdamgia, write_cache,
)

logger = logging.getLogger('kremle')

#: Публичные имена источников. ``builtin`` и ``auto`` — исторические: первое
#: стало алиасом ``own``, второе осталось самостоятельным режимом.
SOURCES = ('auto', 'own', 'builtin', 'sdamgia', 'own+sdamgia')

#: Алиасы: старые имена работают как раньше (до 3.0).
SOURCE_ALIASES = {'builtin': 'own'}

#: Смешанный режим: свои + «Решу ЕГЭ» в одной капче.
MIXED_SOURCE = 'own+sdamgia'

#: Доли источников по умолчанию для смешанного режима.
DEFAULT_MIXED_RATIO = 0.5

CATEGORIES: Dict[str, list] = {
    'math': MATH_QUESTIONS,
    'physics': PHYSICS_QUESTIONS,
    'russian': RUSSIAN_QUESTIONS,
    'literature': LITERATURE_QUESTIONS,
}

ALL_CATEGORY_NAMES = tuple(CATEGORIES.keys())


def _builtin_pool(cats: Sequence[str]) -> List[dict]:
    pool: List[dict] = []
    for cat in cats:
        for q in CATEGORIES[cat]:
            entry = dict(q)
            entry['category'] = cat
            pool.append(entry)
    return pool


def normalize_source(source: str) -> str:
    """
    Привести имя источника к публичному виду.

    Пример:
        normalize_source('builtin')      # 'own'
        normalize_source('own+sdamgia')  # 'own+sdamgia'
    """
    if source not in SOURCES:
        raise ValueError(
            f'source должен быть одним из {SOURCES}, получено {source!r}'
        )
    return SOURCE_ALIASES.get(source, source)


def validate_mixed_ratio(ratio: float) -> float:
    """
    Доля вопросов портала в смешанном челлендже: 0..1.

    Пример:
        validate_mixed_ratio(0.5)   # 0.5
        validate_mixed_ratio(1.5)   # ValueError
    """
    try:
        value = float(ratio)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'mixed_ratio должен быть числом 0..1, получено {ratio!r}'
        ) from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f'mixed_ratio должен быть в диапазоне 0..1, получено {ratio!r}')
    return value


def _mark_source(questions: List[dict], kind: str) -> List[dict]:
    """Проставить ``source_kind`` (``own`` / ``sdamgia``) каждому вопросу."""
    for question in questions:
        question['source_kind'] = kind
    return questions


def mix_questions(
    own_pool: List[dict],
    portal_pool: List[dict],
    count: Optional[int],
    ratio: float = DEFAULT_MIXED_RATIO,
    rng: Optional[random.Random] = None,
) -> List[dict]:
    """
    Собрать челлендж из двух источников в заданной пропорции.

    Если одного источника не хватает (пуст кеш портала, кончились свои
    вопросы), добор идёт из другого — лучше челлендж целиком, чем половина.

    Пример:
        mix_questions(own=мои, portal=портал, count=15, ratio=0.5)
    """
    rng = rng or random.Random()
    own_pool, portal_pool = list(own_pool), list(portal_pool)
    rng.shuffle(own_pool)
    rng.shuffle(portal_pool)
    if count is None:
        return _mark_source(own_pool, 'own') + _mark_source(portal_pool, 'sdamgia')

    want_portal = int(round(count * ratio)) if portal_pool else 0
    want_portal = min(want_portal, len(portal_pool))
    want_own = min(count - want_portal, len(own_pool))

    # добираем недостающее другим источником
    missing = count - want_portal - want_own
    if missing > 0:
        extra_own = min(missing, len(own_pool) - want_own)
        want_own += extra_own
        missing -= extra_own
    if missing > 0:
        want_portal += min(missing, len(portal_pool) - want_portal)

    mixed = _mark_source(own_pool[:want_own], 'own')
    mixed += _mark_source(portal_pool[:want_portal], 'sdamgia')
    rng.shuffle(mixed)
    return mixed


def get_questions(
    categories: Optional[Sequence[str]] = None,
    count: Optional[int] = None,
    shuffle: bool = True,
    source: str = 'auto',
    cache_dir: Optional[str] = None,
    allow_images: bool = False,
    mixed_ratio: float = DEFAULT_MIXED_RATIO,
) -> List[dict]:
    """
    Возвращает список вопросов.

    Args:
        categories: список категорий ('math', 'physics', 'russian', 'literature').
                    None — все категории.
        count: сколько вопросов вернуть. None — все.
        shuffle: перемешать вопросы.
        source: откуда брать вопросы:

                * ``auto`` (по умолчанию) — кеш «Решу ЕГЭ», если он есть,
                  иначе встроенный банк;
                * ``own`` — только свой банк (встроенный + ``extra_questions``
                  движка), работает без сети; ``builtin`` — его алиас;
                * ``sdamgia`` — только кеш «Решу ЕГЭ» (без кеша — пусто);
                * ``own+sdamgia`` — оба источника в одной капче, пропорция
                  задаётся ``mixed_ratio``.
        cache_dir: каталог кеша (по умолчанию ``~/.cache/kremle-detect``).
        allow_images: отдавать задания с рисунком (по умолчанию отбрасываются:
                      картинки грузятся с портала и могут не открыться).
        mixed_ratio: доля вопросов «Решу ЕГЭ» для ``own+sdamgia`` (0..1,
                      по умолчанию 0.5). Игнорируется остальными режимами.

    Returns:
        Список dict с ключами: q, opts, ans, category, source_kind
        (+ source — атрибуция у вопросов из «Решу ЕГЭ»).

    Пример:
        get_questions(['math'], count=5)                    # auto
        get_questions(['math'], count=5, source='own')      # без сети
        get_questions(count=15, source='own+sdamgia', mixed_ratio=0.3)
    """
    source = normalize_source(source)
    ratio = validate_mixed_ratio(mixed_ratio)

    cats = [c.lower() for c in (categories or ALL_CATEGORY_NAMES)]
    for cat in cats:
        if cat not in CATEGORIES:
            raise ValueError(
                f'Неизвестная категория: {cat!r}. '
                f'Доступные (строчными): {ALL_CATEGORY_NAMES}'
            )

    cached: List[dict] = []
    if source in ('auto', 'sdamgia', MIXED_SOURCE):
        cached = load_cached_questions(cats, cache_dir=cache_dir)
        if not cached and source == 'sdamgia':
            logger.warning(
                'Вопросы «Решу ЕГЭ» запрошены, но кеша нет — банк пуст. '
                'Запустите `kremle-detect questions sync`.'
            )
        elif not cached and source == 'auto':
            logger.info(
                'Кеша вопросов «Решу ЕГЭ» нет — используется встроенный банк. '
                'Для загрузки: `kremle-detect questions sync`.'
            )
        elif not cached and source == MIXED_SOURCE:
            logger.info(
                'Смешанный режим: кеша «Решу ЕГЭ» нет — челлендж целиком из '
                'своего банка. Для загрузки: `kremle-detect questions sync`.'
            )

    if not allow_images:
        cached = [q for q in cached if not q.get('images')]

    if source == MIXED_SOURCE:
        own = _builtin_pool(cats)
        if not allow_images:
            own = [q for q in own if not q.get('images')]
        return mix_questions(own, cached, count, ratio)

    pool: List[dict] = list(cached) if source != 'own' else []
    if pool:
        pool = _mark_source(pool, 'sdamgia')
    if not pool and source != 'sdamgia':
        pool = _mark_source(_builtin_pool(cats), 'own')

    if not allow_images:
        pool = [q for q in pool if not q.get('images')]

    if shuffle:
        random.shuffle(pool)

    if count is not None:
        pool = pool[:count]

    return pool


def validate_questions(questions: list) -> None:
    """
    Проверяет формат кастомных вопросов. Бросает ValueError при ошибке.

    Каждый вопрос должен быть dict с полями:
        q   (str)  — текст вопроса
        opts (list) — минимум 2 варианта ответа
        ans (int)  — индекс правильного варианта в opts (0-based)
    """
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f'Вопрос #{i}: ожидается dict, получено {type(q).__name__}')
        if 'q' not in q or not isinstance(q['q'], str) or not q['q'].strip():
            raise ValueError(f'Вопрос #{i}: поле "q" должно быть непустой строкой')
        if 'opts' not in q or not isinstance(q['opts'], list) or len(q['opts']) < 2:
            raise ValueError(f'Вопрос #{i}: поле "opts" должно быть списком минимум из 2 вариантов')
        if 'ans' not in q or not isinstance(q['ans'], int) or not (0 <= q['ans'] < len(q['opts'])):
            raise ValueError(
                f'Вопрос #{i}: поле "ans" должно быть индексом правильного варианта (0–{len(q["opts"])-1})'
            )


def question_sources(questions: Sequence[dict]) -> List[dict]:
    """
    Уникальные источники вопросов — для подписи «Задания: РешуЕГЭ» в UI.

    Пример:
        question_sources(challenge.questions)
        # → [{'name': 'РешуЕГЭ', 'url': 'https://sdamgia.ru/', 'author': '...'}]
    """
    seen = set()
    result: List[dict] = []
    for q in questions:
        src = q.get('source')
        if not isinstance(src, dict):
            continue
        key = (src.get('name'), src.get('url'))
        if key in seen:
            continue
        seen.add(key)
        result.append({
            'name': src.get('name', ''),
            'url': src.get('url', ''),
            'author': src.get('author', ''),
        })
    return result


def attribution_text(questions: Sequence[dict]) -> str:
    """Готовая строка атрибуции для шаблона капчи."""
    names = sorted({(q.get('source') or {}).get('name') for q in questions
                    if isinstance(q.get('source'), dict) and (q.get('source') or {}).get('name')})
    if not names:
        return ''
    return 'Задания: ' + ', '.join(names)
