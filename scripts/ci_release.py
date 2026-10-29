#!/usr/bin/env python3
"""Publish and verify commit-addressed GHCR images and Helm charts."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get('HELM', str(ROOT / '.tools/helm-v3.19.0'))
KUBE_VERSION = '1.35.8'
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
BASE_VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
ACCEPT = ', '.join([
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
])


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def identity(event, env, base_version):
    repository = env['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid source repository.')
    if env['GITHUB_EVENT_NAME'] == 'pull_request':
        sha = event['pull_request']['head']['sha']
        channel, pr = 'pr', int(event['number'])
    elif env['GITHUB_EVENT_NAME'] == 'push' and event['ref'] == 'refs/heads/main':
        sha = event['after']
        channel, pr = 'main', None
    else:
        raise ValueError('Publishing supports PR events and main push only.')
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or not isinstance(base_version, str) or not BASE_VERSION.fullmatch(base_version):
        raise ValueError('Expected a full commit SHA and stable Chart version.')
    run_id, attempt = env['GITHUB_RUN_ID'], env['GITHUB_RUN_ATTEMPT']
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError('Invalid workflow run identity.')
    owner = repository.split('/')[0].lower()
    return {
        'schema_version': 1, 'repository': repository, 'event': env['GITHUB_EVENT_NAME'],
        'channel': channel, 'pr': pr, 'source_sha': sha,
        'run_id': run_id, 'run_attempt': attempt,
        'run_url': f'https://github.com/{repository}/actions/runs/{run_id}',
        'base_chart_version': base_version, 'chart_version': f'{base_version}-sha{sha}',
        'chart_repository': f'oci://ghcr.io/{owner}/charts/cap',
        'images': {name: {'repository': f'ghcr.io/{owner}/cap-{name}', 'tag': sha}
                   for name in ('backend', 'frontend')},
    }


def output(name, value):
    if '\n' in value or '\r' in value:
        raise ValueError('Invalid multiline workflow output.')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write(f'{name}={value}\n')


def metadata(path):
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    chart = yaml.safe_load((ROOT / 'charts/cap/Chart.yaml').read_text())
    data = identity(event, os.environ, chart['version'])
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if head != data['source_sha']:
        raise ValueError('Checkout does not match the event source SHA.')
    dirty = subprocess.check_output(
        ['git', 'status', '--porcelain', '--untracked-files=all', '--', 'apps', 'charts', 'scripts', '.github'],
        cwd=ROOT,
    )
    if dirty:
        raise ValueError('Commit source changes before publishing artifacts for this SHA.')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')
    for key in ('source_sha', 'chart_version', 'chart_repository'):
        output(key, data[key])
    print(f"Source {data['source_sha']}; Chart {data['chart_version']}")


def expected_source(data):
    return {'org.opencontainers.image.source': f"https://github.com/{data['repository']}",
            'org.opencontainers.image.revision': data['source_sha']}


def validate_chart(chart, values, data):
    if (chart.get('name'), chart.get('version'), chart.get('appVersion')) != (
        'cap', data['chart_version'], data['source_sha']
    ):
        raise ValueError('Chart identity does not match this source commit.')
    if any(chart.get('annotations', {}).get(k) != v for k, v in expected_source(data).items()):
        raise ValueError('Chart source annotations do not match.')
    for name, image in data['images'].items():
        if any(values.get(name, {}).get('image', {}).get(k) != image[k] for k in ('repository', 'tag')):
            raise ValueError(f'{name} Chart image does not match this source commit.')


def validate_render(package, data):
    env = dict(os.environ, KUBECONFIG=os.devnull)
    rendered = subprocess.check_output(
        [HELM, 'template', 'ci-review', str(package), '--kube-version', KUBE_VERSION], env=env,
    )
    found = set()
    for resource in yaml.safe_load_all(rendered):
        if not resource or resource.get('kind') not in ('Deployment', 'Job'):
            continue
        pod = resource['spec']['template']['spec']
        for container in pod.get('containers', []) + pod.get('initContainers', []):
            name = container['name']
            component = 'frontend' if name == 'frontend' else 'backend'
            image = data['images'][component]
            if container['image'] != f"{image['repository']}:{image['tag']}":
                raise ValueError(f'Rendered container {name} uses a different image.')
            found.add(name)
    if not {'frontend', 'api', 'migrate', 'wait-migration', 'wait-database'} <= found:
        raise ValueError('Rendered Chart is missing application or migration containers.')


def package_chart(data, directory):
    target = directory / 'cap'
    shutil.copytree(ROOT / 'charts/cap', target)
    chart = yaml.safe_load((target / 'Chart.yaml').read_text())
    values = yaml.safe_load((target / 'values.yaml').read_text())
    chart.update(version=data['chart_version'], appVersion=data['source_sha'])
    chart.setdefault('annotations', {}).update(expected_source(data))
    for name, image in data['images'].items():
        values[name]['image'].update(repository=image['repository'], tag=image['tag'])
    validate_chart(chart, values, data)
    (target / 'Chart.yaml').write_text(yaml.safe_dump(chart, sort_keys=False))
    (target / 'values.yaml').write_text(yaml.safe_dump(values, sort_keys=False))
    run([HELM, 'lint', str(target), '--kube-version', KUBE_VERSION], env=dict(os.environ, KUBECONFIG=os.devnull))
    run([HELM, 'package', str(target), '--destination', str(directory)])
    package = directory / f"cap-{data['chart_version']}.tgz"
    validate_render(package, data)
    return package


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        redirect = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirect is not None and urlparse(request.full_url).netloc != urlparse(newurl).netloc:
            redirect.remove_header('Authorization')
        return redirect


class Registry:
    """Read OCI manifests and blobs; only manifest HTTP 404 means absent."""

    def __init__(self):
        self.tokens = {}
        self.opener = build_opener(SafeRedirect())

    def request(self, url, headers=None, missing_ok=False):
        try:
            with self.opener.open(Request(url, headers=headers or {}), timeout=60) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            raise ValueError(f'GHCR HTTP {error.code}; check token/Package access. Existing refs will not be overwritten.') from None
        except (URLError, TimeoutError):
            raise ValueError('GHCR network request failed; absence could not be established.') from None

    def token(self, repository):
        if repository not in self.tokens:
            token = os.environ.get('GITHUB_TOKEN')
            actor = os.environ.get('GITHUB_ACTOR')
            if not token or not actor:
                raise ValueError('Publishing requires GITHUB_TOKEN and GITHUB_ACTOR from the workflow.')
            credentials = base64.b64encode(f'{actor}:{token}'.encode()).decode()
            query = urlencode({'service': 'ghcr.io', 'scope': f'repository:{repository}:pull,push'})
            result = self.request('https://ghcr.io/token?' + query, {'Authorization': 'Basic ' + credentials})
            self.tokens[repository] = json.loads(result)['token']
        return self.tokens[repository]

    def read(self, repository, kind, reference, missing_ok=False):
        return self.request(
            f'https://ghcr.io/v2/{repository}/{kind}/{reference}',
            {'Authorization': 'Bearer ' + self.token(repository), 'Accept': ACCEPT}, missing_ok,
        )

    def manifest(self, repository, reference):
        raw = self.read(repository, 'manifests', reference, missing_ok=True)
        if raw is None:
            return None
        actual = digest(raw)
        if reference.startswith('sha256:') and actual != reference:
            raise ValueError('Registry manifest digest mismatch.')
        return json.loads(raw), actual

    def blob(self, repository, descriptor):
        expected = descriptor['digest']
        if not DIGEST.fullmatch(expected):
            raise ValueError('Invalid blob digest.')
        raw = self.read(repository, 'blobs', expected)
        if digest(raw) != expected:
            raise ValueError('Registry blob digest mismatch.')
        return raw

    def image(self, image, data):
        repository = image['repository'].removeprefix('ghcr.io/')
        result = self.manifest(repository, image['tag'])
        if result is None:
            return None
        manifest, root_digest = result
        if 'manifests' in manifest:
            matches = [m for m in manifest['manifests'] if m.get('platform', {}).get('os') == 'linux'
                       and m.get('platform', {}).get('architecture') == 'amd64']
            if len(matches) != 1:
                raise ValueError('Image must contain exactly one linux/amd64 manifest.')
            child = self.manifest(repository, matches[0]['digest'])
            if child is None:
                raise ValueError('Image platform manifest is missing.')
            manifest = child[0]
        config = json.loads(self.blob(repository, manifest['config']))
        if (config.get('os'), config.get('architecture')) != ('linux', 'amd64'):
            raise ValueError('Existing image platform mismatch.')
        labels = config.get('config', {}).get('Labels', {}) or {}
        if any(labels.get(k) != v for k, v in expected_source(data).items()):
            raise ValueError('Existing image source/revision mismatch; refusing overwrite.')
        return root_digest

    def chart(self, data, directory):
        repository = data['chart_repository'].removeprefix('oci://ghcr.io/')
        result = self.manifest(repository, data['chart_version'])
        if result is None:
            return None
        manifest, chart_digest = result
        if manifest['config'].get('mediaType') != 'application/vnd.cncf.helm.config.v1+json':
            raise ValueError('Existing artifact is not a Helm chart.')
        layers = [layer for layer in manifest['layers']
                  if layer.get('mediaType') == 'application/vnd.cncf.helm.chart.content.v1.tar+gzip']
        if len(layers) != 1:
            raise ValueError('Chart must have exactly one content layer.')
        raw = self.blob(repository, layers[0])
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            chart = yaml.safe_load(archive.extractfile('cap/Chart.yaml').read())
            values = yaml.safe_load(archive.extractfile('cap/values.yaml').read())
        validate_chart(chart, values, data)
        package = directory / 'read-back.tgz'
        package.write_bytes(raw)
        validate_render(package, data)
        return chart_digest


def credentials(directory):
    token = os.environ.get('GITHUB_TOKEN')
    actor = os.environ.get('GITHUB_ACTOR')
    if not token or not actor:
        raise ValueError('GITHUB_TOKEN and GITHUB_ACTOR are required.')
    return token, actor, dict(os.environ, DOCKER_CONFIG=str(directory / 'docker'),
                             HELM_REGISTRY_CONFIG=str(directory / 'helm.json'))


def publish_images(data, registry):
    with tempfile.TemporaryDirectory() as temporary:
        token, actor, env = credentials(Path(temporary))
        run(['docker', 'login', 'ghcr.io', '--username', actor, '--password-stdin'], input=token.encode(), env=env)
        for name, image in data['images'].items():
            existing = registry.image(image, data)
            if existing is None:
                reference = f"{image['repository']}:{image['tag']}"
                args = ['docker', 'build', '--platform', 'linux/amd64']
                for key, value in expected_source(data).items():
                    args += ['--label', f'{key}={value}']
                run(args + ['--tag', reference, str(ROOT / 'apps' / name)], env=env)
                run(['docker', 'push', reference], env=env)
                existing = registry.image(image, data)
                if existing is None:
                    raise ValueError('Image was not readable after push.')
            output(f'{name}_digest', existing)
            print(f"{image['repository']}:{image['tag']} -> {existing}")


def publish_chart(data, registry, manifest_path):
    manifest_path.unlink(missing_ok=True)
    # Read both images again; never publish a Chart for a partial image release.
    for name, image in data['images'].items():
        actual = registry.image(image, data)
        expected = os.environ.get(f'{name.upper()}_DIGEST')
        if actual is None or not expected or actual != expected:
            raise ValueError(f'{name} image is missing or differs from the image job result.')
        image['digest'] = actual
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        actual = registry.chart(data, directory)
        if actual is None:
            token, actor, env = credentials(directory)
            package = package_chart(data, directory)
            run([HELM, 'registry', 'login', 'ghcr.io', '--username', actor, '--password-stdin'], input=token.encode(), env=env)
            run([HELM, 'push', str(package), data['chart_repository'].rsplit('/', 1)[0]], env=env)
            actual = registry.chart(data, directory)
            if actual is None:
                raise ValueError('Chart was not readable after push.')
    data['chart_digest'] = actual
    data['status'] = 'published'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2) + '\n')
    summary = [f"## Published {data['source_sha']}", '', f"Source: `{data['source_sha']}`",
               f"Chart: `{data['chart_repository']}:{data['chart_version']}`", f"Chart digest: `{actual}`", '']
    for image in data['images'].values():
        summary.append(f"- `{image['repository']}:{image['tag']}` — `{image['digest']}`")
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('\n'.join(summary) + '\n')
    print('\n'.join(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('metadata', 'images', 'chart', 'package'))
    parser.add_argument('--metadata', type=Path, default=ROOT / '.tools/release/metadata.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.tools/release/release.json')
    args = parser.parse_args()
    try:
        if args.command == 'metadata':
            metadata(args.metadata)
        else:
            data = json.loads(args.metadata.read_text())
            if args.command == 'images':
                publish_images(data, Registry())
            elif args.command == 'chart':
                publish_chart(data, Registry(), args.output)
            else:
                args.output.mkdir(parents=True, exist_ok=True)
                package_chart(data, args.output)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (KeyError, OSError, subprocess.SubprocessError, yaml.YAMLError, tarfile.TarError):
        print('Release failed. Verify event/SHA, tool output, GHCR access and artifact identity; no successful release manifest was generated.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
