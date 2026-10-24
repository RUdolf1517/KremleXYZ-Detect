# -*- coding: utf-8 -*-
"""Общие фикстуры тестов."""

import pytest

from kremle_detect.questions import sdamgia


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """
    Тесты не должны видеть настоящий кеш вопросов в ~/.cache и не должны
    в него писать.
    """
    cache_dir = tmp_path / 'kremle-cache'
    monkeypatch.setenv('KREMLE_CACHE_DIR', str(cache_dir))
    yield cache_dir


@pytest.fixture
def sdamgia_html():
    """Страница задания «Решу ЕГЭ» (структура портала, обрезанная до нужного)."""
    return '''<!DOCTYPE html>
<html><body>
<div class="header">РЕШУ ЕГЭ</div>
<div class="prob_maindiv">
  <span class="prob_nums">№ 4 &nbsp; 1001</span>
  <div class="pbody">
    На экзамен вынесено 60 вопросов, Андрей не выучил 3 из них.
    Найдите вероятность того, что ему попадётся выученный вопрос.
    <img src="/formula/abc.svg">
  </div>
  <div class="pbody">
    Решение. Андрей выучил 60 − 3 = 57 вопросов.
  </div>
  <div class="answer">Ответ: 0,95</div>
  <div class="minor"><a href="/problem?id=1002">1002</a></div>
</div>
<div class="footer">СДАМ ГИА</div>
</body></html>'''


@pytest.fixture
def write_sdamgia_cache(tmp_path):
    """Пишет кеш вопросов «Решу ЕГЭ» в изолированный каталог."""
    def _write(category='math', count=4, fetched_at=None):
        questions = [
            {
                'q': f'Задание {i} из банка',
                'opts': ['10', '20', '30', '40'],
                'ans': 0,
                'category': category,
                'problem_id': str(1000 + i),
                'source': {
                    'name': 'РешуЕГЭ',
                    'url': f'https://math-ege.sdamgia.ru/problem?id={1000 + i}',
                    'author': 'Д. Д. Гущин и авторы портала',
                },
            }
            for i in range(count)
        ]
        data = {'category': category, 'fetched_at': fetched_at, 'questions': questions}
        sdamgia.write_cache(category, questions, cache_dir=str(tmp_path))
        if fetched_at is not None:
            import json
            path = sdamgia.cache_path(category, str(tmp_path))
            with open(path, encoding='utf-8') as f:
                payload = json.load(f)
            payload['fetched_at'] = fetched_at
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
        return questions
    return _write
