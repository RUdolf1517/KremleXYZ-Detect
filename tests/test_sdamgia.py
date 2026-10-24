# -*- coding: utf-8 -*-
"""Тесты провайдера вопросов «Решу ЕГЭ»: разбор, кеш, атрибуция, fallback."""

import json
import time

import pytest

from kremle_detect import CaptchaEngine, get_questions, validate_questions
from kremle_detect.questions import sdamgia
from kremle_detect.questions.sdamgia import (
    PROBE_WINDOW, SOURCE, build_distractors, build_question, cache_age, cache_path,
    discover_problem_ids, fetch_questions, load_cached_questions, parse_problem_html,
    parse_problem_ids, read_cache, sync, variant_hrefs, write_cache,
)


class TestParseProblemHtml:
    def test_condition_and_answer(self, sdamgia_html):
        parsed = parse_problem_html(sdamgia_html)
        assert parsed is not None
        assert 'На экзамен вынесено 60 вопросов' in parsed['condition']
        assert 'Решением' not in parsed['condition']   # второе pbody — решение
        assert parsed['answer'] == '0,95'

    def test_only_first_pbody_is_condition(self, sdamgia_html):
        parsed = parse_problem_html(sdamgia_html)
        assert 'Андрей выучил 60 − 3 = 57' not in parsed['condition']

    def test_garbage_html(self):
        assert parse_problem_html('<html><body>ничего</body></html>') is None

    def test_missing_answer(self):
        html = '<div class="prob_maindiv"><div class="pbody">Условие</div></div>'
        assert parse_problem_html(html) is None

    def test_whitespace_collapsed(self):
        html = ('<div class="prob_maindiv"><div class="pbody">Много\n\n   пробелов'
                '</div><div class="answer">Ответ:  42</div></div>')
        parsed = parse_problem_html(html)
        assert parsed['condition'] == 'Много пробелов'
        assert parsed['answer'] == '42'


class TestDistractors:
    def test_numeric_with_comma(self):
        distractors = build_distractors('0,95')
        assert distrators_ok(distractors, '0,95')

    def test_integer(self):
        optional = build_distractors('42')
        assert optional is not None and len(optional) == 3
        assert '42' not in optional

    def test_negative(self):
        optional = build_distractors('-3')
        assert optional is not None and len(set(optional)) == 3

    def test_text_answer_unsupported(self):
        """Текстовый ответ нельзя превратить в варианты — задание пропускаем."""
        assert build_distractors('Москва') is None

    def test_decimal_precision(self):
        distractors = build_distractors('0,5')
        assert distractors is not None
        assert all(',' in d for d in distractors)   # формат сохраняется


def distrators_ok(distractors, answer):
    return distractors is not None and len(distractors) == 3 and answer not in distractors


class TestBuildQuestion:
    def test_shape(self):
        question = build_question(
            {'condition': 'Сколько будет 2+2?', 'answer': '4'},
            category='math', problem_id='1001',
            base_url='https://math-ege.sdamgia.ru',
        )
        assert question is not None
        assert question['q'] == 'Сколько будет 2+2?'
        assert len(question['opts']) == 4
        assert question['opts'][question['ans']] == '4'
        assert question['problem_id'] == '1001'
        assert question['source']['name'] == 'РешуЕГЭ'
        assert question['source']['url'].endswith('/problem?id=1001')
        assert 'Гущин' in question['source']['author']

    def test_question_is_valid_for_engine(self):
        question = build_question(
            {'condition': 'Вопрос?', 'answer': '7'},
            category='math', problem_id='1', base_url='https://example.test',
        )
        validate_questions([question])   # не должно бросить

    def test_too_long_condition_skipped(self):
        question = build_question(
            {'condition': 'а' * 500, 'answer': '4'},
            category='math', problem_id='1', base_url='https://example.test',
        )
        assert question is None

    def test_text_answer_skipped(self):
        assert build_question(
            {'condition': 'Город?', 'answer': 'Москва'},
            category='math', problem_id='1', base_url='https://example.test',
        ) is None

    def test_answer_index_matches_option(self):
        for _ in range(20):
            question = build_question(
                {'condition': 'Q?', 'answer': '12'},
                category='math', problem_id='1', base_url='https://example.test',
            )
            assert question['opts'][question['ans']] == '12'
            assert len(set(question['opts'])) == 4


