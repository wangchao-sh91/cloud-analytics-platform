"""Bounded startup checks; this module never runs database migrations."""
import argparse
import json
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


class WaitError(RuntimeError):
    pass


def poll(check, seconds, label, interval=2):
    deadline = time.monotonic() + seconds
    while True:
        if check():
            print(f"{label} ready", flush=True)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WaitError(f"Timed out waiting for {label}")
        time.sleep(min(interval, remaining))


def job_complete(job):
    conditions = job.get('status', {}).get('conditions', [])
    if any(c['type'] in ('Failed', 'FailureTarget') and c['status'] == 'True' for c in conditions):
        raise WaitError('Migration Job failed; inspect its logs before retrying the release')
    return any(c['type'] == 'Complete' and c['status'] == 'True' for c in conditions)


def get_job():
    account = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    token = (account/'token').read_text().strip()
    namespace = (account/'namespace').read_text().strip()
    job = os.environ['MIGRATION_JOB']
    host = os.environ.get('KUBERNETES_SERVICE_HOST', 'kubernetes.default.svc')
    port = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    request = Request(f'https://{host}:{port}/apis/batch/v1/namespaces/{quote(namespace)}/jobs/{quote(job)}',
                      headers={'Authorization': f'Bearer {token}'})
    try:
        with urlopen(request, context=ssl.create_default_context(cafile=str(account/'ca.crt')), timeout=5) as response:
            return job_complete(json.load(response))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise WaitError('Not authorized to read the migration Job; check the release RBAC') from None
        if exc.code == 404 or exc.code >= 500:
            return False
        raise WaitError(f'Kubernetes API returned HTTP {exc.code}') from None
    except (URLError, TimeoutError):
        return False


def database_ready(schema=False):
    from .db import engine
    try:
        with engine.connect() as connection:
            if not schema:
                return connection.scalar(text('SELECT 1')) == 1
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            expected = ScriptDirectory.from_config(Config('alembic.ini')).get_current_head()
            return connection.scalar(text('SELECT version_num FROM alembic_version')) == expected
    except SQLAlchemyError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['database', 'migration'])
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    try:
        if args.mode == 'migration':
            poll(get_job, args.timeout, 'migration Job')
        poll(lambda: database_ready(schema=args.mode == 'migration'), args.timeout, 'database schema' if args.mode == 'migration' else 'database')
    except WaitError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
