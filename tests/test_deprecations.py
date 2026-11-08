# -*- coding: utf-8 -*-
"""Устаревания объявлены кодом, а не обещаниями в документе.

Правило: имя сначала предупреждает (`DeprecationWarning`), потом исчезает в
3.0. Таблица `DEPRECATED` — единственное место, где хранятся сроки, поэтому
тесты сверяются с ней, а не с памятью автора.
"""

import warnings

import pytest

from kremle_detect.deprecations import DEPRECATED, warn_deprecated
from kremle_detect.questions import get_questions, normalize_source


class TestTable:
    def test_every_entry_has_a_deadline(self):
        for feature, (since, remove_in, hint) in DEPRECATED.items():
            assert since and remove_in, feature
            assert remove_in.startswith('3.'), f'{feature}: удаление только в мажоре'
            assert hint, f'{feature}: без подсказки «чем заменить»'

    def test_documented(self):
        """Про устаревшее имя написано в доках и в роадмапе, а не только в коде."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        questions = (root / 'docs' / 'questions.md').read_text(encoding='utf-8')
        roadmap = (root / 'ROADMAP.md').read_text(encoding='utf-8')
        for feature in DEPRECATED:
            token = feature.split('=')[-1].strip('"\'')
            assert token in questions, f'{token} не описан в docs/questions.md'
            assert token in roadmap, f'{token} не указан в ROADMAP.md'


class TestWarning:
    def test_warn_deprecated_emits(self):
        with pytest.warns(DeprecationWarning) as caught:
            warn_deprecated('старое имя', since='2.14.0', hint='используйте новое')
        message = str(caught[0].message)
        assert '2.14.0' in message and '3.0' in message
        assert 'Используйте новое' in message

    def test_builtin_source_warns(self):
        with pytest.warns(DeprecationWarning, match='own'):
            assert normalize_source('builtin') == 'own'

    def test_own_source_is_silent(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)
            assert normalize_source('own') == 'own'
            assert get_questions(['math'], count=1, source='own')
