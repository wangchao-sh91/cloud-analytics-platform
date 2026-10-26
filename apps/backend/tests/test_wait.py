from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from app.wait import WaitError, get_job, job_complete, poll


def test_job_conditions():
    assert not job_complete({})
    assert job_complete({'status': {'conditions': [{'type': 'Complete', 'status': 'True'}]}})
    for condition in ['Failed', 'FailureTarget']:
        with pytest.raises(WaitError, match='failed'):
            job_complete({'status': {'conditions': [{'type': condition, 'status': 'True'}]}})


def test_delayed_success_and_timeout():
    with patch('app.wait.time.sleep'), patch('app.wait.time.monotonic', side_effect=[0, 0, 1]):
        with patch('builtins.print'):
            poll(iter([False, False, True]).__next__, 5, 'database')
    with patch('app.wait.time.monotonic', side_effect=[0, 2]):
        with pytest.raises(WaitError, match='Timed out'):
            poll(lambda: False, 1, 'database')


@pytest.mark.parametrize('code,result', [(404, False), (503, False), (403, None), (401, None)])
def test_kubernetes_errors(code, result):
    with patch('app.wait.Path.read_text', return_value='test'), patch.dict('os.environ', {'MIGRATION_JOB': 'test'}), patch('app.wait.ssl.create_default_context'), patch('app.wait.urlopen', side_effect=HTTPError('https://test', code, 'error', {}, None)):
        if result is None:
            with pytest.raises(WaitError, match='authorized'):
                get_job()
        else:
            assert get_job() is result


def test_failed_job_never_checks_schema():
    with patch('sys.argv', ['wait', 'migration']), patch('app.wait.get_job', side_effect=WaitError('Migration Job failed')), patch('app.wait.database_ready') as schema:
        from app.wait import main
        assert main() == 1
        schema.assert_not_called()


def test_transient_network_error():
    with patch('app.wait.Path.read_text', return_value='test'), patch.dict('os.environ', {'MIGRATION_JOB': 'test'}), patch('app.wait.ssl.create_default_context'), patch('app.wait.urlopen', side_effect=URLError('temporary')):
        assert not get_job()
