# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 12 - 📁 CLOSEST PHOTOS WINDOW
Like opening a folder: one window with the highlighted photo of every sign (block 5),
sorted Left | Right. Nothing is ticked automatically.
"""

from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel)

from ..config import COLS
from ..core.io import fetch
from ..core.imaging import render
from ..ui.widgets import TileGrid, wait_for, clear_grid, make_window, fit_to_screen
from ..ui.selection_bar import SelectionBar
from ..ui.tile import Tile


class ClosestPhotosMixin:
    """📁 closest photos window - mixed into the review window."""

    # ── 12.1  open_best() : 📁 Closest photos button ───────────────────────────────────────────
    def open_best(self):
        for d in self.same_dialogs:
            if type(d) is BestDialog:           # not the ⭐ My best window (a subclass)
                d.reload()
                d.raise_()
                return
        BestDialog(self).show()

    # ── 12.2  update_best_folder() : count on the button, refresh the window ──────────────────
    def update_best_folder(self):
        """Folder button shows how many signs; an open folder window follows the review."""
        n = len([f for f in self.best.values() if f in set(self.all_fids())])
        self.btn_best.setText(f'📁 Closest photos ({n})')
        for d in list(self.same_dialogs):
            if type(d) is BestDialog:
                d.reload()


# ══ 12.3  BestDialog : the Closest photos window ══════════════════════════════════════════════


class BestDialog(TileGrid, QDialog):
    """Like opening a folder: the best photo of every sign in the review (nearest to the
    camera and not cut off), nearest first, sorted Left | Right of the camera."""

    def __init__(self, rv):
        super().__init__(rv)
        self.rv, self.tiles, self.matches = rv, [], []
        self.setWindowTitle('📁 Closest photos - best photo of every sign')
        self.info_lbl = QLabel()
        scroll = self.make_grid()
        make_window(self)
        fit_to_screen(self, *self.size_for(COLS, 800))
        self.sel_bar = SelectionBar(rv, my_best=getattr(self, 'is_my_best', False))
        lay = QVBoxLayout(self)
        lay.addWidget(self.sel_bar)
        lay.addWidget(self.info_lbl)
        lay.addWidget(scroll)
        self.finished.connect(self.on_close)
        rv.same_dialogs.append(self)
        self.reload()

    def order(self):
        return list(self.matches)

    def fids_to_show(self):
        all_ = set(self.rv.all_fids())
        return [f for f in self.rv.best.values() if f in all_]

    def info_text(self, left):
        n = len(self.matches)
        return (f'<b>{n} signs</b> – best photo of each (nearest to the camera, not cut '
                f'off): {left} left of camera, {n - left} right')

    def reload(self):
        rv = self.rv
        fids = self.fids_to_show()
        futs = [rv.pool.submit(fetch, rv.get_info(f)['url']) for f in fids]
        if not wait_for(futs, 'Downloading images…', self):
            return
        paths = {f: fut.result() for f, fut in zip(fids, futs)}
        self.matches = rv.near_first(fids)
        self.sides, self.road_axis = rv.classify_sides(self.matches)
        rv.forget_tiles(self.tiles)
        clear_grid(self.grid)
        self.tiles = []
        for f in self.matches:
            n = rv.sign_no.get(f)
            extra = f'sign {n} ({len(rv.sign_members.get(n, []))} photos)' if n else ''
            t = Tile(rv, f, render(paths[f], rv.get_info(f)['boxes'], True),
                     rv.caption(f, extra), owner=self)
            if f in rv.best.values():
                t.best = True
                t.refresh()
            self.tiles.append(t)
        self._cols = self.fit_cols()
        self.flow(self.tiles)
        rv.extra_tiles.extend(self.tiles)
        left = sum(1 for f in self.matches if self.sides.get(f) == 'L')
        self.info_lbl.setText(self.info_text(left))

    def on_close(self, *args):
        self.rv.forget_tiles(self.tiles)
        if self.sel_bar in self.rv.bars:
            self.rv.bars.remove(self.sel_bar)
        if self in self.rv.same_dialogs:
            self.rv.same_dialogs.remove(self)

    def keyPressEvent(self, e):
        if self.rv.handle_select_keys(self, e):
            return
        super().keyPressEvent(e)
