#!/usr/bin/env python3
"""Validate Chart versions and require a PR bump for non-documentation changes."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = 'charts/cap/Chart.yaml'
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
SHA = re.compile(r'[0-9a-f]{40}')


def git(repo, *args):
    result = subprocess.run(['git', *args], cwd=repo, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Git comparison failed; ensure the exact base/head commits and full history are available.')
    return result.stdout


def commit(repo, sha):
    if not sha or not SHA.fullmatch(sha):
        raise ValueError('Expected an explicit full 40-character commit SHA.')
    git(repo, 'cat-file', '-e', f'{sha}^{{commit}}')
    return sha


def chart_version(repo, sha):
    try:
        chart = yaml.safe_load(git(repo, 'show', f'{sha}:{CHART}'))
    except yaml.YAMLError:
        raise ValueError('Chart.yaml must be valid YAML.') from None
    value = chart.get('version') if isinstance(chart, dict) else None
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError('Chart version must be stable MAJOR.MINOR.PATCH without leading zeros or suffixes.')
    return tuple(map(int, value.split('.'))), value


def documentation(path):
    path = PurePosixPath(path)
    if path.parts[0] in ('docs', 'openspec'):
        return True
    return len(path.parts) == 1 and (
        path.suffix == '.md' or path.name == 'LICENSE' or path.name.startswith('LICENSE.')
    )


def changed_paths(repo, base, head):
    ancestor = git(repo, 'merge-base', base, head).decode().strip()
    fields = git(repo, 'diff', '--name-status', '-z', '--find-renames', ancestor, head, '--').split(b'\0')
    paths = []
    index = 0
    while index < len(fields) - 1:
        status = fields[index].decode('ascii')
        count = 2 if status.startswith(('R', 'C')) else 1
        paths.extend(field.decode('utf-8', errors='surrogateescape') for field in fields[index + 1:index + 1 + count])
        index += 1 + count
    return paths


def check(repo, event, head, base=None):
    head = commit(repo, head)
    head_value, head_text = chart_version(repo, head)
    if event == 'push':
        return f'Chart version {head_text} is valid; main push does not require a PR base/head comparison.'
    base = commit(repo, base)
    if git(repo, 'rev-parse', '--is-shallow-repository').strip() == b'true':
        raise ValueError('Full Git history is required for PR comparison; fetch with depth 0.')
    base_value, base_text = chart_version(repo, base)
    code_changed = any(not documentation(path) for path in changed_paths(repo, base, head))
    if code_changed and head_value <= base_value:
        raise ValueError(f'Code changed: bump {CHART} version above {base_text}; head is {head_text}.')
    if code_changed:
        return f'Chart version increased: {base_text} -> {head_text}.'
    return f'Only documentation or no net changes; Chart version bump is not required ({head_text}).'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', choices=('pull_request', 'push'), default='pull_request')
    parser.add_argument('--base', help='Exact PR base commit SHA (required for pull_request)')
    parser.add_argument('--head', required=True, help='Exact PR head or main push SHA')
    parser.add_argument('--repo', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(check(args.repo, args.event, args.head, args.base))
    except (ValueError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
