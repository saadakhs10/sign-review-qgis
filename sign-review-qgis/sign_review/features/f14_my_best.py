# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 14 - ⭐ MY BEST: PUT THE PHOTOS YOU CHOSE IN THEIR OWN WINDOW
Click ⭐ on a tile (or select photos and press "⭐ Move to My best" in the blue bar):
the photo leaves the main window and goes to the ⭐ My best window, so the photos you
chose and the rest are seen apart. "↩ Back" (on the tile or in that window's blue bar)
puts it back in the main window.
Your choice is remembered for this layer (also after closing QGIS) in the cache folder:
    my_best.json  ->  {layer source: [feature ids]}
Grouping, Left | Right and 📁 Closest photos still use every point.
"""

import json
import os

from ..config import CACHE, PER_PAGE
from .f12_closest_photos import BestDialog

PICK_FILE = os.path.join(CACHE, 'my_best.json')


def _read_all():
    try:
        with open(PICK_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


class MyBestMixin:
    """⭐ My best - mixed into the review window."""

    # ── 14.1  load_picked() / save_picked() : remembered per layer ────────────────────────────
    def load_picked(self):
        try:
            return set(int(f) for f in _read_all().get(self.layer.source(), []))
        except Exception:
            return set()

    def save_picked(self):
        data = _read_all()
        data[self.layer.source()] = sorted(self.picked)
        if not self.picked:
            data.pop(self.layer.source(), None)
        try:
            tmp = PICK_FILE + '.part'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            os.replace(tmp, PICK_FILE)
        except OSError:
            pass

    # ── 14.2  all_fids() : every point in the review (main window + My best) ──────────────────
    def all_fids(self):
        return [i[0] for i in getattr(self, '_items_all', None) or self.items]

    # ── 14.3  split_picked() : main window shows only the photos NOT in My best ───────────────
    def split_picked(self):
        """Call right after the photos are ordered: keeps every photo in _items_all and
        leaves only the not-chosen ones in the main window (self.items)."""
        self._items_all = list(self.items)
        self.items = [i for i in self._items_all if i[0] not in self.picked]
        self.pages = max(1, (len(self.items) + PER_PAGE - 1) // PER_PAGE)

    def unsplit(self):
        """Before ordering again: put every photo back in self.items."""
        if getattr(self, '_items_all', None) is not None:
            self.items = list(self._items_all)

    # ── 14.4  pick() / unpick() : move photos to My best and back ─────────────────────────────
    def pick(self, fids):
        new = [f for f in fids if f not in self.picked]
        if not new:
            return
        self.picked.update(new)
        self._after_pick_change(new)
        self.open_my_best()

    def unpick(self, fids):
        back = [f for f in fids if f in self.picked]
        if not back:
            return
        self.picked.difference_update(back)
        self._after_pick_change(back)

    def pick_toggle(self, fid):
        if fid in self.picked:
            self.unpick([fid])
        else:
            self.pick([fid])

    def pick_selected(self):
        self.pick([f for f in self.all_fids() if f in self.selected])

    def unpick_selected(self):
        self.unpick([f for f in self.all_fids() if f in self.selected])

    def _after_pick_change(self, fids):
        self.save_picked()
        self.selected.difference_update(fids)
        keep = self.page
        if getattr(self, '_items_all', None) is not None:
            self.items = list(self._items_all)
        self.split_picked()
        self.sides, self.road_axis = self.classify_sides(self.order())
        self.goto(min(keep, self.pages - 1))
        self.selection_changed()
        self.update_my_best()

    # ── 14.5  open_my_best() / update_my_best() : the ⭐ My best window ───────────────────────
    def open_my_best(self):
        for d in self.same_dialogs:
            if isinstance(d, MyBestDialog):
                d.reload()
                return
        MyBestDialog(self).show()
        self.update_my_best()

    def update_my_best(self):
        present = set(self.all_fids())
        n = len([f for f in self.picked if f in present])
        self.btn_my_best.setText(f'⭐ My best ({n})')
        for d in list(self.same_dialogs):
            if isinstance(d, MyBestDialog):
                d.reload()


# ══ 14.6  MyBestDialog : the ⭐ My best window ═════════════════════════════════════════════════


class MyBestDialog(BestDialog):
    """The photos you chose, nearest first, sorted Left | Right of the camera.
    ↩ Back (tile) or "↩ Back to review" (blue bar) returns them to the main window."""

    is_my_best = True

    def __init__(self, rv):
        super().__init__(rv)
        self.setWindowTitle('⭐ My best - the photos you chose')

    def fids_to_show(self):
        present = set(self.rv.all_fids())
        return [f for f in self.rv.picked if f in present]

    def info_text(self, left):
        n = len(self.matches)
        if not n:
            return ('<b>No photos yet</b> – click ⭐ on a tile, or select photos and press '
                    '"⭐ Move to My best", to put them here.')
        return (f'<b>{n} photos you chose</b>: {left} left of camera, {n - left} right   –   '
                '↩ Back puts a photo back in the main window')
