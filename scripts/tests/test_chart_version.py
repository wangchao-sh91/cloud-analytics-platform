import importlib.util
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location('chart_version', Path(__file__).parents[1] / 'check_chart_version.py')
versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(versions)


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo).decode().strip()


def save(repo, files):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.name=CI Test', '-c', 'user.email=ci@example.invalid', 'commit', '-qm', 'fixture')
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    save(tmp_path, {versions.CHART: 'apiVersion: v2\nname: cap\nversion: 0.2.9\n', 'apps/example.py': 'print(1)\n'})
    return tmp_path


def test_code_requires_bump(repo):
    base = git(repo, 'rev-parse', 'HEAD')
    head = save(repo, {'apps/example.py': 'print(2)\n'})
    with pytest.raises(ValueError, match='bump'):
        versions.check(repo, 'pull_request', head, base)


def test_numeric_bump_and_multiple_commits(repo):
    base = git(repo, 'rev-parse', 'HEAD')
    save(repo, {versions.CHART: 'version: 0.2.10\n'})
    head = save(repo, {'apps/example.py': 'print(3)\n'})
    assert '0.2.9 -> 0.2.10' in versions.check(repo, 'pull_request', head, base)


@pytest.mark.parametrize('path', ['docs/guide.md', 'openspec/changes/example/tasks.md', 'README.md', 'LICENSE.txt'])
def test_documentation_exemptions(repo, path):
    base = git(repo, 'rev-parse', 'HEAD')
    head = save(repo, {path: 'documentation\n'})
    assert 'not required' in versions.check(repo, 'pull_request', head, base)


def test_deleted_code_requires_bump(repo):
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'apps/example.py').unlink()
    head = save(repo, {'README.md': 'delete code\n'})
    with pytest.raises(ValueError, match='bump'):
        versions.check(repo, 'pull_request', head, base)


def test_rename_into_documentation_still_requires_bump(repo):
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'docs').mkdir()
    (repo / 'apps/example.py').rename(repo / 'docs/example.py')
    head = save(repo, {})
    assert set(versions.changed_paths(repo, base, head)) == {'apps/example.py', 'docs/example.py'}
    with pytest.raises(ValueError, match='bump'):
        versions.check(repo, 'pull_request', head, base)


def test_paths_with_whitespace_and_unknown_build_files_require_bump(repo):
    base = git(repo, 'rev-parse', 'HEAD')
    head = save(repo, {'build configuration\nwith newline': 'config\n'})
    assert versions.changed_paths(repo, base, head) == ['build configuration\nwith newline']
    with pytest.raises(ValueError, match='bump'):
        versions.check(repo, 'pull_request', head, base)


def test_target_branch_only_code_is_not_pr_code(repo):
    ancestor = git(repo, 'rev-parse', 'HEAD')
    head = save(repo, {'docs/guide.md': 'docs\n'})
    git(repo, 'checkout', '-q', '--detach', ancestor)
    base = save(repo, {'apps/target_only.py': 'print(2)\n'})
    assert 'not required' in versions.check(repo, 'pull_request', head, base)


def test_compare_version_against_current_base_not_common_ancestor(repo):
    ancestor = git(repo, 'rev-parse', 'HEAD')
    head = save(repo, {versions.CHART: 'version: 0.2.10\n'})
    git(repo, 'checkout', '-q', '--detach', ancestor)
    base = save(repo, {versions.CHART: 'version: 0.2.10\n', 'docs/target.md': 'base\n'})
    with pytest.raises(ValueError, match='bump'):
        versions.check(repo, 'pull_request', head, base)


@pytest.mark.parametrize('value', ['0.2.8', '0.2.9', '0.02.10', '0.3.0-rc.1', '0.3.0+build'])
def test_non_increasing_or_invalid_versions_fail(repo, value):
    base = git(repo, 'rev-parse', 'HEAD')
    head = save(repo, {versions.CHART: f'version: {value}\n', 'apps/example.py': 'print(2)\n'})
    with pytest.raises(ValueError):
        versions.check(repo, 'pull_request', head, base)


@pytest.mark.parametrize('base', [None, 'HEAD', '0' * 40])
def test_missing_or_non_exact_base_fails(repo, base):
    with pytest.raises(ValueError):
        versions.check(repo, 'pull_request', git(repo, 'rev-parse', 'HEAD'), base)


def test_main_validates_version_without_pr_comparison(repo):
    assert 'main push' in versions.check(repo, 'push', git(repo, 'rev-parse', 'HEAD'))
    head = save(repo, {versions.CHART: 'version: invalid\n'})
    with pytest.raises(ValueError, match='MAJOR.MINOR.PATCH'):
        versions.check(repo, 'push', head)


def test_shallow_history_fails_instead_of_assuming_no_changes(repo, tmp_path):
    clone = tmp_path / 'shallow'
    git(tmp_path, 'clone', '-q', '--depth=1', repo.as_uri(), str(clone))
    head = git(clone, 'rev-parse', 'HEAD')
    with pytest.raises(ValueError, match='Full Git history'):
        versions.check(clone, 'pull_request', head, head)