class TestCache:
    def test_write_read(self, tmp_path):
        questions = [{'q': 'Q?', 'opts': ['a', 'b'], 'ans': 0, 'category': 'math'}]
        path = write_cache('math', questions, cache_dir=str(tmp_path))
        assert path == cache_path('math', str(tmp_path))

        data = read_cache('math', str(tmp_path))
        assert data['questions'] == questions
        assert data['source']['name'] == SOURCE['name']
        assert data['fetched_at'] <= time.time()

    def test_missing(self, tmp_path):
        assert read_cache('math', str(tmp_path)) is None
        assert cache_age('math', str(tmp_path)) is None

    def test_broken_json(self, tmp_path):
        path = cache_path('math', str(tmp_path))
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{ not json')
        assert read_cache('math', str(tmp_path)) is None

    def test_atomic_write_leaves_no_tmp(self, tmp_path):
        write_cache('math', [], cache_dir=str(tmp_path))
        leftovers = [p for p in tmp_path.iterdir() if p.name.endswith('.tmp')]
        assert leftovers == []

    def test_load_cached_questions(self, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=3)
        write_sdamgia_cache('physics', count=2)
        qs = load_cached_questions(['math', 'physics'], cache_dir=str(tmp_path))
        assert len(qs) == 5

    def test_stale_cache_still_used(self, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=2, fetched_at=time.time() - 400 * 86400)
        qs = load_cached_questions(['math'], cache_dir=str(tmp_path))
        assert len(qs) == 2   # лучше старые вопросы, чем пустой банк

    def test_env_cache_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv('KREMLE_CACHE_DIR', str(tmp_path / 'custom'))
        assert sdamgia.default_cache_dir().endswith('custom')


class TestFetch:
    def test_fetch_with_injected_get(self, sdamgia_html):
        calls = []

        def fake_get(url):
            calls.append(url)
            return sdamgia_html

        questions = fetch_questions('math', limit=2, problem_ids=['1001'], get=fake_get)
        assert len(questions) == 1
        assert calls == ['https://math-ege.sdamgia.ru/problem?id=1001']
        assert questions[0]['problem_id'] == '1001'

    def test_fetch_stops_at_limit(self, sdamgia_html):
        questions = fetch_questions(
            'math', limit=2, problem_ids=['1', '2', '3'], get=lambda url: sdamgia_html,
        )
        assert len(questions) == 2

    def test_network_error_skipped(self):
        def broken(url):
            from urllib.error import URLError
            raise URLError('offline')

        assert fetch_questions('math', limit=2, problem_ids=['1'], get=broken) == []

    def test_unknown_category(self):
        with pytest.raises(ValueError, match='Нет источника'):
            fetch_questions('chemistry', limit=1, get=lambda url: '')

    def test_zero_limit(self):
        assert fetch_questions('math', limit=0, get=lambda url: '') == []

    def test_ids_from_general_api(self, sdamgia_html):
        """id в newapi/general — id варианта, задания берутся со страницы варианта."""
        general = json.dumps({'larinVariants': [{'id': 550, 'number': '550', 'href': '/BZWpu'}]})
        variant_html = ('<div><a href="/problem?id=1001">1</a>'
                        '<a href="/problem?id=1002">2</a></div>')
        requested = []

        def fake_get(url):
            requested.append(url)
            if url.endswith('/newapi/general'):
                return general
            if url.endswith('/BZWpu'):
                return variant_html
            return sdamgia_html

        fetch_questions('math', limit=2, get=fake_get)
        assert 'https://math-ege.sdamgia.ru/newapi/general' in requested
        assert 'https://math-ege.sdamgia.ru/BZWpu' in requested
        assert [u for u in requested if 'problem?id=' in u] == [
            'https://math-ege.sdamgia.ru/problem?id=1001',
            'https://math-ege.sdamgia.ru/problem?id=1002',
        ]


class TestSync:
    def test_sync_writes_cache(self, tmp_path, sdamgia_html):
        result = sync(['math'], limit=1, cache_dir=str(tmp_path),
                      problem_ids=['1001'], get=lambda url: sdamgia_html)
        assert result == {'math': 1}
        assert len(read_cache('math', str(tmp_path))['questions']) == 1

    def test_sync_does_not_overwrite_on_failure(self, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=2)
        result = sync(['math'], limit=2, cache_dir=str(tmp_path), get=lambda url: '<html></html>')
        assert result == {}
        assert len(read_cache('math', str(tmp_path))['questions']) == 2

    def test_sync_unknown_category_skipped(self, tmp_path):
        result = sync(['chemistry'], limit=1, cache_dir=str(tmp_path), get=lambda url: '')
        assert result == {}


class TestParseProblemIds:
    def test_extracts_unique(self):
        html = ('<a href="/problem?id=1001">1</a><a href="/problem?id=1001">1</a>'
                '<a href="/problem?id=1002">2</a>')
        assert parse_problem_ids(html) == ['1001', '1002']

    def test_limit(self):
        html = ''.join(f'<a href="/problem?id={i}">x</a>' for i in range(10))
        assert len(parse_problem_ids(html, limit=3)) == 3

    def test_empty(self):
        assert parse_problem_ids('') == []
        assert parse_problem_ids(None) == []

    def test_ignores_test_links(self):
        assert parse_problem_ids('<a href="/test?id=93508173">v</a>') == []


class TestVariantHrefs:
    def test_all_sections(self):
        general = {
            'larinVariants': [{'id': 1, 'href': '/aaa'}],
            'probVariants': [{'id': 2, 'href': '/bbb'}],
            'ourVariants': [{'id': 3}],
        }
        assert variant_hrefs(general) == ['/aaa', '/bbb']

    def test_empty(self):
        assert variant_hrefs({}) == []


class TestDiscover:
    def test_uses_variant_pages(self):
        general = json.dumps({'larinVariants': [{'href': '/X'}]})
        html = {'/newapi/general': general, '/X': '<a href="/problem?id=7">7</a>'}

        ids = discover_problem_ids('math', limit=1, get=lambda url: html[
            url.replace('https://math-ege.sdamgia.ru', '')
        ])
        assert ids == ['7']

    def test_falls_back_to_seed_window(self):
        def offline(url):
            from urllib.error import URLError
            raise URLError('offline')

        ids = discover_problem_ids('math', limit=5, get=offline)
        assert ids == ['1001', '1002', '1003', '1004', '1005']

    def test_seed_window_limits_probe(self):
        def offline(url):
            from urllib.error import URLError
            raise URLError('offline')

        ids = discover_problem_ids('math', limit=10_000, get=offline)
        assert len(ids) == PROBE_WINDOW


class TestGetQuestionsSource:
    def test_builtin(self):
        qs = get_questions(['math'], count=3, source='builtin')
        assert len(qs) == 3
        assert all('source' not in q for q in qs)

    def test_auto_without_cache_is_builtin(self):
        qs = get_questions(['math'], count=3, source='auto')
        assert len(qs) == 3

    def test_auto_with_cache_uses_remote(self, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=4)
        qs = get_questions(['math'], source='auto', cache_dir=str(tmp_path))
        assert len(qs) == 4
        assert qs[0]['source']['name'] == 'РешуЕГЭ'
        assert all('problem_id' in q for q in qs)

    def test_sdamgia_without_cache_is_empty(self):
        assert get_questions(['math'], source='sdamgia') == []

    def test_invalid_source(self):
        with pytest.raises(ValueError, match='source должен быть'):
            get_questions(['math'], source='internet')

    def test_attribution_in_challenge(self, tmp_path, write_sdamgia_cache):
        write_sdamgia_cache('math', count=5)
        engine = CaptchaEngine(
            categories=['math'], question_count=3, max_errors=1, secret='s',
            questions_source='auto',
        )
        # engine читает кеш из KREMLE_CACHE_DIR (см. conftest)
        import shutil
        from kremle_detect.questions.sdamgia import default_cache_dir
        target = default_cache_dir()
        import os
        os.makedirs(target, exist_ok=True)
        shutil.copy(cache_path('math', str(tmp_path)), os.path.join(target, 'sdamgia-math.json'))

        ch = engine.create_challenge()
        data = ch.to_dict()
        assert data['attribution'] == 'Задания: РешуЕГЭ'
        assert data['sources'][0]['url']
        assert all(q['source']['name'] == 'РешуЕГЭ' for q in data['questions'])
        assert 'ans' not in data['questions'][0]
