import os
from pathlib import Path
import re
import subprocess
import shutil
import tarfile

import pytest
import yaml

from scripts import ci_release

ROOT = Path(__file__).resolve().parents[2]
HELM = os.environ.get('HELM','helm')
KUBE_VERSION = os.environ.get('KUBE_VERSION', '1.35.8')


def render(release='test', *args):
    return subprocess.run([HELM,'template',release,str(ROOT/'charts/cap'),'--kube-version',KUBE_VERSION,*args],capture_output=True,text=True)


@pytest.mark.parametrize('values',[None,'values-kind.yaml','values-legacy.yaml'])
def test_supported_values_render_and_keep_data(values):
    args=[] if values is None else ['-f',str(ROOT/'charts/cap'/values)]
    result=render('test',*args)
    assert result.returncode==0,result.stderr
    assert 'whenDeleted: Retain' in result.stdout and 'helm.sh/resource-policy: keep' in result.stdout
    assert 'helm.sh/hook:' not in result.stdout
    assert 'ttlSecondsAfterFinished' not in result.stdout


@pytest.mark.parametrize('setting',['backend.replicas=0','database.image.tag=18','database.persistence.size=0Gi','naming.mode=unknown','database.enabled=false'])
def test_invalid_values_are_rejected(setting):
    assert render('test','--set',setting).returncode!=0


def test_long_release_names_remain_distinct():
    first=render('shared-prefix-'+'a'*30+'-one')
    second=render('shared-prefix-'+'a'*30+'-two')
    assert first.returncode==second.returncode==0
    def names(text):
        return set(re.findall(r'^  name: (.+)$',text,re.M))
    assert names(first.stdout).isdisjoint(names(second.stdout))
    assert all(len(n)<=63 for n in names(first.stdout))


def test_release_package_binds_images_without_changing_source(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    source = project / 'charts/cap'
    shutil.copytree(ROOT / 'charts/cap', source)
    before = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    data = ci_release.identity(
        {'number': 42, 'pull_request': {'head': {'sha': 'a' * 40}}},
        {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_NAME': 'pull_request',
         'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1'}, '0.3.0',
    )
    monkeypatch.setattr(ci_release, 'ROOT', project)
    monkeypatch.setattr(ci_release, 'HELM', HELM)
    directory = tmp_path / 'package'
    directory.mkdir()
    package = ci_release.package_chart(data, directory)
    with tarfile.open(package, mode='r:gz') as archive:
        chart = yaml.safe_load(archive.extractfile('cap/Chart.yaml').read())
        values = yaml.safe_load(archive.extractfile('cap/values.yaml').read())
        for name in ('values-kind.yaml', 'values-legacy.yaml'):
            assert archive.extractfile('cap/' + name).read() == before[name]
    ci_release.validate_chart(chart, values, data)
    assert chart['version'] == '0.3.0-sha' + 'a' * 40
    assert values['database'] == yaml.safe_load(before['values.yaml'])['database']
    assert before == {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*') if path.is_file()}


def test_published_chart_render_rejects_wrong_application_image(tmp_path, monkeypatch):
    data = ci_release.identity(
        {'number': 42, 'pull_request': {'head': {'sha': 'a' * 40}}},
        {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_NAME': 'pull_request',
         'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1'}, '0.3.0',
    )
    monkeypatch.setattr(ci_release, 'HELM', HELM)
    with pytest.raises(ValueError, match='different image'):
        ci_release.validate_render(ROOT / 'charts/cap', data)
