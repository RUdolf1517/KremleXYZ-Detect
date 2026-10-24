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

SOURCES = ('auto', 'builtin', 'sdamgia')

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


def get_questions(
    categories: Optional[Sequence[str]] = None,
    count: Optional[int] = None,
    shuffle: bool = True,
    source: str = 'auto',
    cache_dir: Optional[str] = None,
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
                * ``builtin`` — только встроенный банк (работает без сети);
                * ``sdamgia`` — только кеш «Решу ЕГЭ» (без кеша — пусто).
        cache_dir: каталог кеша (по умолчанию ``~/.cache/kremle-detect``).

    Returns:
        Список dict с ключами: q, opts, ans, category (+ source у вопросов
        из «Решу ЕГЭ»).

    Пример:
        get_questions(['math'], count=5)                    # auto
        get_questions(['math'], count=5, source='builtin')  # без сети
    """
    if source not in SOURCES:
        raise ValueError(f'source должен быть одним из {SOURCES}, получено {source!r}')

    cats = [c.lower() for c in (categories or ALL_CATEGORY_NAMES)]
    for cat in cats:
        if cat not in CATEGORIES:
            raise ValueError(
                f'Неизвестная категория: {cat!r}. '
                f'Доступные (строчными): {ALL_CATEGORY_NAMES}'
            )

    pool: List[dict] = []
    if source in ('auto', 'sdamgia'):
        cached = load_cached_questions(cats, cache_dir=cache_dir)
        if cached:
            pool = cached
        elif source == 'sdamgia':
            logger.warning(
                'Вопросы «Решу ЕГЭ» запрошены, но кеша нет — банк пуст. '
                'Запустите `kremle-detect questions sync`.'
            )
        else:
            logger.info(
                'Кеша вопросов «Решу ЕГЭ» нет — используется встроенный банк. '
                'Для загрузки: `kremle-detect questions sync`.'
            )

    if not pool and source != 'sdamgia':
        pool = _builtin_pool(cats)

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
