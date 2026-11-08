# -*- coding: utf-8 -*-
"""
Устаревшие имена и поведения: одно место, где объявляются сроки.

Правило проекта: в 2.x ломающих изменений нет, поэтому всё, что уходит,
сначала объявляется здесь — с версией, в которой появилось предупреждение,
и версией, в которой имя исчезнет. Пользователь видит ``DeprecationWarning``
в логе и успевает переехать; 3.0 удаляет объявленное.

Пример:
    from kremle_detect.deprecations import warn_deprecated

    warn_deprecated(
        'questions_source="builtin"',
        since='2.13.1', remove_in='3.0', hint='используйте "own"',
    )
"""

from __future__ import annotations

import warnings
from typing import Optional

#: Что уже объявлено устаревшим. Ключ — имя, значение — (since, remove_in, hint).
#: Таблица нужна тестам и документации: обещания сверяются, а не запоминаются.
DEPRECATED: dict = {
    'questions_source="builtin"': (
        '2.14.0', '3.0', 'используйте questions_source="own"',
    ),
}


def warn_deprecated(
    feature: str,
    since: str,
    remove_in: str = '3.0',
    hint: Optional[str] = None,
    stacklevel: int = 3,
) -> None:
    """
    Предупредить об устаревшем имени (``DeprecationWarning``).

    Args:
        feature: что именно устарело — так, как это написано в коде пользователя.
        since: версия, в которой появилось предупреждение.
        remove_in: версия, в которой имя исчезнет.
        hint: чем заменить.
        stacklevel: глубина стека для корректного «файла пользователя».

    Пример:
        warn_deprecated('source="builtin"', since='2.13.1')
    """
    message = f'{feature} устарело с {since} и будет удалено в {remove_in}.'
    if hint:
        message += f' {hint[0].upper()}{hint[1:]}.'
    warnings.warn(message, DeprecationWarning, stacklevel=stacklevel)
