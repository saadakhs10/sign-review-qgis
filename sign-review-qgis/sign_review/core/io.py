# SPDX-License-Identifier: GPL-2.0-or-later
"""Downloading and caching the photos behind the image links.

Only real images are kept: a reply that is not a JPEG / PNG / WebP / GIF / BMP / TIFF
(for example an error message sent when the server is busy) is never cached, and a bad
file already in the cache is deleted and downloaded again. Failed downloads are retried
a few times, and tried again later instead of being given up for the whole session."""

import os
import time
import hashlib
import json
import struct
import threading
import urllib.request

from qgis.PyQt.QtGui import QImageReader

from ..config import CACHE

RETRIES = 3
TIMEOUT_S = 30
RETRY_AFTER_S = 60

_FAILED = {}
_SIZES = {}
_VALID = set()
_LOCK = threading.Lock()


def cache_path(url):
    return os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + '.img')


def is_image_bytes(head):
    """True if the first bytes are those of an image file."""
    return (head.startswith(b'\xff\xd8\xff')
            or head.startswith(b'\x89PNG\r\n\x1a\n')
            or (head[:4] == b'RIFF' and head[8:12] == b'WEBP')
            or head.startswith((b'GIF87a', b'GIF89a', b'BM', b'II*\x00', b'MM\x00*')))


def _forget(path):
    with _LOCK:
        _VALID.discard(path)
        _SIZES.pop(path, None)


def cached(url):
    """Path of the already-downloaded photo, or None. Never touches the network.
    A cached file that is not an image is deleted, so it will be downloaded again."""
    if not url:
        return None
    p = cache_path(str(url))
    if p in _VALID:
        return p
    try:
        with open(p, 'rb') as f:
            head = f.read(16)
    except OSError:
        return None
    if is_image_bytes(head):
        _VALID.add(p)
        return p
    try:
        os.remove(p)
    except OSError:
        pass
    _forget(p)
    return None


def fetch(url):
    """Download an image once and keep it in the cache. Returns path or None.
    Call from worker threads (ThreadPoolExecutor), never in a loop on the GUI thread."""
    if not url:
        return None
    url = str(url)
    p = cached(url)
    if p:
        return p
    last = _FAILED.get(url)
    if last and time.time() - last < RETRY_AFTER_S:
        return None
    error = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = r.read()
            if not is_image_bytes(data[:16]):
                raise ValueError('reply is not an image (%d bytes, starts %r)' % (len(data), data[:20]))
            path = cache_path(url)
            tmp = '%s.%d.part' % (path, threading.get_ident())
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)
            _forget(path)
            _VALID.add(path)
            _FAILED.pop(url, None)
            return path
        except Exception as e:
            error = e
            time.sleep(1.5 * (attempt + 1))
    _FAILED[url] = time.time()
    print('Download failed:', url, error)
    return None


def image_size(path):
    """(width, height) from the file header only (no decoding), cached."""
    if not path:
        return None, None
    if path not in _SIZES:
        sz = QImageReader(path).size()
        if sz.width() <= 0:
            return None, None
        _SIZES[path] = (sz.width(), sz.height())
    return _SIZES[path]


def image_width(path):
    return image_size(path)[0]


# ── Photo size without downloading the photo ──────────────────────────────────────────────
# Grouping and Relocate only need the photo's width and height (W, H), which are stored in
# the first bytes of the file. probe() reads just those bytes (a few KB instead of ~1 MB)
# and remembers the size on disk, so opening many points is fast and the full photos are
# downloaded only for the page being shown.
SIZE_FILE = os.path.join(CACHE, 'photo_sizes.json')
PROBE_MAX = 512 * 1024
_KNOWN = None


def _known():
    global _KNOWN
    if _KNOWN is None:
        try:
            with open(SIZE_FILE, encoding='utf-8') as f:
                _KNOWN = {k: tuple(v) for k, v in json.load(f).items()}
        except Exception:
            _KNOWN = {}
    return _KNOWN


def save_sizes():
    try:
        tmp = SIZE_FILE + '.part'
        with _LOCK:
            data = dict(_known())
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, SIZE_FILE)
    except OSError:
        pass


def header_size(data):
    """(width, height) read from the first bytes of a PNG / JPEG / WebP / GIF / BMP, or None."""
    try:
        if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
            return struct.unpack('>II', data[16:24])
        if data.startswith((b'GIF87a', b'GIF89a')) and len(data) >= 10:
            return struct.unpack('<HH', data[6:10])
        if data.startswith(b'BM') and len(data) >= 26:
            w, h = struct.unpack('<ii', data[18:26])
            return w, abs(h)
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 30:
            kind = data[12:16]
            if kind == b'VP8X':
                return (1 + int.from_bytes(data[24:27], 'little'),
                        1 + int.from_bytes(data[27:30], 'little'))
            if kind == b'VP8 ':
                w, h = struct.unpack('<HH', data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if kind == b'VP8L':
                b = data[21:25]
                return (1 + (((b[1] & 0x3F) << 8) | b[0]),
                        1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6)))
        if data.startswith(b'\xff\xd8'):
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                m = data[i + 1]
                if m == 0xFF:
                    i += 1
                    continue
                if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                    i += 2
                    continue
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack('>H', data[i + 2:i + 4])[0]
    except (struct.error, IndexError):
        pass
    return None


def known_size(url):
    """(width, height) of the photo if known (downloaded or probed before), else None."""
    if not url:
        return None
    p = cached(url)
    if p:
        w, h = image_size(p)
        if w:
            return w, h
    return _known().get(str(url))


def probe(url):
    """Worker thread: read only the start of the photo to learn its size (W, H).
    If the size is not in the first bytes the whole photo is downloaded instead.
    Returns (w, h) or None."""
    if not url:
        return None
    url = str(url)
    s = known_size(url)
    if s:
        return s
    last = _FAILED.get(url)
    if last and time.time() - last < RETRY_AFTER_S:
        return None
    error = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data, s = b'', None
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                while len(data) < PROBE_MAX:
                    chunk = r.read(16384)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) >= 16 and not is_image_bytes(data[:16]):
                        raise ValueError('reply is not an image')
                    s = header_size(data)
                    if s:
                        break
            if s and s[0] > 0 and s[1] > 0:
                with _LOCK:
                    _known()[url] = (int(s[0]), int(s[1]))
                return int(s[0]), int(s[1])
            p = fetch(url)
            w, h = image_size(p)
            return (w, h) if w else None
        except Exception as e:
            error = e
            time.sleep(1.5 * (attempt + 1))
    _FAILED[url] = time.time()
    print('Download failed:', url, error)
    return None
