#!/usr/bin/env python3
"""Run unit tests or backend integration tests against an explicit disposable DB."""
import argparse
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'apps/backend'


def test_environment():
    env = os.environ.copy()
    for key in ('DATABASE_URL', 'TEST_DATABASE_URL', 'PGPASSWORD', 'PGSERVICE'):
        env.pop(key, None)
    env['PYTHONPATH'] = str(BACKEND)
    env['KUBECONFIG'] = os.devnull
    return env


def wait_for_database(url, timeout):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import SQLAlchemyError

    if make_url(url).drivername != 'postgresql+psycopg':
        raise ValueError('TEST_DATABASE_URL must use postgresql+psycopg.')
    engine = create_engine(url, connect_args={'connect_timeout': 2})
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                with engine.connect() as connection:
                    version = int(connection.execute(text('SHOW server_version_num')).scalar_one())
                if version // 10000 != 17:
                    raise ValueError('Integration tests require PostgreSQL 17.')
                return
            except SQLAlchemyError:
                if time.monotonic() >= deadline:
                    raise ValueError('Test database did not become ready before the timeout.') from None
                time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    finally:
        engine.dispose()


def run(mode, timeout):
    # Validate before starting any suite; never fall back to DATABASE_URL.
    url = os.environ.get('TEST_DATABASE_URL')
    if mode in ('backend', 'all'):
        if not url:
            raise ValueError('Set TEST_DATABASE_URL to a disposable PostgreSQL 17 database; tests truncate data.')
        wait_for_database(url, timeout)
    env = test_environment()
    if mode in ('unit', 'all'):
        subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', 'scripts/tests',
             '--ignore=scripts/tests/test_chart.py', 'apps/backend/tests/test_wait.py'],
            cwd=ROOT, env=env, check=True,
        )
    if mode in ('backend', 'all'):
        env['TEST_DATABASE_URL'] = url
        env['DATABASE_URL'] = url
        subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests'], cwd=BACKEND, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('unit', 'backend', 'all'))
    parser.add_argument('--db-timeout', type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.db_timeout) or args.db_timeout <= 0:
        parser.error('--db-timeout must be a positive finite number')
    try:
        run(args.mode, args.db_timeout)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        return error.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
