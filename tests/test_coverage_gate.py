# -*- coding: utf-8 -*-
"""Гейт покрытия (`scripts/coverage_gate.py`) — сам по себе инструмент, его тоже проверяем.

Гейт, который всегда зелёный, хуже отсутствующего: он создаёт уверенность.
Поэтому проверяем и «порог выдержан», и «провал виден», и внятность ошибок.
"""

import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'scripts', 'coverage_gate.py')


def _gate():
    spec = importlib.util.spec_from_file_location('coverage_gate', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _gate()


def make_report(files: dict, total: float = 95.0) -> dict:
    return {
        'totals': {'percent_covered': total},
        'files': {
            name: {'summary': {'percent_covered': percent}}
            for name, percent in files.items()
        },
    }


class TestThresholds:
    def test_clean_report_has_no_failures(self):
        report = make_report({'kremle_detect/storage.py': 98})
        assert gate.check(report, 90, {'kremle_detect/storage.py': 95}) == []

    def test_low_file_is_reported_even_when_total_is_green(self):
        # Ровно тот случай, ради которого гейт и нужен
        report = make_report({'kremle_detect/demo.py': 74}, total=94)
        failures = gate.check(report, 90, {'kremle_detect/demo.py': 95})
        assert [(name, round(actual), threshold) for name, actual, threshold in failures] == [
            ('kremle_detect/demo.py', 74, 95),
        ]

    def test_overall_threshold_is_checked(self):
        report = make_report({}, total=88)
        failures = gate.check(report, 90, {})
        assert [name for name, _, _ in failures] == ['всё вместе']

    def test_missing_file_in_report_is_a_failure(self):
        failures = gate.check(make_report({}), None, {'kremle_detect/storage.py': 90})
        assert 'нет в отчёте' in failures[0][0]

    def test_exact_threshold_passes(self):
        report = make_report({'kremle_detect/storage.py': 95})
        assert gate.check(report, None, {'kremle_detect/storage.py': 95}) == []


class TestConfig:
    def test_project_config_is_readable_and_not_empty(self):
        overall, targets = gate._load_targets(os.path.join(ROOT, 'pyproject.toml'))
        assert overall == 90
        assert targets['kremle_detect/storage.py'] == 95
        # сами себя не обманываем: порогов меньше двух — это уже не «по модулям»
        assert len(targets) >= 3

    def test_unknown_file_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit):
            gate._load_targets(str(tmp_path / 'nope.toml'))


class TestCli:
    def test_missing_report_is_exit_code_2(self, tmp_path):
        code = gate.main(['--report', str(tmp_path / 'nope.json'),
                          '--config', os.path.join(ROOT, 'pyproject.toml')])
        assert code == 2

    def test_failure_is_exit_code_1(self, tmp_path):
        report = tmp_path / 'coverage.json'
        report.write_text(json.dumps(make_report({'kremle_detect/demo.py': 10})),
                          encoding='utf-8')
        assert gate.main(['--report', str(report),
                          '--config', os.path.join(ROOT, 'pyproject.toml')]) == 1

    def test_success_is_exit_code_0(self, tmp_path):
        report = tmp_path / 'coverage.json'
        report.write_text(json.dumps(make_report({
            'kremle_detect/demo.py': 99,
            'kremle_detect/storage.py': 99,
            'kremle_detect/integrations/fastapi_ext.py': 99,
            'kremle_detect/session.py': 99,
            'kremle_detect/detector.py': 100,
        }, total=95)), encoding='utf-8')
        assert gate.main(['--report', str(report),
                          '--config', os.path.join(ROOT, 'pyproject.toml')]) == 0
