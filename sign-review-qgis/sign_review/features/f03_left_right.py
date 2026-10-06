# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 3 - LEFT | RIGHT COLUMNS
Every photo goes to the LEFT columns when its camera angle is negative and to the
RIGHT columns when it is positive (see block 2). Photos taken driving the other way
are marked with ⇅. The grid is drawn with the left half and the right half side by side.
"""

import math

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QLabel


class LeftRightMixin:
    """Left | right columns - mixed into the review window."""

    # ── 3.1  main_heading() : main driving direction of the cluster ───────────────────────────
    def main_heading(self, fids):
        """Main driving direction of these photos (degrees), or None.
        The road axis comes from the doubled-angle mean (NW and SE give the same axis);
        it is then pointed the way MOST photos were driving."""
        hs = [self.get_info(f)['heading'] for f in fids]
        hs = [h for h in hs if h is not None]
        if not hs:
            return None
        s2 = sum(math.sin(math.radians(2 * h)) for h in hs)
        c2 = sum(math.cos(math.radians(2 * h)) for h in hs)
        axis = math.degrees(math.atan2(s2, c2)) / 2.0
        ahead = sum(1 for h in hs if math.cos(math.radians(h - axis)) >= 0)
        return axis % 360 if ahead >= len(hs) - ahead else (axis + 180) % 360

    # ── 3.2  is_opposite() : photo taken driving the other way? ───────────────────────────────
    def is_opposite(self, fid):
        """True if this photo was taken driving the other way than the main direction."""
        h = self.get_info(fid)['heading']
        ref = getattr(self, 'ref_heading', None)
        return h is not None and ref is not None and math.cos(math.radians(h - ref)) < 0

    # ── 3.3  classify_sides() : L / R for every photo from its own angle ──────────────────────
    def classify_sides(self, fids):
        """Left / right column for each photo, straight from the formula:
             focal = (W/2) / tan(FOV/2),  angle = atan((box centre x - W/2) / focal)
             angle < 0 -> 'L',  angle > 0 -> 'R',  unknown -> None"""
        self.ref_heading = self.main_heading(fids)
        sides = {}
        for f in fids:
            ang = self.camera_angle(f)
            sides[f] = None if ang is None else ('L' if ang < 0 else 'R')
        return sides, None


class LeftRightGridMixin:
    """Draws the tile grid as LEFT half | RIGHT half - mixed into every photo window."""

    # ── 3.4  flow() : lay the tiles out: LEFT half | RIGHT half ───────────────────────────────
    def flow(self, tiles):
        """Place the tiles. With 'Left | Right' on: signs on the LEFT side of the road go
        in the left columns, signs on the RIGHT side in the right columns."""
        for t in tiles:
            self.grid.removeWidget(t)
        for h in getattr(self, '_side_headers', []):
            try:
                self.grid.removeWidget(h)
                h.deleteLater()
            except RuntimeError:
                pass
        self._side_headers = []
        c = self._cols
        split = c >= 2
        if not split:
            for i, t in enumerate(tiles):
                self.grid.addWidget(t, i // c, i % c)
            return

        sides = getattr(self, 'sides', {})
        left, right, unknown = [], [], []
        for t in tiles:
            side = sides.get(t.fid)
            (left if side == 'L' else right if side == 'R' else unknown).append(t)
        left += unknown
        l_txt, r_txt = 'LEFT of camera  (angle &lt; 0°)', 'RIGHT of camera  (angle &gt; 0°)'

        half = c // 2
        right_start = c - half
        for text, col, n in (('◀  %s  – %d' % (l_txt, len(left)), 0, len(left)),
                             ('%s  – %d  ▶' % (r_txt, len(right)), right_start, len(right))):
            h = QLabel(f'<b>{text}</b>')
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.setStyleSheet('background:#eceff1; padding:4px; border-radius:3px;')
            self.grid.addWidget(h, 0, col, 1, half)
            self._side_headers.append(h)
        for i, t in enumerate(left):
            self.grid.addWidget(t, 1 + i // half, i % half)
        for i, t in enumerate(right):
            self.grid.addWidget(t, 1 + i // half, right_start + i % half)
