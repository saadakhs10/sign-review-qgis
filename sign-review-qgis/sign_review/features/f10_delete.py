# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 10 - DELETE
Deletes the selected points from the layer in one undo step. Nothing is permanent
until Save Layer Edits.
"""

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import iface

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
        self.load_items()
        self.selection_changed()
        iface.messageBar().pushSuccess(
            'Sign review', f'{len(deleted)} points deleted - press Save Layer Edits to make it permanent')
