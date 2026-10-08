# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 5 - BEST PHOTO (GOLD FRAME) AND QUALITY FLAGS
The highlighted photo of a sign ("★ BEST", gold frame) is the photo NEAREST to the
camera whose box is NOT cut off at the photo border. One per sign.
Quality flags under a tile (information only): edge, tiny, low conf, blurry, 1 photo, off-ray.
"""

import math

from qgis.PyQt.QtGui import QImage

from ..config import (EDGE_PX, TINY_PX, LOW_CONF, OUTLIER_M)
from ..core.io import cached
from ..core.parsing import largest_box
from ..core.imaging import (sharpness_image, read_region, box_rect)


class BestPhotoMixin:
    """Best photo (gold frame) and quality flags - mixed into the review window."""

    # ── 5.1  best_photo() : nearest photo that is not cut off ─────────────────────────────────
    def best_photo(self, members):
        """The ONE photo highlighted for a sign (gold frame, "★ BEST"):
        the photo nearest to the camera whose box is NOT cut off at the photo border.
        None if every photo of the sign is cut off (then nothing is highlighted)."""
        ok = [f for f in members if not self.is_cut_off(f) and self.distance_of(f) is not None]
        if not ok:
            return None
        return min(ok, key=lambda f: self.distance_of(f))

    # ── 5.2  is_cut_off() : box touches the photo border? ─────────────────────────────────────
    def is_cut_off(self, f):
        """True if the box touches the photo border (or there is no box)."""
        b = largest_box(self.get_info(f)['boxes'])
        if not b:
            return True
        w, hh = self.width_of(f), self.height_of(f)
        return bool(w and (b[0] <= EDGE_PX or b[2] >= w - EDGE_PX or b[1] <= EDGE_PX
                           or (hh and b[3] >= hh - EDGE_PX)))

    # ── 5.3  box_problem() : cut off or tiny? ─────────────────────────────────────────────────
    def box_problem(self, f):
        """True if the box is cut off at the image border or tiny -> its angle / size lie."""
        b = largest_box(self.get_info(f)['boxes'])
        w, hh = self.width_of(f), self.height_of(f)
        if not b:
            return True
        if w and (b[0] <= EDGE_PX or b[2] >= w - EDGE_PX or b[1] <= EDGE_PX or (hh and b[3] >= hh - EDGE_PX)):
            return True
        return b[2] - b[0] < TINY_PX

    # ── 5.4  quality_flags() : the red notes under a tile ─────────────────────────────────────
    def quality_flags(self, f):
        """Pure-geometry checks on one photo -> list of short flags ('' = looks fine)."""
        out = []
        d = self.get_info(f)
        b = largest_box(d['boxes'])
        w = self.width_of(f)
        if not b:
            return ['no box']
        if w:
            h_img = self.height_of(f)
            if b[0] <= EDGE_PX or b[2] >= w - EDGE_PX or b[1] <= EDGE_PX or (h_img and b[3] >= h_img - EDGE_PX):
                out.append('edge')
        if b[2] - b[0] < TINY_PX:
            out.append('tiny')
        conf = d.get('conf')
        if conf is not None and conf < LOW_CONF:
            out.append('low conf')
        n = self.sign_no.get(f)
        if n and len(self.sign_members[n]) == 1:
            out.append('1 photo')
        if n and f in self.rays and self.L is not None:
            lon, lat, meth, _ = self.sign_pos[n]
            if meth == 'triangulated':
                px, py = self.L.xy(lon, lat)
                (cx, cy), (dx, dy), _ = self.rays[f]
                vx, vy = px - cx, py - cy
                along = vx * dx + vy * dy
                miss = math.sqrt(max(0.0, vx * vx + vy * vy - along * along)) if along > 0 else 99
                if miss > OUTLIER_M:
                    out.append('off-ray')
        return out

    # ── 5.5  near_set() : close-up photos of a sign ───────────────────────────────────────────
    def near_set(self, members):
        """The close-up photos of a sign: box not cut off / tiny, and at least half as wide
        as the biggest such box. Only these are compared for sharpness (fair comparison:
        same size, measured at the same width)."""
        ok = [f for f in members if not self.box_problem(f)]
        if not ok:
            return []
        wmax = max(self.box_width(f) for f in ok)
        return [f for f in ok if self.box_width(f) >= 0.5 * wmax]

    # ── 5.6  sharp_at() : sharpness at a fixed width ──────────────────────────────────────────
    def sharp_at(self, f, width):
        key = (f, width)
        if key not in self._sharp_cache:
            d = self.get_info(f)
            b = largest_box(d['boxes'])
            img, r = read_region(cached(d['url']), box_rect(b)) if b else (QImage(), None)
            self._sharp_cache[key] = (sharpness_image(img, (0, 0, img.width(), img.height()), width)
                                      if not img.isNull() else None)
        return self._sharp_cache[key]

    # ── 5.7  rel_sharpness() : sharpness compared with the sharpest close-up ──────────────────
    def rel_sharpness(self, members):
        """{fid: sharpness / sharpest} for the close-up photos of one sign.
        Only photos already downloaded are compared (no download just for this)."""
        near = [f for f in self.near_set(members) if cached(self.get_info(f)['url'])]
        if len(near) < 2:
            return {}
        width = max(8, min(64, min(self.box_width(f) for f in near)))
        sh = {f: self.sharp_at(f, width) or 0.0 for f in near}
        top = max(sh.values())
        return {f: (v / top if top > 0 else 1.0) for f, v in sh.items()}
