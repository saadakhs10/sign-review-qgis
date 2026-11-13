# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 12 - 📁 CLOSEST PHOTOS WINDOW
Like opening a folder: for every sign in the review, its CLOSEST_PER_SIGN (config.py, 3) photos
taken nearest to the sign - never a cut-off photo - sorted by camera distance (nearest first)
and Left | Right of the camera. The sign's ★ BEST photo is always one of them (gold frame).
Nothing is taken out of the main window: every photo stays there too.
The blue bar has the same controls as the main window (Relocate, Delete, ★ Make best,
⚡ Finalize sign, ⭐ Move to My best …). The window opens at once; photos fill in as they arrive.
"""

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel)

from ..config import COLS, CLOSEST_PER_SIGN
from ..core.parsing import largest_box
from ..ui.widgets import TileGrid, clear_grid, make_window, fit_to_screen
from ..ui.selection_bar import SelectionBar
from ..ui.tile import Tile


class ClosestPhotosMixin:
    """📁 closest photos window - mixed into the review window."""

    # ── 12.1  open_best() : 📁 Closest photos button ───────────────────────────────────────────
    def open_best(self):
        for d in self.same_dialogs:
            if type(d) is BestDialog:           # not the ⭐ My best / ✂ Cut-off windows (subclasses)
                d.reload()
                d.raise_()
                return
        BestDialog(self).show()

    # ── 12.2  closest_fids() : up to CLOSEST_PER_SIGN nearest uncut photos of every sign ──────
    def closest_fids(self, per_sign=CLOSEST_PER_SIGN):
        """For every sign: its photos that are not cut off, nearest to the sign first, at most
        per_sign of them; the sign's ★ BEST photo (if not cut off) is always included.
        Returned nearest first over all signs (strictly by camera distance)."""
        present = set(self.all_fids())
        out = []
        for n, members in self.sign_members.items():
            ok = [f for f in members if f in present and not self._is_cut(f)
                  and self.distance_of(f) is not None]
            ok.sort(key=lambda f: self.distance_of(f))
            keep = ok[:per_sign]
            b = self.best.get(n)
            if b in ok and b not in keep:
                keep = [b] + keep[:per_sign - 1]
            out += keep
        return self.near_first(out)

    def _is_cut(self, f):
        if f in getattr(self, 'problems', {}):
            return True
        if not largest_box(self.get_info(f)['boxes']):
            return True
        return self.is_cut_off(f)

    # ── 12.3  update_best_folder() : count on the button, refresh the window ──────────────────
    def update_best_folder(self):
        """Folder button shows how many photos (and signs); an open folder window follows."""
        fids = self.closest_fids()
        signs = len({self.sign_no.get(f) for f in fids})
        self.btn_best.setText(f'📁 Closest photos ({len(fids)})')
        self.btn_best.setToolTip(f'{len(fids)} photos of {signs} signs: the {CLOSEST_PER_SIGN} photos taken '
                                 'nearest to each sign, never cut off - sorted by distance, Left | Right')
        for d in list(self.same_dialogs):
            if type(d) is BestDialog:
                d.reload()


# ══ 12.4  BestDialog : the Closest photos window (also the base of ⭐ My best and ✂ Cut-off) ══


class BestDialog(TileGrid, QDialog):
    """Closest photos of every sign, nearest first, sorted Left | Right of the camera.
    Opens at once: every tile is drawn straight away and its photo fills in when the review
    window's loader has it."""

    def __init__(self, rv):
        super().__init__(rv)
        self.rv, self.tiles, self.matches = rv, [], []
        self._waiting = []
        self._fill = QTimer(self)
        self._fill.setInterval(60)
        self._fill.timeout.connect(self._fill_tiles)
        self.setWindowTitle(f'📁 Closest photos - the {CLOSEST_PER_SIGN} nearest uncut photos of every sign')
        self.info_lbl = QLabel()
        scroll = self.make_grid()
        make_window(self)
        fit_to_screen(self, *self.size_for(COLS, 800))
        self.sel_bar = SelectionBar(rv, my_best=getattr(self, 'is_my_best', False))
        if hasattr(rv, 'add_fast_buttons'):            # ★ Make best, ⚡ Finalize sign (block 16)
            rv.add_fast_buttons(self.sel_bar)
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
        return self.rv.closest_fids()

    def info_text(self, left):
        n = len(self.matches)
        signs = len({self.rv.sign_no.get(f) for f in self.matches})
        return (f'<b>{n} photos of {signs} signs</b> – the {CLOSEST_PER_SIGN} taken nearest to each sign, '
                f'never cut off, nearest first: {left} left of camera, {n - left} right   –   '
                'every photo is still in the main window')

    def reload(self):
        rv = self.rv
        bar = self.scroll.verticalScrollBar()
        pos = bar.value()                               # a refresh keeps your place in the window
        self.matches = rv.near_first(self.fids_to_show())
        self.sides, self.road_axis = rv.classify_sides(self.matches)
        rv.forget_tiles(self.tiles)
        clear_grid(self.grid)
        self.tiles, self._waiting = [], []
        best = set(rv.best.values())
        rank = {}
        for f in self.matches:
            n = rv.sign_no.get(f)
            rank[n] = rank.get(n, 0) + 1
            extra = (f'sign {n} · {rank[n]} of {len(rv.sign_members.get(n, []))} photos' if n else '')
            d = rv.get_info(f)
            fut = rv.loader.submit(rv._thumb_key(d['url'], d['boxes']), 0, d['url'], d['boxes'])
            cap = rv.caption(f, extra)
            if f in best:
                cap = '<span style="color:#2e7d32;font-weight:bold">★ BEST</span>  ' + cap
            t = Tile(rv, f, None, cap, owner=self)
            if fut.done():
                t.set_image(rv._result(fut))
            else:
                t.show_loading()
                self._waiting.append((t, fut))
            if f in best:
                t.best = True
                t.refresh()
            self.tiles.append(t)
        self._cols = self.fit_cols()
        self.flow(self.tiles)
        rv.extra_tiles.extend(self.tiles)
        left = sum(1 for f in self.matches if self.sides.get(f) == 'L')
        self.info_lbl.setText(self.info_text(left))
        bar.setValue(pos)
        QTimer.singleShot(0, lambda: bar.setValue(pos))
        if self._waiting:
            self._fill.start()

    def _fill_tiles(self):
        still = []
        for t, fut in self._waiting:
            if not fut.done():
                still.append((t, fut))
                continue
            try:
                t.set_image(self.rv._result(fut))
            except RuntimeError:
                pass
        self._waiting = still
        if not still:
            self._fill.stop()

    def on_close(self, *args):
        self._fill.stop()
        self.rv.forget_tiles(self.tiles)
        for bar in [self.sel_bar]:
            if bar in self.rv.bars:
                self.rv.bars.remove(bar)
        if self in self.rv.same_dialogs:
            self.rv.same_dialogs.remove(self)

    def keyPressEvent(self, e):
        if self.rv.handle_select_keys(self, e):
            return
        super().keyPressEvent(e)
