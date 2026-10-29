import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest
import yaml

from scripts import ci_release as release


@pytest.fixture
def data():
    return release.identity(
        {'number': 42, 'pull_request': {'head': {'sha': 'a' * 40}}},
        {'GITHUB_REPOSITORY': 'Test-Owner/cloud-analytics-platform', 'GITHUB_EVENT_NAME': 'pull_request',
         'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1'}, '0.3.0',
    )


def test_pr_metadata_uses_full_head_and_normalizes_owner(data):
    assert data['images']['backend']['tag'] == 'a' * 40
    assert data['chart_version'] == '0.3.0-sha' + 'a' * 40
    assert data['images']['frontend']['repository'] == 'ghcr.io/test-owner/cap-frontend'


def test_main_uses_actual_merge_sha_and_same_formula(data):
    event = {'ref': 'refs/heads/main', 'after': 'b' * 40}
    env = {'GITHUB_REPOSITORY': data['repository'], 'GITHUB_EVENT_NAME': 'push',
           'GITHUB_RUN_ID': '101', 'GITHUB_RUN_ATTEMPT': '1'}
    result = release.identity(event, env, '0.3.0')
    assert result['source_sha'] == 'b' * 40
    assert result['images']['backend']['tag'] == 'b' * 40
    assert result['chart_version'] == '0.3.0-sha' + 'b' * 40
    assert result['channel'] == 'main' and result['pr'] is None
    assert result['chart_version'] != data['chart_version']


def test_retry_does_not_change_versions(data):
    event = {'number': 42, 'pull_request': {'head': {'sha': data['source_sha']}}}
    result = release.identity(event, {'GITHUB_REPOSITORY': data['repository'],
                              'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_RUN_ID': '200',
                              'GITHUB_RUN_ATTEMPT': '3'}, '0.3.0')
    assert result['chart_version'] == data['chart_version']
    assert result['images'] == data['images']


def test_metadata_checks_actual_checkout_and_rejects_untracked_source(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'charts/cap').mkdir(parents=True)
    (repo / 'charts/cap/Chart.yaml').write_text('name: cap\nversion: 0.3.0\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=CI Test', '-c', 'user.email=ci@example.invalid',
                    'commit', '-qm', 'fixture'], cwd=repo, check=True)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'ref': 'refs/heads/main', 'after': sha}))
    monkeypatch.setattr(release, 'ROOT', repo)
    for key, value in {'GITHUB_EVENT_PATH': str(event), 'GITHUB_REPOSITORY': 'owner/repo',
                       'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ID': '100', 'GITHUB_RUN_ATTEMPT': '1',
                       'GITHUB_OUTPUT': str(tmp_path / 'outputs')}.items():
        monkeypatch.setenv(key, value)
    target = tmp_path / 'metadata.json'
    release.metadata(target)
    assert json.loads(target.read_text())['source_sha'] == sha
    assert 'source_sha=' + sha in (tmp_path / 'outputs').read_text()
    (repo / 'apps').mkdir()
    (repo / 'apps/uncommitted.py').write_text('print(1)\n')
    with pytest.raises(ValueError, match='Commit source changes'):
        release.metadata(target)
    event.write_text(json.dumps({'ref': 'refs/heads/main', 'after': 'b' * 40}))
    with pytest.raises(ValueError, match='Checkout does not match'):
        release.metadata(target)


@pytest.mark.parametrize('sha', ['HEAD', 'abc', 'a' * 39, 'x' * 40, 'a' * 40 + '\n'])
def test_invalid_source_sha_fails(sha):
    with pytest.raises(ValueError):
        release.identity({'number': 1, 'pull_request': {'head': {'sha': sha}}}, {
            'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_NAME': 'pull_request',
            'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1'}, '0.3.0')


@pytest.mark.parametrize('code', [401, 403, 429, 500])
def test_registry_errors_are_not_treated_as_absent(code):
    registry = release.Registry()
    registry.opener = MagicMock()
    registry.opener.open.side_effect = HTTPError('https://ghcr.io/', code, 'failure', {}, None)
    with pytest.raises(ValueError, match=f'HTTP {code}'):
        registry.request('https://ghcr.io/', missing_ok=True)


def test_only_manifest_404_can_mean_absent():
    registry = release.Registry()
    registry.opener = MagicMock()
    registry.opener.open.side_effect = HTTPError('https://ghcr.io/', 404, 'missing', {}, None)
    assert registry.request('https://ghcr.io/', missing_ok=True) is None
    with pytest.raises(ValueError, match='HTTP 404'):
        registry.request('https://ghcr.io/')


