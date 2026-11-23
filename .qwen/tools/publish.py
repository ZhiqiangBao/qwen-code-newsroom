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
import issue_quality
import review

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


def _require_layout(folder: Path, fingerprint: str, page_ids: list[str]) -> None:
    receipt = json.loads((folder / 'layout.json').read_text(encoding='utf-8'))
    if not isinstance(receipt, dict) or receipt.get('fingerprint') != fingerprint:
        raise ValueError('量尺回执缺失或属于另一份候选')
    result = receipt.get('result')
    if (not isinstance(result, dict) or result.get('ok') is not True
        or result.get('errors') or result.get('warnings')):
        raise ValueError('整期版面量尺未通过')
    scale = result.get('scale')
    measures = result.get('measure')
    if (type(scale) is not int or scale < 1 or result.get('page_width_px') != review.PAGE_W
        or not isinstance(measures, list) or len(measures) != len(page_ids)):
        raise ValueError('量尺回执缺少完整版面或纸宽无效')
    for i, (pid, measure) in enumerate(zip(page_ids, measures, strict=True), 1):
        name = f'{i:02d}_{pid.upper()}.png'
        if not isinstance(measure, dict) or measure.get('id') != pid or measure.get('page') != name:
            raise ValueError(f'{pid.upper()} 的量尺回执与校样顺序不符')
        size = measure.get('px')
        if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
            raise ValueError(f'{pid.upper()} 的量尺尺寸无效')
        failure = review.dimension_error(*size, scale)
        if failure:
            raise ValueError(f'{pid.upper()} {failure}')
        if _hash((folder / name).read_bytes()) != measure.get('sha256'):
            raise ValueError(f'{pid.upper()} 校样图片与量尺回执不一致')


def _require_final_review(path: Path | None, fingerprint: str, page_ids: list[str], figure_ids: set[str]) -> None:
    if path is None:
        raise ValueError('缺少主编终审记录，请提供 --final-review')
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(record, dict) or record.get('fingerprint') != fingerprint:
        raise ValueError('主编终审记录与当前候选指纹不一致')
    reviewer = record.get('reviewer')
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError('主编终审记录缺少验收人')
    editorial = record.get('editorial')
    if not isinstance(editorial, dict) or any(editorial.get(key) is not True
            for key in ('facts', 'prose', 'image_rights')):
        raise ValueError('主编尚未确认事实、文体或图源')
    images = record.get('images')
    if not isinstance(images, dict) or images.keys() != figure_ids:
        raise ValueError('须提交实际见报配图逐张验收结果')
    for fid, image in images.items():
        if (not isinstance(image, dict) or not isinstance(image.get('reviewer'), str)
            or not image['reviewer'].strip()
            or any(image.get(key) is not True for key in ('provenance', 'matches_article', 'print'))):
            raise ValueError(f'配图 {fid} 的来源、稿件对应或成报效果未通过')
    desktop = record.get('desktop')
    if not isinstance(desktop, dict) or desktop.keys() != set(page_ids):
        raise ValueError('主编须逐版填写桌面校样结果')
    for pid in page_ids:
        checked = desktop[pid]
        if not isinstance(checked, dict) or any(checked.get(key) is not True
                for key in ('reading_order', 'captions', 'no_clipping')):
            raise ValueError(f'{pid.upper()} 的阅读顺序、图注或裁切核对未通过')
        gap, width = checked.get('column_bottom_gap_px'), checked.get('column_width_px')
        if (type(gap) not in {int, float} or type(width) not in {int, float}
            or not 0 < width < review.PAGE_W or not 0 <= gap <= width):
            raise ValueError(f'{pid.upper()} 的栏末行高差应在一栏宽以内')
    mobile = record.get('mobile')
    if (not isinstance(mobile, dict) or mobile.get('width_px') != 320
        or any(mobile.get(key) is not True for key in ('reading_order', 'navigation', 'source_links'))):
        raise ValueError('主编尚未确认 320px 版的阅读顺序、导航或出处链接')


def _reviewed_candidate(root: Path, stamp: str) -> tuple[str, dict[str, bytes], list[str], set[str]]:
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
    document = files['index.html'].decode('utf-8')
    edition.check_document(root, stamp, document)
    quality = issue_quality.check_issue(document, edition.load_evidence(root, stamp))
    if not quality['ok']:
        raise ValueError('成报硬指标未通过：' + '；'.join(quality['errors']))
    pages = [page['id'] for page in quality['pages']]
    figures = {figure['id'].strip() for page in quality['pages'] for figure in page['figures']}
    _require_layout(folder.parent, fingerprint, pages)
    return fingerprint, files, pages, figures


def reviewed_status(root: Path, stamp: str) -> dict:
    """Inspect the current reviewed candidate without modifying the project."""
    root = Path(root).resolve()
    try:
        stamp = _day(stamp)
        fingerprint, _, _, _ = _reviewed_candidate(root, stamp)
        return {'ok': True, 'date': stamp, 'fingerprint': fingerprint,
                'index': f'desk/版面/{stamp}/候选/index.html'}
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return {'ok': False, 'date': stamp, 'error': str(exc)}


def run(root: Path, stamp: str, approval: str = '', final_review: Path | None = None) -> dict:
    root = Path(root).resolve()
    try:
        stamp = _day(stamp)
        fingerprint, files, pages, figures = _reviewed_candidate(root, stamp)
        if approval != fingerprint:
            raise ValueError('approval does not match current candidate fingerprint')
        _require_final_review(final_review, fingerprint, pages, figures)
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
