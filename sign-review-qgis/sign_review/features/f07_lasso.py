# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 7 - LASSO (drag a rectangle to select many photos)
Press the mouse on a photo and drag: a blue rectangle follows the mouse (and the grid
scrolls at the edges). On release every photo the rectangle touches is selected.
"""

from qgis.PyQt.QtCore import QRect


class LassoMixin:
    """Lasso (drag a rectangle to select many photos) - mixed into the review window."""

    # ── 7.1  reviewer() : the main window ─────────────────────────────────────────────────────
    def reviewer(self):
        return getattr(self, 'rv', self)

    # ── 7.2  lasso_press() : mouse pressed: remember the start ────────────────────────────────
    def lasso_press(self, gpos):
        self._lasso_origin = self.grid_host.mapFromGlobal(gpos)
        self._lasso_active = False

    # ── 7.3  lasso_move() : mouse moved: draw the rectangle ───────────────────────────────────
    def lasso_move(self, gpos):
        if self._lasso_origin is None:
            return
        p = self.grid_host.mapFromGlobal(gpos)
        if not self._lasso_active and (p - self._lasso_origin).manhattanLength() > 10:
            self._lasso_active = True
            self.rubber.show()
        if self._lasso_active:
            self.rubber.setGeometry(QRect(self._lasso_origin, p).normalized())
            self.scroll.ensureVisible(p.x(), p.y(), 30, 30)

    # ── 7.4  lasso_release() : mouse released: select what it touches ─────────────────────────
    def lasso_release(self, gpos):
        """Finish a drag: select every picture the rectangle touches. Returns True if it was a drag."""
        dragged = self._lasso_active
        if dragged:
            self.lasso_move(gpos)
            rect = self.rubber.geometry()
            hits = [t.fid for t in getattr(self, 'tiles', []) if t.geometry().intersects(rect)]
            self.rubber.hide()
            self.reviewer().select_many(hits)
        self._lasso_origin, self._lasso_active = None, False
        return dragged
