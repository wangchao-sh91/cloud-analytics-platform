import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELM = os.environ.get('HELM','helm')


def render(release='test', *args):
    return subprocess.run([HELM,'template',release,str(ROOT/'charts/cap'),'--kube-version','1.35.8',*args],capture_output=True,text=True)


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
    names=lambda text:set(re.findall(r'^  name: (.+)$',text,re.M))
    assert names(first.stdout).isdisjoint(names(second.stdout))
    assert all(len(n)<=63 for n in names(first.stdout))
