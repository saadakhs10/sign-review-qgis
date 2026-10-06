# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 1 - READING THE LAYER AND THE PHOTOS
Reads the fields of every point (img_link, boxes, heading, original_x / original_y,
confidence) and remembers them, downloads the photos in the background and knows
each photo's width and height in pixels.
"""

import re

from qgis.core import QgsFeatureRequest

from ..core.io import cached, fetch, image_size
from ..core.parsing import parse_boxes, largest_box, to_float
from ..ui.widgets import wait_for

from ..ui.widgets import wait_for


class PhotoDataMixin:
    """Reading the layer and the photos - mixed into the review window."""

    # ── 1.1  build_info() : collect the fields of one feature ─────────────────────────────────
    def build_info(self, f):
        return {
            'url': f[self.idx_link],
            'boxes': parse_boxes(f[self.idx_box]) if self.idx_box >= 0 else [],
            'heading': to_float(f[self.idx_head]) if self.idx_head >= 0 else None,
            'cam': self.camera_of(f),
            'conf': self.conf_of(f),
        }

    # ── 1.2  conf_of() : lowest detector confidence ───────────────────────────────────────────
    def conf_of(self, f):
        """Lowest detector confidence in the CONF_FIELD (None if the field is missing)."""
        if self.idx_conf < 0:
            return None
        nums = [float(x) for x in re.findall(r'\d*\.\d+|\d+', str(f[self.idx_conf] or ''))]
        nums = [x for x in nums if 0.0 <= x <= 1.0]
        return min(nums) if nums else None

    # ── 1.3  all_info() : fields of the whole layer (built on demand) ─────────────────────────
    def all_info(self):
        """Info for every point of the layer (read once, reused)."""
        if self._all is None:
            self._all = {f.id(): self.build_info(f) for f in self.layer.getFeatures()}
        return self._all

    # ── 1.4  get_info() : fields of one point (cached) ────────────────────────────────────────
    def get_info(self, fid):
        if fid in self.info:
            return self.info[fid]
        if self._all and fid in self._all:
            return self._all[fid]
        f = next(self.layer.getFeatures(QgsFeatureRequest().setFilterFid(fid)), None)
        return self.build_info(f) if f else {'url': None, 'boxes': [], 'heading': None, 'cam': None,
                                             'conf': None}

    # ── 1.5  camera_of() : camera position from original_x / original_y ───────────────────────
    def camera_of(self, f):
        """Camera position (lon, lat) in WGS84: original_x/y, else the point itself."""
        if self.idx_ox >= 0 and self.idx_oy >= 0:
            lon, lat = to_float(f[self.idx_ox]), to_float(f[self.idx_oy])
            if lon is not None and lat is not None:
                return lon, lat
        if f.hasGeometry() and not f.geometry().isEmpty():
            try:
                p = self.to_wgs.transform(f.geometry().centroid().asPoint())
                return p.x(), p.y()
            except Exception:
                pass
        return None

    # ── 1.6  hash_key() : key of one photo + box ──────────────────────────────────────────────
    @staticmethod
    def hash_key(d):
        return f"{d['url']}|{largest_box(d['boxes'])}"

    # ── 1.7  hash_of() : look fingerprint of a sign (dHash) ───────────────────────────────────
    def hash_of(self, fid):
        h = self.hashes.get(self.hash_key(self.get_info(fid)))
        return int(h, 16) if h else None

    # ── 1.8  sharp_of() : sharpness of a sign crop ────────────────────────────────────────────
    def sharp_of(self, fid):
        return self.sharp.get(self.hash_key(self.get_info(fid)))

    # ── 1.9  width_of() : photo width in pixels (W) ───────────────────────────────────────────
    def width_of(self, fid):
        """Pixel width of the point's image (None if not downloaded yet)."""
        url = self.get_info(fid)['url']
        if not url:
            return None
        return image_size(cached(url))[0]

    # ── 1.10  height_of() : photo height in pixels ────────────────────────────────────────────
    def height_of(self, fid):
        url = self.get_info(fid)['url']
        if not url:
            return None
        return image_size(cached(url))[1]

    # ── 1.11  photo_id() : same photo = same camera position + heading ────────────────────────
    def photo_id(self, fid):
        """Same camera position + heading = the same photo (frame)."""
        d = self.get_info(fid)
        if not d['cam'] or d['heading'] is None:
            return ('fid', fid)
        return (round(d['cam'][0], 7), round(d['cam'][1], 7), round(d['heading'], 1))

    # ── 1.12  ensure_downloads() : download every photo not in the cache yet ──────────────────
    def ensure_downloads(self, fids, label):
        """Download (in the background, 12 at a time) every photo not cached yet.
        Returns False if the user pressed Cancel."""
        todo = {}
        for f in fids:
            url = self.get_info(f)['url']
            if url and not cached(url) and str(url) not in todo:
                todo[str(url)] = self.pool.submit(fetch, url)
        return wait_for(todo.values(), label, self)

    # ── 1.13  caption() : text under a tile: fid | distance | angle ───────────────────────────
    def caption(self, fid, extra=''):
        dist = self.distance_of(fid)
        d = f'~{dist:.1f} m' if dist is not None else '? m'
        ang = self.camera_angle(fid)
        a = f'{ang:+.0f}°' if ang is not None else '?°'
        if self.is_opposite(fid):
            a += ' ⇅'
        return f'fid {fid}  |  {d}  |  {a}' + (f'  |  {extra}' if extra else '')
