import base64
import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('release', Path(__file__).parents[1]/'release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def resources():
    def resource(kind, name, spec=None, data=None):
        value = {'kind':kind, 'metadata':{'name':name}}
        if spec is not None:
            value['spec'] = spec
        if data is not None:
            value['data'] = data
        return value
    sts = resource('StatefulSet','postgres', {
        'serviceName':'postgres', 'selector':{'matchLabels':{'app':'postgres'}},
        'volumeClaimTemplates':[{'metadata':{'name':'data'},'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'2Gi'}}}}],
        'template':{'spec':{'containers':[{'env':[{'name':'PGDATA','value':'/var/lib/postgresql/data/pgdata'}]}]}}})
    config = resource('ConfigMap','database-config', data={'POSTGRES_DB':'cap','POSTGRES_USER':'cap'})
    secret = resource('Secret','database-secret', data={k:base64.b64encode(v.encode()).decode() for k,v in {'POSTGRES_PASSWORD':'dummy','DATABASE_URL':'postgresql+psycopg://cap:dummy@postgres:5432/cap'}.items()})
    secret['metadata']['annotations']={'cap.lab/identity':json.dumps({'mode':'legacy','user':'cap','database':'cap'})}
    result=[sts,config,secret]
    for comp in ['api','frontend']:
        result += [resource('Deployment',comp, {'selector':{'matchLabels':{'app':comp}}}), resource('Service',comp, {'selector':{'app':comp}})]
    result += [resource('Service','postgres', {'selector':{'app':'postgres'}})]
    return result


def test_owner_conflicts_and_explicit_adoption():
    obj=resources()[0]
    with pytest.raises(ValueError, match='Ownership conflict'):
        release.verify_owner(obj,'cap','cap')
    release.verify_owner(obj,'cap','cap',True)
    obj['metadata']['annotations']={'meta.helm.sh/release-name':'other','meta.helm.sh/release-namespace':'cap'}
    with pytest.raises(ValueError, match='Ownership conflict'):
        release.verify_owner(obj,'cap','cap',True)


@pytest.mark.parametrize('field', ['selector','serviceName','storage','credentials','database','directory'])
def test_database_preflight_rejects_incompatible_inputs(field):
    sts,config,secret=resources()[:3]
    desired=copy.deepcopy(sts)
    wanted=copy.deepcopy(config)
    if field=='selector':
        sts['spec']['selector']={}
    if field=='serviceName':
        sts['spec']['serviceName']='other'
    if field=='storage':
        sts['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage']='3Gi'
    if field=='credentials':
        secret['data'].pop('DATABASE_URL')
    if field=='database':
        config['data']['POSTGRES_DB']='other'
    if field=='directory':
        sts['spec']['template']['spec']['containers'][0]['env']=[]
    with pytest.raises(ValueError):
        release.verify_database(sts,desired,config,wanted,secret,{'user':'cap','database':'cap'})


def test_backup_failure_never_patches_ownership(tmp_path):
    objects=resources()
    claim={'kind':'PersistentVolumeClaim','metadata':{'name':'data-postgres-0','uid':'test-uid'},'spec':{'resources':{'requests':{'storage':'2Gi'}}},'status':{'phase':'Bound'}}
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        if 'template' in command:
            return b'rendered'
        if 'create' in command:
            return json.dumps({'kind':'List','items':objects}).encode()
        if 'get' in command:
            kind,name=command[command.index('get')+1:command.index('get')+3]
            if kind=='secrets':
                return json.dumps({'items':[]}).encode()
            item=claim if kind=='pvc' else next(o for o in objects if o['kind']==kind and o['metadata']['name']==name)
            return json.dumps(item).encode()
        if 'pg_dump' in command:
            raise RuntimeError('simulated backup failure')
        raise AssertionError('Unexpected mutation')
    argv=['release','adopt','--execute','--context','test','--namespace','cap','--release','cap']
    with patch.object(release,'ROOT',tmp_path), patch.object(release,'run',side_effect=run), patch('sys.argv',argv):
        with pytest.raises(RuntimeError,match='backup failure'):
            release.main()
    assert not any('patch' in command for command in calls)


def test_parse_kubectl_multiple_documents():
    assert len(release.json_documents(b'{"kind":"Secret"}\n{"kind":"Service"}'))==2
