"""Reproduce the two pinned upstream browser bundles and their license notices."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    'geotiff': ('3.0.5', 'OWcL9S9+yDZ6iAlXMt32T1iwUApJM8UiD47xbm6ZP1h33d10fqkPs14EG/ttT5EnefpZSx3G15iDFC5FxUNUwA==',
                'dist-browser/geotiff.js', 'LICENSE', 'geotiffjs/geotiff.js', '4a296052fb90aa2cc673f573d6f95d14167a8fbc'),
    'proj4': ('2.19.10', 'uL6/C6kA8+ncJAEDmUeV8PmNJcTlRLDZZa4/87CzRpb8My4p+Ame4LhC4G3H/77z2icVqcu3nNL9h5buSdnY+g==',
              'dist/proj4.js', 'LICENSE.md', 'proj4js/proj4js', '7c6296485462f6f03dcc1d1852b9e976bf23bfb1'),
}


def get(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def archive(url, integrity):
    data = get(url)
    algorithm, expected = integrity.split('-', 1)
    if base64.b64encode(hashlib.new(algorithm, data).digest()).decode() != expected:
        raise ValueError(f'Archive integrity mismatch: {url}')
    return tarfile.open(fileobj=io.BytesIO(data), mode='r:gz')


def main():
    target = ROOT / 'web/vendor'
    records, notices = [], []
    for name, (version, digest, bundle, license_name, repo, commit) in PACKAGES.items():
        url = f'https://registry.npmjs.org/{name}/-/{name}-{version}.tgz'
        with archive(url, 'sha512-' + digest) as package:
            content = package.extractfile('package/' + bundle).read()
            filename = f'{name}-{version}.js'
            (target / filename).write_bytes(content)
            (target / f'LICENSE-{name}').write_bytes(package.extractfile('package/' + license_name).read())
            records.append({'name': name, 'version': version, 'tarball': url, 'integrity': 'sha512-' + digest,
                            'upstream_commit': commit, 'file': filename, 'sha256': hashlib.sha256(content).hexdigest()})
        lock_url = f'https://raw.githubusercontent.com/{repo}/{commit}/package-lock.json'
        lock = json.loads(get(lock_url))
        for path, dependency in lock['packages'].items():
            if not path or dependency.get('dev'):
                continue
            label = path.removeprefix('node_modules/')
            notices.append(f'\n=== {name} bundle dependency: {label} {dependency["version"]} ===\n')
            with archive(dependency['resolved'], dependency['integrity']) as package:
                licenses = [member for member in package.getmembers() if member.isfile() and
                            Path(member.name).name.lower().startswith(('license', 'licence', 'copying', 'notice', 'copyright'))]
                if not licenses:
                    if label != 'lerc' or dependency['version'] != '3.0.0':
                        raise RuntimeError(f'No license in {label}')
                    # lerc's npm archive omits its license; use its matching release.
                    for filename in ['LICENSE', 'NOTICE']:
                        source = f'https://raw.githubusercontent.com/Esri/lerc/v3.0/{filename}'
                        notices.append(source + '\n' + get(source).decode('utf-8'))
                for member in licenses:
                    notices.append(f'\n{member.name}\n' + package.extractfile(member).read().decode('utf-8', errors='replace'))
            records.append({'bundled_with': name, 'name': label, 'version': dependency['version'],
                            'tarball': dependency['resolved'], 'integrity': dependency['integrity'], 'lock_source': lock_url})
    (target / 'RASTER-DEPENDENCIES.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8', newline='\n')
    notice_text = 'Upstream bundle dependency notices. Bundles are redistributed without modification.\n' + '\n'.join(notices)
    notice_text = notice_text.replace('\r\n', '\n').replace('\r', '\n')
    notice_text = '\n'.join(line.rstrip(' \t') for line in notice_text.split('\n'))
    (target / 'RASTER-DEPENDENCY-LICENSES.txt').write_text(notice_text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
