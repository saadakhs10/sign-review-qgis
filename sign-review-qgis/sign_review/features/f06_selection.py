# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 6 - SELECTING PHOTOS (click, Shift+click, Select all, Clear)
Click = select / unselect, Shift+click = a run of photos, tick box = select,
Select all / Clear in the blue bar (Ctrl+A / Esc). Selected points are highlighted
on the map in yellow with a blue outline.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsFeatureRequest
from qgis.gui import QgsHighlight


class SelectionMixin:
    """Selecting photos (click, shift+click, select all, clear) - mixed into the review window."""

    # ── 6.1  click_select() : click / Shift+click on a photo ──────────────────────────────────
    def click_select(self, owner, fid, shift):
        """Click = add / remove this picture.  Shift (+Ctrl) + click = add the whole run
        from the last clicked picture to this one."""
        order = owner.order()
        if shift and self.anchor in order and fid in order:
            a, b = order.index(self.anchor), order.index(fid)
            self.selected |= set(order[min(a, b):max(a, b) + 1])
        else:
            self.selected ^= {fid}
        self.anchor = fid
        self.selection_changed()

    # ── 6.2  set_selected() : tick box on a tile ──────────────────────────────────────────────
    def set_selected(self, fid, on):
        if on:
            self.selected.add(fid)
        else:
            self.selected.discard(fid)
        self.anchor = fid
        self.selection_changed()

    # ── 6.3  select_many() : add many photos (used by the lasso) ──────────────────────────────
    def select_many(self, fids):
        if fids:
            self.selected |= set(fids)
            self.anchor = fids[-1]
            self.selection_changed()

    # ── 6.4  select_all_shown() : Select all ──────────────────────────────────────────────────
    def select_all_shown(self):
        owner = QApplication.activeWindow()
        owner = owner if owner in self.same_dialogs else self
        self.selected |= set(owner.order())
        self.selection_changed()

    # ── 6.5  clear_selection() : Clear ────────────────────────────────────────────────────────
    def clear_selection(self):
        self.selected.clear()
        self.anchor = None
        self.selection_changed()

    # ── 6.6  selection_changed() : refresh tiles, bar and map ─────────────────────────────────
    def selection_changed(self):
        self.refresh_tiles()
        self.sync_selection_highlights()

        for b in list(self.bars):
            try:
                b.update_state()
            except RuntimeError:
                self.bars.remove(b)

    # ── 6.7  handle_select_keys() : Ctrl+A, Esc, Delete key ───────────────────────────────────
    def handle_select_keys(self, owner, e):
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl and e.key() == Qt.Key.Key_A:
            self.selected |= set(owner.order())
            self.selection_changed()
            return True
        if e.key() == Qt.Key.Key_Escape and self.selected:
            self.clear_selection()
            return True
        if e.key() == Qt.Key.Key_Delete and self.selected:
            self.delete_selected()
            return True
        return False

    # ── 6.8  sync_selection_highlights() : highlight selected points on the map ───────────────
    def sync_selection_highlights(self):
        """Selected pictures -> blue/yellow highlight on the map canvas."""
        for fid in list(self.sel_highlights):
            if fid not in self.selected:
                h = self.sel_highlights.pop(fid)
                h.hide()
                self.canvas.scene().removeItem(h)
        for fid in self.selected:
            if fid in self.sel_highlights:
                continue
            feat = next(self.layer.getFeatures(QgsFeatureRequest().setFilterFid(fid)), None)
            if feat is None or not feat.hasGeometry():
                continue
            h = QgsHighlight(self.canvas, feat, self.layer)
            h.setColor(QColor(21, 101, 192))
            h.setFillColor(QColor(255, 235, 59, 220))
            h.setWidth(6)
            h.show()
            self.sel_highlights[fid] = h
        self.canvas.refresh()

    # ── 6.9  clear_selection_highlights() : remove the map highlights ─────────────────────────
    def clear_selection_highlights(self):
        for h in self.sel_highlights.values():
            h.hide()
            self.canvas.scene().removeItem(h)
        self.sel_highlights = {}

    # ── 6.10  refresh_tiles() : redraw tile frames ────────────────────────────────────────────
    def refresh_tiles(self):
        alive = []
        for t in self.tiles + self.extra_tiles:
            try:
                t.refresh()
                if t in self.extra_tiles:
                    alive.append(t)
            except RuntimeError:
                pass
        self.extra_tiles = alive

    # ── 6.11  forget_tiles() : stop tracking tiles of a closed window ─────────────────────────
    def forget_tiles(self, tiles):
        self.extra_tiles = [t for t in self.extra_tiles if t not in tiles]

    # ── 6.12  resplit() : sort again into Left | Right ────────────────────────────────────────
    def resplit(self, *args):
        """Camera settings changed -> sign positions changed -> redo left / right."""
        self.sides, self.road_axis = self.classify_sides(self.order())
        for d in list(self.same_dialogs):
            d.sides, d.road_axis = self.classify_sides(d.matches)
        self.reflow_all()

    # ── 6.13  reflow_all() : re-flow every open window ────────────────────────────────────────
    def reflow_all(self, *args):
        self.flow(self.tiles)
        for d in list(self.same_dialogs):
            d.flow(d.tiles)
