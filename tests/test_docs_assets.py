# -*- coding: utf-8 -*-
"""Статика сайта документации: триколор и гимн.

Сайт — это `mkdocs` и три файла в `docs/assets`: тема, кнопка «послушать гимн»
и бандл виджета. Проверяем то, что легко сломать руками: файл забыли положить
рядом с конфигом, ноты в плеере разъехались, цвета «перекрасили» не туда.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'
ASSETS = DOCS / 'assets'

def _list(name):
    """Значения из `extra_css:`/`extra_javascript:` в mkdocs.yml.

    Полный YAML-парсер тут не нужен и даже вреден: в конфиге есть
    `!!python/object/apply` для слагификации, который обычный `safe_load`
    не переварит.
    """
    text = (ROOT / 'mkdocs.yml').read_text(encoding='utf-8')
    block = re.search(rf'^{name}:\n((?:\s+-\s+.*\n)+)', text, re.M)
    if not block:
        return []
    return [line.split('-', 1)[1].strip() for line in block.group(1).splitlines()]


class TestSiteAssets:
    def test_extra_css_exists(self):
        for name in _list('extra_css'):
            assert (DOCS / name).is_file(), f'нет файла темы: {name}'

    def test_extra_javascript_exists(self):
        for name in _list('extra_javascript'):
            assert (DOCS / name).is_file(), f'нет файла скрипта: {name}'

    def test_tricolor_is_white_blue_red(self):
        css = (ASSETS / 'tricolor.css').read_text(encoding='utf-8').lower()
        assert '#0039a6' in css, 'синий флага'
        assert '#d52b1e' in css, 'красный флага'
        assert '#ffffff' in css, 'белый флага'

    def test_demo_page_uses_theme_and_anthem(self):
        html = (DOCS / 'demo.html').read_text(encoding='utf-8')
        assert 'assets/tricolor.css' in html
        assert 'assets/anthem.js' in html


class TestAnthem:
    def _notes(self):
        js = (ASSETS / 'anthem.js').read_text(encoding='utf-8')
        block = re.search(r'var NOTES = \[(.*?)\n  \]', js, re.S)
        assert block, 'таблица нот не найдена'
        rows = block.group(1).strip().rstrip(',')
        parsed = json.loads('[' + rows + ']')
        return js, parsed

    def test_melody_is_there(self):
        _, notes = self._notes()
        assert len(notes) >= 70, 'мелодия короче, чем гимн'

    def test_notes_are_valid(self):
        _, notes = self._notes()
        for beat, length, midi in notes:
            assert 0 <= beat
            assert length > 0
            # Мелодия гимна: от до первой октавы до фа второй
            assert 55 <= midi <= 84

    def test_notes_go_forward(self):
        _, notes = self._notes()
        beats = [beat for beat, _, _ in notes]
        assert beats == sorted(beats), 'ноты идут не по порядку'
        # Один куплет с припевом: около минуты при темпе 76
        assert beats[-1] > 60, 'мелодия обрывается на середине'

    def test_ends_on_the_tonic(self):
        """«Славься, страна!» заканчивается на тонике — это не оборванная фраза."""
        _, notes = self._notes()
        assert notes[-1][2] == 72, notes[-1]

    def test_opening_is_the_anthem(self):
        """Первые такты — «Россия — священная наша держава».

        Регрессия: в первой версии плеера мелодия бралась из случайного MIDI
        и на гимн не походила. Здесь зафиксировано начало из партитуры
        (партия корнета 1 в B♭, транспонированная в до мажор).
        """
        _, notes = self._notes()
        opening = [midi for _, _, midi in notes[:8]]
        assert opening == [72, 67, 72, 67, 69, 71, 64, 64], opening

    def test_melody_is_diatonic(self):
        _, notes = self._notes()
        for _, _, midi in notes:
            assert midi % 12 in {0, 2, 4, 5, 7, 9, 11}, midi

    def test_tempo_is_official(self):
        js, _ = self._notes()
        assert 'var BPM = 76' in js, 'гимн исполняется в темпе 76'

    def test_composer_is_credited(self):
        js = (ASSETS / 'anthem.js').read_text(encoding='utf-8')
        assert 'Александрова' in js
        assert 'Михалкова' in js

    def test_no_external_audio(self):
        """Никаких чужих mp3: только синтез в браузере."""
        js = (ASSETS / 'anthem.js').read_text(encoding='utf-8')
        assert '.mp3' not in js
        assert 'AudioContext' in js