def test_network_failure_is_not_treated_as_absent():
    registry = release.Registry()
    registry.opener = MagicMock()
    registry.opener.open.side_effect = URLError('offline')
    with pytest.raises(ValueError, match='absence could not be established'):
        registry.request('https://ghcr.io/', missing_ok=True)


def image_registry(data, architecture='amd64', revision=None):
    config = json.dumps({'os': 'linux', 'architecture': architecture, 'config': {'Labels': {
        **release.expected_source(data), 'org.opencontainers.image.revision': revision or data['source_sha'],
    }}}).encode()
    manifest = json.dumps({'config': {'digest': release.digest(config)}}).encode()
    registry = release.Registry()
    registry.read = MagicMock(side_effect=lambda repo, kind, ref, **kw: manifest if kind == 'manifests' else config)
    return registry, release.digest(manifest)


def test_existing_image_verifies_labels_architecture_and_digest(data):
    registry, expected = image_registry(data)
    assert registry.image(data['images']['backend'], data) == expected


def test_docker_image_index_selects_amd64_and_ignores_attestation(data):
    config = json.dumps({'os': 'linux', 'architecture': 'amd64',
                         'config': {'Labels': release.expected_source(data)}}).encode()
    child = json.dumps({'config': {'digest': release.digest(config)}}).encode()
    index = json.dumps({'manifests': [
        {'digest': release.digest(child), 'platform': {'os': 'linux', 'architecture': 'amd64'}},
        {'digest': 'sha256:' + '0' * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'}},
    ]}).encode()
    registry = release.Registry()

    def read(repo, kind, reference, **kwargs):
        if kind == 'blobs':
            return config
        return child if reference.startswith('sha256:') else index

    registry.read = read
    assert registry.image(data['images']['backend'], data) == release.digest(index)


@pytest.mark.parametrize('kwargs', [{'architecture': 'arm64'}, {'revision': 'b' * 40}])
def test_existing_image_mismatch_is_fatal(data, kwargs):
    registry, _ = image_registry(data, **kwargs)
    with pytest.raises(ValueError, match='mismatch'):
        registry.image(data['images']['backend'], data)


def test_blob_content_must_match_descriptor():
    registry = release.Registry()
    registry.read = MagicMock(return_value=b'changed')
    with pytest.raises(ValueError, match='digest mismatch'):
        registry.blob('owner/image', {'digest': release.digest(b'original')})


def test_partial_image_publication_resumes_only_missing_image(data, monkeypatch):
    registry = MagicMock()
    registry.image.side_effect = ['sha256:' + '1' * 64, None, 'sha256:' + '2' * 64]
    monkeypatch.setenv('GITHUB_TOKEN', 'dummy-test-token')
    monkeypatch.setenv('GITHUB_ACTOR', 'collaborator')
    commands = []
    monkeypatch.setattr(release, 'run', lambda args, **kwargs: commands.append(args))
    release.publish_images(data, registry)
    builds = [command for command in commands if command[:2] == ['docker', 'build']]
    assert len(builds) == 1 and builds[0][-1].endswith('/frontend')
    assert not any('cap-backend:' in arg for command in commands for arg in command)


def test_image_failure_does_not_continue_publication(data, monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'dummy-test-token')
    monkeypatch.setenv('GITHUB_ACTOR', 'collaborator')
    registry = MagicMock()
    registry.image.return_value = None
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[:2] == ['docker', 'build']:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(release, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        release.publish_images(data, registry)
    assert not any(command[:2] == ['docker', 'push'] for command in commands)
    assert registry.image.call_count == 1


def test_partial_images_cannot_publish_chart_or_leave_success_file(data, tmp_path, monkeypatch):
    manifest = tmp_path / 'release.json'
    manifest.write_text('old success')
    registry = MagicMock()
    registry.image.return_value = None
    monkeypatch.setenv('BACKEND_DIGEST', 'sha256:' + '1' * 64)
    with pytest.raises(ValueError, match='missing or differs'):
        release.publish_chart(data, registry, manifest)
    registry.chart.assert_not_called()
    assert not manifest.exists()


def test_reused_chart_outputs_complete_manifest_without_push(data, tmp_path, monkeypatch):
    registry = MagicMock()
    registry.image.side_effect = ['sha256:' + '1' * 64, 'sha256:' + '2' * 64]
    registry.chart.return_value = 'sha256:' + '3' * 64
    monkeypatch.setenv('BACKEND_DIGEST', 'sha256:' + '1' * 64)
    monkeypatch.setenv('FRONTEND_DIGEST', 'sha256:' + '2' * 64)
    runner = MagicMock()
    monkeypatch.setattr(release, 'run', runner)
    target = tmp_path / 'release.json'
    release.publish_chart(data, registry, target)
    runner.assert_not_called()
    result = json.loads(target.read_text())
    assert result['status'] == 'published'
    assert result['chart_digest'] == 'sha256:' + '3' * 64
    assert result['images']['backend']['digest'] == 'sha256:' + '1' * 64
    assert 'token' not in target.read_text().lower()


def test_chart_push_with_failed_readback_never_generates_success_manifest(data, tmp_path, monkeypatch):
    registry = MagicMock()
    registry.image.side_effect = ['sha256:' + '1' * 64, 'sha256:' + '2' * 64]
    registry.chart.side_effect = [None, ValueError('readback validation failed')]
    monkeypatch.setenv('BACKEND_DIGEST', 'sha256:' + '1' * 64)
    monkeypatch.setenv('FRONTEND_DIGEST', 'sha256:' + '2' * 64)
    monkeypatch.setattr(release, 'credentials', lambda directory: ('dummy', 'actor', {}))
    monkeypatch.setattr(release, 'package_chart', lambda *args: tmp_path / 'package.tgz')
    monkeypatch.setattr(release, 'run', MagicMock())
    target = tmp_path / 'release.json'
    with pytest.raises(ValueError, match='readback validation failed'):
        release.publish_chart(data, registry, target)
    assert not target.exists()


def chart_blob(data):
    chart = {'name': 'cap', 'version': data['chart_version'], 'appVersion': data['source_sha'],
             'annotations': release.expected_source(data)}
    values = {name: {'image': {'repository': image['repository'], 'tag': image['tag']}}
              for name, image in data['images'].items()}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, content in [('Chart.yaml', chart), ('values.yaml', values)]:
            raw = yaml.safe_dump(content).encode()
            member = tarfile.TarInfo('cap/' + name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return stream.getvalue()


def test_chart_layer_readback_checks_identity_then_renders(data, tmp_path, monkeypatch):
    raw = chart_blob(data)
    manifest = {'config': {'mediaType': 'application/vnd.cncf.helm.config.v1+json'}, 'layers': [{
        'mediaType': 'application/vnd.cncf.helm.chart.content.v1.tar+gzip', 'digest': release.digest(raw)}]}
    registry = release.Registry()
    monkeypatch.setattr(registry, 'manifest', lambda *args: (manifest, 'sha256:' + '3' * 64))
    monkeypatch.setattr(registry, 'read', lambda *args: raw)
    render = MagicMock()
    monkeypatch.setattr(release, 'validate_render', render)
    assert registry.chart(data, tmp_path) == 'sha256:' + '3' * 64
    render.assert_called_once()
    wrong = copy.deepcopy(data)
    wrong['images']['backend']['tag'] = 'b' * 40
    with pytest.raises(ValueError, match='image does not match'):
        registry.chart(wrong, tmp_path)


def test_workflow_contract_and_permissions():
    workflow = yaml.load((Path(__file__).resolve().parents[2] / '.github/workflows/ci.yaml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'pull_request', 'push'}
    assert workflow['permissions'] == {'contents': 'read'}
    jobs = workflow['jobs']
    assert {job['name'] for job in jobs.values()} == {
        'Static Checks', 'Code Tests', 'Build and Publish Images', 'Helm Validation',
        'Package and Publish Chart', 'Chart Version Check',
    }
    assert set(jobs['images']['needs']) == {'static-checks', 'code-tests', 'helm-validation', 'chart-version'}
    assert jobs['chart']['needs'] == ['images']
    for name, job in jobs.items():
        if name in ('images', 'chart'):
            assert job['if'] == '${{ always() }}'
            assert job['permissions'] == {'contents': 'read', 'packages': 'write'}
        else:
            assert 'permissions' not in job
        for step in job['steps']:
            if 'uses' in step:
                assert release.SHA.fullmatch(step['uses'].split('@')[1])


@pytest.mark.parametrize('results,expected', [
    (['success'] * 4, 0),
    (['success', 'failure', 'success', 'success'], 1),
    (['success', 'skipped', 'success', 'success'], 1),
    (['success', 'cancelled', 'success', 'success'], 1),
    ([], 1),
])
def test_actual_workflow_gate_blocks_failure_skipped_and_cancelled(results, expected):
    workflow = yaml.load((release.ROOT / '.github/workflows/ci.yaml').read_text(), Loader=yaml.BaseLoader)
    gate = workflow['jobs']['images']['steps'][0]['run'].splitlines()
    assert gate[0] == "python - <<'PY'" and gate[-1] == 'PY'
    result = subprocess.run([sys.executable, '-c', '\n'.join(gate[1:-1])],
                            env=dict(os.environ, GATE_RESULTS=json.dumps(results)), capture_output=True)
    assert result.returncode == expected
