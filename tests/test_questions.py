# -*- coding: utf-8 -*-
"""Тесты банка вопросов."""

import pytest

from kremle_detect import get_questions, validate_questions, ALL_CATEGORY_NAMES, CATEGORIES


class TestGetQuestions:
    def test_all_categories(self):
        qs = get_questions(shuffle=False)
        assert len(qs) == 60  # 4 категории × 15

    def test_single_category(self):
        qs = get_questions(categories=['math'], shuffle=False)
        assert all(q['category'] == 'math' for q in qs)
        assert len(qs) == 15

    def test_multiple_categories(self):
        qs = get_questions(categories=['physics', 'russian'], shuffle=False)
        cats = {q['category'] for q in qs}
        assert cats == {'physics', 'russian'}
        assert len(qs) == 30

    def test_count(self):
        qs = get_questions(count=5)
        assert len(qs) == 5

    def test_count_exceeds_pool(self):
        qs = get_questions(categories=['math'], count=100)
        assert len(qs) == 15  # не больше чем есть

    def test_shuffle(self):
        qs1 = get_questions(shuffle=True)
        qs2 = get_questions(shuffle=True)
        # Хоть один порядок должен отличаться (крайне вероятно при 60 вопросах)
        texts1 = [q['q'] for q in qs1]
        texts2 = [q['q'] for q in qs2]
        # Не гарантируем отличие, но проверяем что вернулись те же вопросы
        assert set(texts1) == set(texts2)

    def test_invalid_category(self):
        with pytest.raises(ValueError, match='Неизвестная категория'):
            get_questions(categories=['nonexistent'])

    def test_question_format(self):
        qs = get_questions(shuffle=False)
        for q in qs:
            assert 'q' in q and isinstance(q['q'], str)
            assert 'opts' in q and isinstance(q['opts'], list)
            assert 'ans' in q and isinstance(q['ans'], int)
            assert 'category' in q
            assert 0 <= q['ans'] < len(q['opts'])
            assert len(q['opts']) >= 2


class TestCategories:
    def test_all_category_names(self):
        assert set(ALL_CATEGORY_NAMES) == {'math', 'physics', 'russian', 'literature'}

    def test_categories_dict(self):
        for name, qs in CATEGORIES.items():
            assert len(qs) == 15
            for q in qs:
                assert 'q' in q
                assert 'opts' in q
                assert 'ans' in q


class TestValidateQuestions:
    def test_valid(self):
        validate_questions([
            {'q': 'Q?', 'opts': ['A', 'B'], 'ans': 0},
            {'q': 'Q2?', 'opts': ['X', 'Y', 'Z'], 'ans': 2},
        ])

    def test_not_dict(self):
        with pytest.raises(ValueError, match='ожидается dict'):
            validate_questions(['not a dict'])

    def test_missing_q(self):
        with pytest.raises(ValueError, match='"q"'):
            validate_questions([{'opts': ['A', 'B'], 'ans': 0}])

    def test_empty_q(self):
        with pytest.raises(ValueError, match='"q"'):
            validate_questions([{'q': '', 'opts': ['A', 'B'], 'ans': 0}])

    def test_too_few_opts(self):
        with pytest.raises(ValueError, match='opts'):
            validate_questions([{'q': 'Q?', 'opts': ['A'], 'ans': 0}])

    def test_ans_out_of_range(self):
        with pytest.raises(ValueError, match='ans'):
            validate_questions([{'q': 'Q?', 'opts': ['A', 'B'], 'ans': 5}])

    def test_ans_negative(self):
        with pytest.raises(ValueError, match='ans'):
            validate_questions([{'q': 'Q?', 'opts': ['A', 'B'], 'ans': -1}])
