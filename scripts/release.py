#!/usr/bin/env python3
"""Read-only preflight by default; explicit deploy/adopt actions manage releases."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]


def json_documents(raw):
    decoder = json.JSONDecoder()
    remaining = raw.decode().strip()
    documents = []
    while remaining:
        value, position = decoder.raw_decode(remaining)
        documents.extend(value['items'] if value.get('kind') == 'List' else [value])
        remaining = remaining[position:].lstrip()
    return documents


def run(command, *, data=None):
    result = subprocess.run(command, input=data, capture_output=True)
    if result.returncode:
        # Do not echo stdin, rendered Secret objects or Helm debug output.
        raise RuntimeError(result.stderr.decode().strip() or 'Command failed: ' + command[0])
    return result.stdout


def verify_owner(resource, release, namespace, adopt=False):
    metadata = resource['metadata']
    annotations = metadata.get('annotations', {})
    owner = (annotations.get('meta.helm.sh/release-name'), annotations.get('meta.helm.sh/release-namespace'))
    manager = metadata.get('labels', {}).get('app.kubernetes.io/managed-by')
    if owner == (release, namespace) and manager == 'Helm':
        return
    if adopt and owner == (None, None) and manager in (None, 'kubectl'):
        return
    raise ValueError(f"Ownership conflict: {resource['kind']}/{metadata['name']}")


def verify_database(sts, desired, config, wanted_config, secret, identity):
    for key in ['serviceName', 'selector']:
        if sts['spec'][key] != desired['spec'][key]:
            raise ValueError('Existing StatefulSet immutable field differs: ' + key)
    old = sts['spec']['volumeClaimTemplates'][0]
    new = desired['spec']['volumeClaimTemplates'][0]
    if old['metadata']['name'] != new['metadata']['name']:
        raise ValueError('Volume template identity differs')
    for key in ['accessModes', 'resources', 'storageClassName', 'volumeMode']:
        default = 'Filesystem' if key == 'volumeMode' else ''
        if old['spec'].get(key, default) != new['spec'].get(key, default):
            raise ValueError('Existing storage settings differ: ' + key)
    for key in ['POSTGRES_DB', 'POSTGRES_USER']:
        if config['data'][key] != wanted_config['data'][key]:
            raise ValueError('Database identity differs: ' + key)
    old_container = sts['spec']['template']['spec']['containers'][0]
    new_container = desired['spec']['template']['spec']['containers'][0]
    if old_container.get('env') != new_container.get('env'):
        raise ValueError('Database data directory configuration differs')
    verify_credentials(secret, identity, desired['metadata']['name'])


def verify_credentials(secret, identity, database_host):
    values = secret.get('data', {})
    if not values.get('POSTGRES_PASSWORD') or not values.get('DATABASE_URL'):
        raise ValueError('Database Secret is incomplete; restore original credentials')
    url = urlparse(base64.b64decode(values['DATABASE_URL']).decode())
    password = base64.b64decode(values['POSTGRES_PASSWORD']).decode()
    if (url.scheme, unquote(url.username or ''), unquote(url.password or ''), url.hostname, url.port, url.path) != ('postgresql+psycopg', identity['user'], password, database_host, 5432, '/' + identity['database']):
        raise ValueError('Database Secret URL does not match expected identity')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'deploy', 'adopt'])
    parser.add_argument('--context', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('-f', '--values', action='append', default=[])
    parser.add_argument('--set', action='append', default=[])
    parser.add_argument('--execute', action='store_true', help='Perform explicit legacy adoption after backup')
    parser.add_argument('--timeout', default='10m')
    args = parser.parse_args()
    helm = os.environ.get('HELM', 'helm')
    k = ['kubectl', '--context', args.context, '-n', args.namespace]
    flags = sum((['-f', str(Path(v).resolve())] for v in args.values), [])
    flags += sum((['--set', v] for v in args.set), [])
    rendered = run([helm, 'template', args.release, str(ROOT/'charts/cap'), '--namespace', args.namespace, '--kube-version', '1.35.0'] + flags)
    manifests = json_documents(run(k + ['create', '--dry-run=client', '--validate=false', '-f', '-', '-o', 'json'], data=rendered))
    by_kind = {}
    for item in manifests:
        by_kind.setdefault(item['kind'], []).append(item)
    desired_db = by_kind['StatefulSet'][0]
    desired_secret = by_kind['Secret'][0]
    desired_config = next(m for m in by_kind['ConfigMap'] if 'POSTGRES_DB' in m.get('data', {}))
    identity = json.loads(desired_secret['metadata']['annotations']['cap.lab/identity'])
    # Also check retained resources after uninstall, when the StatefulSet no longer exists.
    for candidate in json.loads(run(k + ['get', 'secrets', '-o', 'json']))['items']:
        annotations = candidate['metadata'].get('annotations', {})
        if (annotations.get('meta.helm.sh/release-name'), annotations.get('meta.helm.sh/release-namespace')) == (args.release, args.namespace) and 'cap.lab/identity' in annotations:
            if json.loads(annotations['cap.lab/identity']) != identity:
                raise ValueError('Database identity, naming mode and storage settings are immutable')
    adopting = args.action == 'adopt'
    if adopting and identity['mode'] != 'legacy':
        raise ValueError('Adoption requires values-legacy.yaml')
    # Validate all resources before changing any metadata or workload.
    existing = []
    for item in manifests:
        raw = run(k + ['get', item['kind'], item['metadata']['name'], '--ignore-not-found', '-o', 'json'])
        if raw.strip():
            live = json.loads(raw)
            verify_owner(live, args.release, args.namespace, adopting)
            if live['kind'] == 'Deployment' and live['spec']['selector'] != item['spec']['selector']:
                raise ValueError('Existing Deployment selector differs: ' + item['metadata']['name'])
            if live['kind'] == 'Service' and live['spec'].get('selector') != item['spec'].get('selector'):
                raise ValueError('Existing Service selector differs: ' + item['metadata']['name'])
            existing.append(live)
    db = next((m for m in existing if m['kind'] == 'StatefulSet'), None)
    secret = next((m for m in existing if m['kind'] == 'Secret'), None)
    config = next((m for m in existing if m['kind'] == 'ConfigMap' and m['metadata']['name'] == desired_config['metadata']['name']), None)
    claim_name = 'data-' + desired_db['metadata']['name'] + '-0'
    raw_claim = run(k + ['get', 'pvc', claim_name, '--ignore-not-found', '-o', 'json'])
    claim = json.loads(raw_claim) if raw_claim.strip() else None
    if claim and not secret:
        raise ValueError('Retained PVC exists but its original Secret is missing')
    if secret:
        verify_credentials(secret, identity, desired_db['metadata']['name'])
    if claim and claim['spec']['resources']['requests']['storage'] != desired_db['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage']:
        raise ValueError('Existing PVC size differs; use a separate expansion procedure')
    if db:
        if not secret or not config or not claim or claim.get('status', {}).get('phase') != 'Bound':
            raise ValueError('Existing database requires complete credentials, configuration and a Bound PVC')
        verify_database(db, desired_db, config, desired_config, secret, identity)
    if adopting:
        required = {('StatefulSet', 'postgres'), ('Secret', 'database-secret'), ('ConfigMap', 'database-config'), ('Deployment', 'api'), ('Deployment', 'frontend'), ('Service', 'api'), ('Service', 'frontend'), ('Service', 'postgres')}
        if not required <= {(m['kind'], m['metadata']['name']) for m in existing}:
            raise ValueError('Legacy deployment is incomplete; refusing partial adoption')
    print('Preflight passed; no resources changed.', flush=True)
    if args.action == 'check' or (adopting and not args.execute):
        return
    if adopting:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        backup = ROOT/'backups'/('adopt-' + stamp)
        backup.mkdir(parents=True, mode=0o700)
        os.chmod(backup, 0o700)
        snapshot = backup/'resources.json'
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(existing + [claim], f, indent=2)
        pod = desired_db['metadata']['name'] + '-0'
        dump = run(k + ['exec', pod, '--', 'pg_dump', '-U', identity['user'], '-d', identity['database'], '-Fc'])
        if not dump.startswith(b'PGDMP'):
            raise ValueError('Backup failed or is not a PostgreSQL custom archive')
        run(k + ['exec', '-i', pod, '--', 'pg_restore', '--list'], data=dump)
        dump_file = backup/'database.dump'
        dump_file.write_bytes(dump)
        dump_file.chmod(0o600)
        baseline = {'pvc_uid': claim['metadata']['uid'], 'secret_sha256': hashlib.sha256(json.dumps(secret['data'], sort_keys=True).encode()).hexdigest()}
        rows = run(k + ['exec', pod, '--', 'psql', '-U', identity['user'], '-d', identity['database'], '-At', '-c', "SELECT coalesce(json_agg(s ORDER BY id), '[]'::json) FROM physical_servers s"])
        baseline['assets'] = json.loads(rows)
        (backup/'baseline.json').write_text(json.dumps(baseline, indent=2, ensure_ascii=False))
        (backup/'baseline.json').chmod(0o600)
        for live in existing:
            patch = {'metadata': {'labels': {'app.kubernetes.io/managed-by': 'Helm'}, 'annotations': {'meta.helm.sh/release-name': args.release, 'meta.helm.sh/release-namespace': args.namespace}}}
            run(k + ['patch', live['kind'], live['metadata']['name'], '--type=merge', '-p', json.dumps(patch)])
        print('Backup and ownership snapshot saved under', backup, flush=True)
    command = [helm, 'upgrade', '--install', args.release, str(ROOT/'charts/cap'), '--kube-context', args.context, '--namespace', args.namespace, '--create-namespace', '--wait', '--wait-for-jobs', '--timeout', args.timeout] + flags
    subprocess.run(command, check=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
