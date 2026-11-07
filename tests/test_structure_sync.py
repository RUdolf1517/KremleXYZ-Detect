"""Документация не отстаёт от кода: версии и состав модулей.

Проверяем то, что глазами не видно: бейдж в README, шапку `STRUCTURE.md`,
версии в метаданных пакетов и список файлов в дереве структуры. Раньше
`STRUCTURE.md` два релиза подряд описывал 2.7.0 — теперь такой дрейф валит тест.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kremle_detect import __version__

ROOT = Path(__file__).resolve().parent.parent

# Строка дерева в STRUCTURE.md: '│   ├── captcha.py   Ядро...'
TREE_LINE = re.compile(r'^(?P<prefix>(?:[│ ]   )*)(?:├── |└── )(?P<name>\S+)')


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding='utf-8')


def _pyproject_version() -> str:
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', _read('pyproject.toml'), re.M)
    assert match is not None, 'в pyproject.toml нет version'
    return match.group(1)


def _react_version() -> str:
    return json.loads(_read('kremle-react/package.json'))['version']


def _readme_badge_version() -> str:
    match = re.search(r'badge/version-([0-9][^-]*)-', _read('README.md'))
    assert match is not None, 'в README нет бейджа version'
    return match.group(1)


def _structure_tree(block: str) -> list[str]:
    """Пути из блока «Структура» — по отступам дерева."""
    stack: list[tuple[int, str]] = []
    paths: list[str] = []
    for line in block.splitlines():
        match = TREE_LINE.match(line)
        if not match:
            continue
        depth = len(match.group('prefix')) // 4
        name = match.group('name')
        while stack and stack[-1][0] >= depth:
            stack.pop()
        stack.append((depth, name))
        paths.append('/'.join(part for _, part in stack).replace('//', '/'))
    return paths


def _structure_block() -> str:
    text = _read('STRUCTURE.md')
    return text.split('## Структура', 1)[1].split('```', 2)[1]


def test_versions_match():
    """Одна версия во всех местах, где она написана руками."""
    places = {
        'kremle-react/package.json': _react_version(),
        'pyproject.toml': _pyproject_version(),
        'README.md (бейдж)': _readme_badge_version(),
    }
    assert places == {name: __version__ for name in places}, places


def test_structure_header_version():
    text = _read('STRUCTURE.md')
    assert re.search(r'^# kremle-detect v' + re.escape(__version__) + r'\s*$', text, re.M), (
        'шапка STRUCTURE.md не совпадает с __version__'
    )
    assert f"__version__ = '{__version__}'" in text, (
        'строка с __version__ в дереве STRUCTURE.md устарела'
    )


def test_structure_modules_match_package():
    """Список файлов в STRUCTURE.md = содержимое kremle_detect/."""
    documented = {
        path for path in _structure_tree(_structure_block()) if path.startswith('kremle_detect/')
    }
    actual = {
        'kremle_detect/' + str(path.relative_to(ROOT / 'kremle_detect')).replace('__pycache__/', '')
        for path in (ROOT / 'kremle_detect').rglob('*')
        if path.is_file() and '__pycache__' not in path.parts
    }
    missing = sorted(actual - documented)
    stale = sorted(path for path in documented - actual if not path.endswith('/'))
    assert not missing, f'есть в пакете, нет в STRUCTURE.md: {missing}'
    assert not stale, f'есть в STRUCTURE.md, нет в пакете: {stale}'


def test_structure_mentions_security_helpers():
    """Общие помощники интеграций описаны в дереве — они общие для всех трёх."""
    block = _structure_block()
    line = next(
        (line for line in block.splitlines() if '_common.py' in line),
        '',
    )
    assert 'заголовк' in line.lower() or 'безопасн' in line.lower(), (
        'в STRUCTURE.md _common.py описан без учёта заголовков безопасности'
    )
