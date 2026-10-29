import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

spec = importlib.util.spec_from_file_location('check_code', Path(__file__).parents[1] / 'check_code.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def test_unit_tests_do_not_use_database_or_wait_for_it(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'must-not-be-used')
    monkeypatch.setenv('TEST_DATABASE_URL', 'must-not-be-used')
    with patch.object(checks, 'wait_for_database') as wait, patch.object(checks.subprocess, 'run') as run:
        checks.run('unit', 1)
    wait.assert_not_called()
    env = run.call_args.kwargs['env']
    assert 'DATABASE_URL' not in env and 'TEST_DATABASE_URL' not in env
    assert run.call_args.kwargs['check']


def test_backend_never_falls_back_to_application_database(monkeypatch):
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'must-not-be-used')
    with patch.object(checks.subprocess, 'run') as run:
        with pytest.raises(ValueError, match='Set TEST_DATABASE_URL'):
            checks.run('all', 1)
    run.assert_not_called()


def test_backend_uses_explicit_database_and_correct_working_directory(monkeypatch):
    url = 'postgresql+psycopg://test:temporary@localhost/cap_test'
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    monkeypatch.setenv('DATABASE_URL', 'must-not-be-used')
    with patch.object(checks, 'wait_for_database') as wait, patch.object(checks.subprocess, 'run') as run:
        checks.run('backend', 1)
    wait.assert_called_once_with(url, 1)
    assert run.call_args.kwargs['cwd'] == checks.BACKEND
    assert run.call_args.kwargs['env']['DATABASE_URL'] == url
    assert run.call_args.kwargs['env']['TEST_DATABASE_URL'] == url


def test_pytest_failure_is_not_swallowed():
    with patch.object(checks.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['pytest'])):
        with pytest.raises(subprocess.CalledProcessError):
            checks.run('unit', 1)


@pytest.mark.parametrize('exit_code', [1, 4])
def test_entrypoint_preserves_pytest_failure_exit_code(exit_code):
    with patch('sys.argv', ['check_code.py', 'unit']):
        with patch.object(checks.subprocess, 'run', side_effect=subprocess.CalledProcessError(exit_code, ['pytest'])):
            assert checks.main() == exit_code


def test_database_timeout_does_not_run_tests(monkeypatch):
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql+psycopg://test@localhost/cap_test')
    with patch.object(checks, 'wait_for_database', side_effect=ValueError('timeout')):
        with patch.object(checks.subprocess, 'run') as run:
            with pytest.raises(ValueError, match='timeout'):
                checks.run('backend', 1)
    run.assert_not_called()


@pytest.mark.parametrize('version', [160000, 180000])
def test_wrong_postgres_major_version_is_rejected(version):
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value = version
    with patch('sqlalchemy.create_engine', return_value=engine):
        with pytest.raises(ValueError, match='PostgreSQL 17'):
            checks.wait_for_database('postgresql+psycopg://test@localhost/cap_test', 1)
    engine.dispose.assert_called_once()
