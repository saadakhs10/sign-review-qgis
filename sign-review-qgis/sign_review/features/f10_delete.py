# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 10 - DELETE
Deletes the selected points from the layer in one undo step. Nothing is permanent
until Save Layer Edits.
"""

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import iface

from ..config import PER_PAGE
from .f09_nearby_snap import NearbyDialog


class DeleteMixin:
    """Delete - mixed into the review window."""

    # ── 10.1  delete_selected() : Delete button (asks first) ──────────────────────────────────
    def delete_selected(self):
        if not self.selected:
            return
        fids = sorted(self.selected)
        ans = QMessageBox.question(
            self, 'Delete',
            f'Delete the {len(fids)} selected points from "{self.layer.name()}"?\n'
            'You still need to Save Layer Edits; Undo works until then.')
        if ans == QMessageBox.StandardButton.Yes:
            self.delete_fids(fids)

    # ── 10.2  delete_fids() : delete and refresh every window ─────────────────────────────────
    def delete_fids(self, fids):
        """Delete these points (one undo step) and refresh every window."""
        self._busy = True
        self.ensure_editing()
        deleted = set(fids)
        self.layer.beginEditCommand('Delete signs')
        self.layer.deleteFeatures(list(deleted))
        self.layer.endEditCommand()
        self._busy = False
        self._all = None
        self.selected -= deleted
        for fid in deleted:
            h = self.sel_highlights.pop(fid, None)
            if h is not None:
                h.hide()
                self.canvas.scene().removeItem(h)
        if self.anchor in deleted:
            self.anchor = None
        self.layer.triggerRepaint()
        for d in list(self.same_dialogs):
            if isinstance(d, NearbyDialog):
                d.reload()
        self.drop_deleted(deleted)
        self.selection_changed()
        iface.messageBar().pushSuccess(
            'Sign review', f'{len(deleted)} points deleted - press Save Layer Edits to make it permanent')

    # ── 10.3  drop_deleted() : take deleted points out of the review - no full reload ─────────
    def drop_deleted(self, deleted):
        """Removes the deleted points from the lists, signs and windows that are already there,
        instead of reading the layer and grouping every photo again (which made Delete slow).
        A sign that lost its ★ BEST photo gets the next nearest uncut photo."""
        keep = lambda items: [i for i in items if i[0] not in deleted]     # noqa: E731
        self.items = keep(self.items)
        if getattr(self, '_items_all', None) is not None:
            self._items_all = keep(self._items_all)
        for f in deleted:
            self.info.pop(f, None)
            self.sign_no.pop(f, None)
            self.flags.pop(f, None)
            getattr(self, 'problems', {}).pop(f, None)
        for n in list(self.sign_members):
            members = [f for f in self.sign_members[n] if f not in deleted]
            if not members:
                del self.sign_members[n]
                self.best.pop(n, None)
                self.sign_pos.pop(n, None)
            elif len(members) != len(self.sign_members[n]):
                self.sign_members[n] = members
                if self.best.get(n) in deleted or n not in self.best:
                    b = self.best_photo(members)
                    if b is None:
                        self.best.pop(n, None)
                    else:
                        self.best[n] = b
        self.pages = max(1, (len(self.items) + PER_PAGE - 1) // PER_PAGE)
        self.sides, self.road_axis = self.classify_sides(self.order())
        self.goto(min(self.page, self.pages - 1))
        self.update_best_folder()
        if hasattr(self, 'update_my_best'):
            self.update_my_best()

