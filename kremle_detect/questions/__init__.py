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

import random
from typing import Dict, List, Optional, Sequence

from .math import QUESTIONS as MATH_QUESTIONS
from .physics import QUESTIONS as PHYSICS_QUESTIONS
from .russian import QUESTIONS as RUSSIAN_QUESTIONS
from .literature import QUESTIONS as LITERATURE_QUESTIONS

CATEGORIES: Dict[str, list] = {
    'math': MATH_QUESTIONS,
    'physics': PHYSICS_QUESTIONS,
    'russian': RUSSIAN_QUESTIONS,
    'literature': LITERATURE_QUESTIONS,
}

ALL_CATEGORY_NAMES = tuple(CATEGORIES.keys())


def get_questions(
    categories: Optional[Sequence[str]] = None,
    count: Optional[int] = None,
    shuffle: bool = True,
) -> List[dict]:
    """
    Возвращает список вопросов.

    Args:
        categories: список категорий ('math', 'physics', 'russian', 'literature').
                    None — все категории.
        count: сколько вопросов вернуть. None — все.
        shuffle: перемешать вопросы.

    Returns:
        Список dict с ключами: q, opts, ans, category
    """
    cats = categories or ALL_CATEGORY_NAMES

    pool = []
    for cat in cats:
        if cat not in CATEGORIES:
            raise ValueError(f'Неизвестная категория: {cat!r}. Доступные: {ALL_CATEGORY_NAMES}')
        for q in CATEGORIES[cat]:
            entry = dict(q)
            entry['category'] = cat
            pool.append(entry)

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
