"""Prepare and release an immutable, evidence-bound edition package."""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import edition

TAG = re.compile(r'<(?:link|img|source)\b[^>]*>', re.I)
ATTR = re.compile(r'''\b(href|src|srcset)\s*=\s*(["'])(.*?)\2''', re.I | re.S)
CSS_URL = re.compile(r'''url\(\s*(["']?)(.*?)\1\s*\)''', re.I)
CSS_IMPORT = re.compile(r'''(@import\s+)(["'])(.*?)\2''', re.I)


def _day(stamp: str) -> str:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp or ''):
        raise ValueError('date must be YYYY-MM-DD')
    if date.fromisoformat(stamp).isoformat() != stamp:
        raise ValueError('invalid date')
    return stamp


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _external(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme and parts.scheme.lower() not in {'http', 'https', 'data'}:
        raise ValueError(f'unsupported resource URL scheme: {url}')
    return bool(parts.scheme or parts.netloc or url.startswith('#'))


def _resolve(root: Path, base: Path, url: str) -> Path:
    parts = urlsplit(url)
    if not parts.path or parts.query or parts.fragment or '\\' in parts.path:
        raise ValueError(f'unsupported local resource URL: {url}')
    path = unquote(parts.path)
    if path.startswith('/') or '\\' in path or '\x00' in path:
        raise ValueError(f'unsafe resource URL: {url}')
    target = (base / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f'missing or unsafe local resource: {url}')
    return target


def _package(root: Path, stamp: str, html: str) -> tuple[str, dict[str, bytes]]:
    files: dict[str, bytes] = {}
    visiting: set[Path] = set()
    cache: dict[Path, str] = {}

    def resource(path: Path) -> str:
        if path in cache:
            return cache[path]
        if path in visiting:
            raise ValueError(f'cyclic CSS import: {path.name}')
        visiting.add(path)
        data = path.read_bytes()
        if path.suffix.lower() == '.css':
            css = data.decode('utf-8')
            # Assets are siblings by hash, so the relative path is stable before hashing CSS.
            def css_url(match):
                url = match.group(2).strip()
                if _external(url) or url.startswith('data:'):
                    return match.group(0)
                target = resource(_resolve(root, path.parent, url))
                return f'url("../{posixpath.relpath(target, f"assets/{stamp}")}")'
            def css_import(match):
                url = match.group(3).strip()
                if _external(url):
                    return match.group(0)
                target = resource(_resolve(root, path.parent, url))
                return f'{match.group(1)}"../{posixpath.relpath(target, f"assets/{stamp}")}"'
            css = CSS_URL.sub(css_url, css)
            css = CSS_IMPORT.sub(css_import, css)
            data = css.encode('utf-8')
        # Use a safe fixed basename: original names need not become URL syntax.
        suffix = path.suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
            raise ValueError(f'unsupported resource type: {path.name}')
        dest = f'assets/{stamp}/{_hash(data)}/asset{suffix}'
        files[dest] = data
        cache[path] = dest
        visiting.remove(path)
        return dest

    if re.search(r'<(?:script|iframe|object|embed|video|audio)\b|\bstyle\s*=|<style\b|<base\b', html, re.I):
        raise ValueError('inline or active resources are not supported in edition packages')

    def tag(match):
        raw = match.group(0)
        is_link = bool(re.match(r'<link\b', raw, re.I))
        if re.search(r'\b(?:src|srcset|href)\s*=\s*[^\s"\']', raw, re.I):
            raise ValueError('resource attributes must use quotes')
        def attribute(a):
            key, quote, url = a.group(1), a.group(2), a.group(3).strip()
            if key.lower() == 'srcset':
                raise ValueError('srcset is not supported in edition packages')
            if not url:
                raise ValueError('empty resource URL')
            if _external(url) or url.startswith('data:'):
                if not is_link and not url.startswith('data:'):
                    raise ValueError(f'remote image is not packaged: {url}')
                return a.group(0)
            dest = resource(_resolve(root, root, url))
            return f'{key}={quote}{dest}{quote}'
        return ATTR.sub(attribute, raw)
    return TAG.sub(tag, html), files


def _fingerprint(stamp: str, evidence: str, files: dict[str, bytes]) -> str:
    obj = {'date': stamp, 'evidence': evidence,
           'files': {name: _hash(data) for name, data in sorted(files.items())}}
    return _hash(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.publish-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def prepare(root: Path, stamp: str) -> dict:
    root = Path(root).resolve()
    try:
        stamp = _day(stamp)
        source = root / f'{stamp}.html'
        html = source.read_text(encoding='utf-8')
        evidence = edition.issue_digest(root, stamp)
        edition.check_document(root, stamp, html)
        html, assets = _package(root, stamp, html)
        edition.check_document(root, stamp, html)
        files = {'index.html': html.encode('utf-8'), **assets}
        fingerprint = _fingerprint(stamp, evidence, files)
        base = root / 'desk' / '版面' / stamp
        base.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.candidate-', dir=base))
        target = base / '候选'
        backup = base / '.candidate-previous'
        try:
            for name, data in files.items():
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            manifest = {'date': stamp, 'evidence': evidence, 'fingerprint': fingerprint,
                        'files': {name: _hash(data) for name, data in sorted(files.items())}}
            (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            if backup.exists():
                raise ValueError(f'previous candidate backup requires attention: {backup}')
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(stage, target)
            except Exception:
                if backup.exists():
                    os.replace(backup, target)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return {'ok': True, 'cmd': 'prepare', 'date': stamp, 'fingerprint': fingerprint,
                'index': str((target / 'index.html').relative_to(root)).replace('\\', '/'),
                'checks': {'document': True, 'evidence': True, 'resources': len(assets)}}
    except (OSError, ValueError, UnicodeError) as exc:
        return {'ok': False, 'cmd': 'prepare', 'date': stamp, 'error': str(exc)}


def _reviewed_candidate(root: Path, stamp: str) -> tuple[str, dict[str, bytes]]:
    folder = root / 'desk' / '版面' / stamp / '候选'
    if not folder.resolve().is_relative_to(root):
        raise ValueError('candidate directory escapes project root')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('date') != stamp or not isinstance(manifest.get('files'), dict):
        raise ValueError('candidate manifest date or files invalid')
    evidence = edition.issue_digest(root, stamp)
    if evidence != manifest.get('evidence'):
        raise ValueError('evidence changed; prepare and review a new candidate')
    files = {}
    for name, digest in manifest['files'].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise ValueError(f'missing or unsafe candidate file: {name}')
        data = path.read_bytes()
        if _hash(data) != digest:
            raise ValueError(f'candidate file changed: {name}')
        files[name] = data
    if 'index.html' not in files or any(name != 'index.html' and not name.startswith(f'assets/{stamp}/') for name in files):
        raise ValueError('candidate package contains invalid paths')
    fingerprint = _fingerprint(stamp, evidence, files)
    if fingerprint != manifest.get('fingerprint'):
        raise ValueError('candidate fingerprint does not match manifest')
    edition.check_document(root, stamp, files['index.html'].decode('utf-8'))
    receipt = json.loads((folder.parent / 'layout.json').read_text(encoding='utf-8'))
    if not isinstance(receipt, dict):
        raise ValueError('invalid layout review receipt')
    result = receipt.get('result')
    if (receipt.get('fingerprint') != fingerprint or not isinstance(result, dict)
        or result.get('ok') is not True or not result.get('measure')
        or result.get('errors') or result.get('warnings')):
        raise ValueError('full layout review missing, failed, or belongs to another candidate')
    return fingerprint, files


def reviewed_status(root: Path, stamp: str) -> dict:
    """Inspect the current reviewed candidate without modifying the project."""
    root = Path(root).resolve()
    try:
        stamp = _day(stamp)
        fingerprint, _ = _reviewed_candidate(root, stamp)
        return {'ok': True, 'date': stamp, 'fingerprint': fingerprint,
                'index': f'desk/版面/{stamp}/候选/index.html'}
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return {'ok': False, 'date': stamp, 'error': str(exc)}


def run(root: Path, stamp: str, approval: str = '') -> dict:
    root = Path(root).resolve()
    try:
        stamp = _day(stamp)
        fingerprint, files = _reviewed_candidate(root, stamp)
        if approval != fingerprint:
            raise ValueError('approval does not match current candidate fingerprint')
        site = (root / 'docs').resolve()
        if not site.is_relative_to(root):
            raise ValueError('docs directory escapes project root')
        for name in files:
            if not (site / name).resolve().is_relative_to(site):
                raise ValueError(f'unsafe release path: {name}')
        if not (site / f'{stamp}.html').resolve().is_relative_to(site):
            raise ValueError('unsafe archive path')
        for name, data in files.items():
            if name != 'index.html':
                _atomic_write(site / name, data)
        _atomic_write(site / f'{stamp}.html', files['index.html'])
        _atomic_write(site / 'index.html', files['index.html'])
        return {'ok': True, 'cmd': 'publish', 'date': stamp, 'fingerprint': fingerprint,
                'index': 'docs/index.html', 'archive': f'docs/{stamp}.html', 'resources': len(files) - 1}
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return {'ok': False, 'cmd': 'publish', 'date': stamp, 'error': str(exc)}
