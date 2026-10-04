"""GitHub release discovery for update notifications and installation."""
import platform
import re
import urllib.parse
import requests
from app_version import VERSION, BUILD_LABEL

REPOSITORY = 'marushan491/lwmc-nbg-uploader'
RELEASE_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(value))
    if not match:
        raise ValueError('Ungültige stabile Versionsnummer.')
    return tuple(map(int, match.groups()))


def platform_label():
    if BUILD_LABEL:
        return BUILD_LABEL
    system, machine = platform.system(), platform.machine().lower()
    if system == 'Darwin':
        return 'macOS-AppleSilicon' if machine in ('arm64', 'aarch64') else 'macOS-Intel'
    if machine in ('x86_64', 'amd64'):
        return {'Windows': 'Windows-x64', 'Linux': 'Linux-x64'}.get(system, '')
    return ''


def trusted_release_url(url, download=False):
    parsed = urllib.parse.urlsplit(str(url))
    prefix = f'/{REPOSITORY}/releases/' + ('download/' if download else 'tag/')
    return (parsed.scheme == 'https' and parsed.hostname == 'github.com' and
            parsed.port in (None, 443) and parsed.username is None and parsed.password is None and
            parsed.path.startswith(prefix) and not parsed.query and not parsed.fragment)


def check_update(current=VERSION, label=None):
    response = requests.get(RELEASE_API, headers={'Accept': 'application/vnd.github+json',
        'User-Agent': 'LWMC-NBG-Uploader/' + VERSION}, timeout=(5, 10))
    response.raise_for_status()
    release = response.json()
    tag = release.get('tag_name', '')
    if release.get('draft') or release.get('prerelease') or version_tuple(tag) <= version_tuple(current):
        return None
    url = release.get('html_url', '')
    if not trusted_release_url(url):
        raise RuntimeError('GitHub hat einen unerwarteten Release-Link geliefert.')
    wanted = f'WorshipUploader-{label or platform_label()}.zip'
    asset = next((a for a in release.get('assets', []) if a.get('name') == wanted), None)
    download = asset.get('browser_download_url') if asset else None
    if download and not trusted_release_url(download, download=True):
        raise RuntimeError('GitHub hat einen unerwarteten Download-Link geliefert.')
    return {'version': tag, 'url': url, 'download_url': download, 'asset_name': wanted if download else None,
            'digest': asset.get('digest') if asset else None, 'size': asset.get('size') if asset else None,
            'platform': label or platform_label()}
