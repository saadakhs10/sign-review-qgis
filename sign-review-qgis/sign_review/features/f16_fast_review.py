# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 16 - FAST REVIEW: FEWER CLICKS, NO MAP HUNTING, NOTHING DONE TWICE

⚡ FINALIZE               one step per sign: keep its ★ BEST photo, move it to the sign
                          (Relocate) and delete the sign's other photos. With photos selected:
                          their signs; with nothing selected: every sign on the page (asks first).
⏭ NEXT AREA              marks what is left in this review as checked, then selects the
                          nearest UNREVIEWED points (CLUSTER_M around the start, at most
                          CLUSTER_MAX), opens them and pans the map there. The area after it
                          starts downloading in the background.
PROGRESS                  a field STATUS_FIELD ('sr_status') is added to the layer once:
                            kept       ★ BEST photo kept by Finalize
                            relocated  moved by Relocate / Snap / by hand
                            checked    looked at (⏭ Next area), nothing changed
                          empty = not reviewed yet. The window shows "n / N reviewed".
★ MAKE BEST               blue bar: the selected photo becomes the ★ BEST of its sign
                          (the photo Finalize keeps).
REMEMBERED                FOV, sign width, distances, curb offset, window size and place.
💾 AUTO-SAVE              Save Layer Edits every AUTOSAVE_MIN minutes (switch on in the top row);
                          a clock next to it counts down to the next save.
CACHE                     full photos above CACHE_MAX_GB are removed (oldest first); the
                          cropped thumbnails stay on disk, so revisits are instant.
"""

import math
import time
from concurrent.futures import ThreadPoolExecutor

from qgis.PyQt.QtCore import QTimer, QSettings
from qgis.PyQt.QtWidgets import QCheckBox, QLabel, QMessageBox, QPushButton
from qgis.core import QgsFeatureRequest, QgsField, QgsPointXY, QgsRectangle
from qgis.utils import iface

from ..config import (STATUS_FIELD, CLUSTER_M, CLUSTER_MAX, AUTOSAVE_MIN, TIMING_LOG)
from ..core.imaging import trim_cache

SETTINGS = 'sign_review/'
SPINS = ('sp_fov', 'sp_sign', 'sp_min', 'sp_max', 'sp_group', 'sp_curb')
_trim = ThreadPoolExecutor(1)
_trimmed = []


def _string_field(name):
    """QgsField of type text on QGIS 3.x (QVariant) and 3.38+ / 4.x (QMetaType)."""
    try:
        from qgis.PyQt.QtCore import QMetaType
        return QgsField(name, QMetaType.Type.QString, 'string', 20)
    except (TypeError, AttributeError, ImportError):
        from qgis.PyQt.QtCore import QVariant
        return QgsField(name, QVariant.String, 'string', 20)


class FastReviewMixin:
    """Fast review - mixed into the review window as the FIRST block (its additions to
    refresh_moved / delete_fids / split_picked run before the others)."""

    # ── 16.1  fast_init() : called once at the end of the window's __init__ ─────────────────
    def fast_init(self):
        self.status_idx = self.layer.fields().indexOf(STATUS_FIELD)
        self._area_center = None
        self._progress = None
        self._status_asked = False
        load = self.load_items                         # a new review (e.g. ⏭ Next area)
        def load_items(_load=load):                    # starts with nothing finalized
            self.finalized = set()
            _load()
        self.load_items = load_items
        try:                                           # the map-selection timer must use it too
            self.reload_timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.reload_timer.timeout.connect(self.load_items)
        self.finalized = set()
        self._restore_settings()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(int(AUTOSAVE_MIN * 60 * 1000))
        self.autosave_timer.timeout.connect(self.autosave)
        self.clock_timer = QTimer(self)                # the countdown next to 💾 Auto-save
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self._show_clock)
        self._add_widgets()
        self.finished.connect(self._save_settings)
        if QSettings().value(SETTINGS + 'autosave', False, type=bool):
            self.chk_autosave.setChecked(True)
        if TIMING_LOG:
            for name in ('load_items', 'goto', 'delete_fids', 'finalize_signs', 'next_area', 'relocate'):
                setattr(self, name, _timed(name, getattr(self, name)))
        if not _trimmed:                                 # once per QGIS session, in the background
            _trimmed.append(_trim.submit(trim_cache))
        self.count_progress()

    def _add_widgets(self):
        top = None
        lay = self.layout()
        for i in range(lay.count() if lay else 0):
            sub = lay.itemAt(i).layout()
            if sub is not None and sub.indexOf(self.btn_my_best) >= 0:
                top = sub
        self.btn_finalize = QPushButton('⚡ Finalize page')
        self.btn_finalize.setStyleSheet('background:#2e7d32;color:white;font-weight:bold;padding:4px 12px;')
        self.btn_finalize.setToolTip('Every sign on this page (or the signs of the selected photos): keep '
                                     'its ★ BEST photo, move it to the sign, delete its other photos.')
        self.btn_finalize.setAutoDefault(False)
        self.btn_finalize.clicked.connect(lambda: self.finalize_signs(None, ask=True))
        self.btn_next_area = QPushButton('⏭ Next area')
        self.btn_next_area.setStyleSheet('font-weight:bold; padding:4px 12px;')
        self.btn_next_area.setToolTip('Mark this review as checked and open the nearest points not '
                                      'reviewed yet - no lasso on the map.')
        self.btn_next_area.setAutoDefault(False)
        self.btn_next_area.clicked.connect(self.next_area)
        self.chk_autosave = QCheckBox(f'💾 Auto-save ({AUTOSAVE_MIN:g} min)')
        self.chk_autosave.setToolTip('Save Layer Edits automatically. Note: Undo cannot go back past a save.')
        self.chk_autosave.toggled.connect(self._autosave_toggled)
        self.clock_lbl = QLabel('')
        self.clock_lbl.setStyleSheet('color:#1565c0; font-weight:bold;')
        self.clock_lbl.setToolTip('Time until the next automatic Save Layer Edits')
        self.progress_lbl = QLabel()
        self.progress_lbl.setStyleSheet('color:#2e7d32; font-weight:bold;')
        for w in (self.btn_finalize, self.btn_next_area, self.chk_autosave, self.clock_lbl, self.progress_lbl):
            if top is not None:
                top.addWidget(w)
        self.add_fast_buttons(self.sel_bar)

    def add_fast_buttons(self, bar):
        """★ Make best and ⚡ Finalize sign in a blue bar (main window, 📁 Closest photos …)."""
        best = QPushButton('★ Make best')
        best.setProperty('active_style', 'background:#f9a825;color:black;font-weight:bold;padding:4px 10px;')
        best.setToolTip('The selected photo becomes the ★ BEST of its sign - the photo Finalize keeps')
        best.clicked.connect(self.make_best_selected)
        fin_sel = QPushButton('⚡ Finalize sign')
        fin_sel.setProperty('active_style', 'background:#2e7d32;color:white;font-weight:bold;padding:4px 10px;')
        fin_sel.setToolTip('The signs of the selected photos: keep ★ BEST, move it to the sign, '
                           'delete the other photos.')
        fin_sel.clicked.connect(lambda: self.finalize_signs(None, ask=True))
        for btn in (best, fin_sel):
            bar.layout().addWidget(btn)
            bar.btns.append(btn)
        bar.update_state()

    # ── 16.2  settings that are remembered ────────────────────────────────────────────────────
    def _restore_settings(self):
        s = QSettings()
        for name in SPINS:
            v = s.value(SETTINGS + name, None)
            sp = getattr(self, name, None)
            if v is not None and sp is not None:
                try:
                    sp.blockSignals(True)
                    sp.setValue(float(v))
                finally:
                    sp.blockSignals(False)
        geo = s.value(SETTINGS + 'geometry', None)
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    def _save_settings(self, *args):
        s = QSettings()
        for name in SPINS:
            sp = getattr(self, name, None)
            if sp is not None:
                s.setValue(SETTINGS + name, sp.value())
        s.setValue(SETTINGS + 'geometry', self.saveGeometry())
        s.setValue(SETTINGS + 'autosave', self.chk_autosave.isChecked())
        self.autosave_timer.stop()
        self.clock_timer.stop()

    # ── 16.3  status field: progress of the whole layer ──────────────────────────────────────
    def ensure_status_field(self, ask=True):
        """Adds STATUS_FIELD to the layer once (asks first). Returns True if it is there."""
        if self.status_idx >= 0:
            return True
        if ask and QMessageBox.question(
                self, 'Track progress',
                f'Add a field "{STATUS_FIELD}" to "{self.layer.name()}" to remember which points are '
                'reviewed (kept / relocated / checked)?\nIt is used by ⏭ Next area and the progress '
                'count, and saved with Save Layer Edits.') != QMessageBox.StandardButton.Yes:
            return False
        self.ensure_editing()
        if not self.layer.addAttribute(_string_field(STATUS_FIELD)):
            iface.messageBar().pushWarning('Sign Review', f'Could not add the field "{STATUS_FIELD}"')
            return False
        self.layer.updateFields()
        self.status_idx = self.layer.fields().indexOf(STATUS_FIELD)
        self.count_progress()
        return self.status_idx >= 0

    def status_of(self, fid):
        if self.status_idx < 0:
            return None
        v = self.layer.getFeature(fid)[self.status_idx]
        return None if v in (None, '') or str(v) == 'NULL' else str(v)

    def set_status(self, fids, value, only_empty=False):
        """Writes the status (inside the edit command that is open, if any)."""
        if not fids or not self.ensure_status_field(ask=False):
            return
        self.ensure_editing()
        delta = 0
        for f in fids:
            old = self.status_of(f)
            if only_empty and old:
                continue
            if old != value:
                self.layer.changeAttributeValue(f, self.status_idx, value)
                delta += (1 if value else 0) - (1 if old else 0)
        self._add_progress(delta, 0)

    def _add_progress(self, d_done, d_total):
        if self._progress is None:
            self.count_progress()
            return
        done, total = self._progress
        self._progress = (max(0, done + d_done), max(0, total + d_total))
        self._show_progress()

    def _show_progress(self):
        if self._progress is None or self.status_idx < 0:
            self.progress_lbl.setText('')
            return
        done, total = self._progress
        pct = 100.0 * done / total if total else 0
        self.progress_lbl.setText(f'✔ {done} / {total} reviewed ({pct:.1f}%)')

    def count_progress(self):
        if self.status_idx < 0:
            self._progress = None
            self.progress_lbl.setText('')
            return
        req = QgsFeatureRequest()
        for flag in ('Qgis.FeatureRequestFlag.NoGeometry', 'QgsFeatureRequest.Flag.NoGeometry',
                     'QgsFeatureRequest.NoGeometry'):
            try:
                import qgis.core as qc
                obj = qc
                for part in flag.split('.'):
                    obj = getattr(obj, part)
                req.setFlags(obj)
                break
            except (AttributeError, TypeError):
                continue
        req.setSubsetOfAttributes([self.status_idx])
        total = done = 0
        for f in self.layer.getFeatures(req):
            total += 1
            v = f[self.status_idx]
            if v not in (None, '') and str(v) != 'NULL':
                done += 1
        self._progress = (done, total)
        self._show_progress()

    # Delete (D key, button, Finalize uses its own) - the layer has fewer points now
    def delete_fids(self, fids):
        had = sum(1 for f in fids if self.status_of(f)) if self.status_idx >= 0 else 0
        super().delete_fids(fids)
        self._add_progress(-had, -len(set(fids)))

    # Relocate / Snap / Reset to camera all end in refresh_moved -> keep the status in step
    def refresh_moved(self, fids):
        super().refresh_moved(fids)
        if self.status_idx >= 0 and fids:
            moved = [f for f in fids if self.is_moved(f)]
            back = [f for f in fids if f not in set(moved) and self.status_of(f) == 'relocated']
            keep_kept = [f for f in moved if self.status_of(f) != 'kept']
            self.layer.beginEditCommand('Review status')
            self.set_status(keep_kept, 'relocated')
            self.set_status(back, None)
            self.layer.endEditCommand()

    # ── 16.4  finalize_signs() : keep ★ BEST at the sign, delete the other photos ─────────────
    def signs_for(self, fids):
        return sorted({self.sign_no[f] for f in fids if f in self.sign_no})

    def finalize_signs(self, signs=None, ask=True):
        """signs=None: the signs of the selected photos, or every sign on the page."""
        what = 'selected'
        if signs is None:
            if self.selected:
                signs = self.signs_for(self.selected)
            else:
                signs = self.signs_for([i[0] for i in self.page_items(self.page)])
                what = 'on this page'
        plan = []                                       # (sign, best fid, [fids to delete])
        for n in signs:
            b = self.best.get(n)
            members = self.sign_members.get(n, [])
            if b is None or b not in members or b in self.finalized:
                continue
            plan.append((n, b, [f for f in members if f != b and f not in self.picked]))
        if not plan:
            iface.messageBar().pushInfo('Sign Review', 'No sign with a ★ BEST photo to finalize '
                                        '(all its photos are cut off?)')
            return 0
        n_del = sum(len(p[2]) for p in plan)
        if ask and QMessageBox.question(
                self, 'Finalize',
                f'Finalize {len(plan)} signs {what}:\n'
                f'  • keep the ★ BEST photo of each and move it to the sign ({len(plan)} points)\n'
                f'  • delete their other {n_del} photos\n\n'
                'Undo (Ctrl+Z) works until you Save Layer Edits.') != QMessageBox.StandardButton.Yes:
            return 0
        best = [p[1] for p in plan]
        if not self.ensure_sizes(best, 'Reading photo sizes…'):
            return 0
        if not self._status_asked:
            self._status_asked = True
            self.ensure_status_field(ask=True)
        deleted = {f for p in plan for f in p[2]}
        had = {f for f in deleted if self.status_of(f)} if self.status_idx >= 0 else set()
        newly_kept = [b for b in best if not self.status_of(b)] if self.status_idx >= 0 else []
        self.ensure_editing()
        self._busy = True
        try:
            self.layer.beginEditCommand('Finalize signs')
            kept = []
            for b in best:
                est = self.estimate(b, self.width_of(b))
                if est is not None:
                    self.layer.changeGeometry(b, self.make_geom(self.to_layer.transform(QgsPointXY(*est))))
                kept.append(b)
            if self.status_idx >= 0:
                for b in kept:
                    self.layer.changeAttributeValue(b, self.status_idx, 'kept')
            if deleted:
                self.layer.deleteFeatures(list(deleted))
            self.layer.endEditCommand()
        finally:
            self._busy = False
        self.selected -= deleted | set(kept)
        for f in deleted:
            h = self.sel_highlights.pop(f, None)
            if h is not None:
                h.hide()
                self.canvas.scene().removeItem(h)
        self.finalized.update(kept)
        self.items = [i for i in self.items if i[0] not in self.finalized]   # done: off the grid
        bar = self.scroll.verticalScrollBar()
        pos = bar.value()
        self.drop_deleted(deleted)                      # removes the deleted, redraws the page once
        if what == 'selected':                          # stay where you were on the page
            bar.setValue(pos)
            QTimer.singleShot(0, lambda: bar.setValue(pos))
        self._add_progress(len(newly_kept) - len(had), -len(deleted))
        self.refresh_moved(kept)
        self.selection_changed()
        iface.messageBar().pushSuccess('Sign Review', f'{len(kept)} signs finalized, {len(deleted)} photos '
                                       'deleted - Save Layer Edits when you are done')
        return len(kept)

    # ── 16.5  next_area() : the nearest points not reviewed yet ──────────────────────────────
    def next_area(self):
        self._status_asked = True
        if not self.ensure_status_field(ask=True):
            return
        current = self.all_fids()
        if current:
            self._area_center = self._center_of(current)
            self.layer.beginEditCommand('Mark area checked')
            self.set_status(current, 'checked', only_empty=True)
            self.layer.endEditCommand()
        center = self._area_center or self._map_center()
        fids, bbox = self.find_area(center, exclude=set(current))
        if not fids:
            iface.messageBar().pushSuccess('Sign Review', 'No unreviewed points left - the layer is done')
            return
        self.layer.selectByIds(fids)                    # -> the review reloads with these points
        try:
            from qgis.core import QgsCoordinateTransform, QgsProject
            ct = QgsCoordinateTransform(self.layer.crs(), self.canvas.mapSettings().destinationCrs(),
                                        QgsProject.instance())
            box = ct.transformBoundingBox(bbox)
            self.canvas.setExtent(box.buffered(max(box.width(), box.height()) * 0.3 or 50))
            self.canvas.refresh()
        except Exception:
            pass
        QTimer.singleShot(1500, lambda: self._prefetch_after(set(fids)))

    def _center_of(self, fids):
        xs, ys = [], []
        for f in fids:
            try:
                g = self.layer.getFeature(f)
                if not g.hasGeometry():
                    continue
                p = g.geometry().centroid().asPoint()
            except Exception:                           # deleted meanwhile
                continue
            xs.append(p.x())
            ys.append(p.y())
        return QgsPointXY(sum(xs) / len(xs), sum(ys) / len(ys)) if xs else None

    def _map_center(self):
        try:
            from qgis.core import QgsCoordinateTransform, QgsProject
            c = self.canvas.extent().center()
            ct = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(), self.layer.crs(),
                                        QgsProject.instance())
            return ct.transform(c)
        except Exception:
            return None

    def _rect_around(self, center, metres):
        """Layer-CRS rectangle of +-metres around center (works for degrees and metres CRS)."""
        c = self.to_wgs.transform(center)
        dlat = metres / 111320.0
        dlon = metres / (111320.0 * max(0.01, math.cos(math.radians(c.y()))))
        r = QgsRectangle(c.x() - dlon, c.y() - dlat, c.x() + dlon, c.y() + dlat)
        return self.to_layer.transformBoundingBox(r)

    def _unreviewed_in(self, rect, exclude):
        req = QgsFeatureRequest().setFilterRect(rect)
        req.setFilterExpression(f'"{STATUS_FIELD}" IS NULL')
        out = []
        for f in self.layer.getFeatures(req):
            if f.id() in exclude or not f.hasGeometry():
                continue
            out.append((f.id(), f.geometry().centroid().asPoint()))
        return out

    def find_area(self, center, exclude=()):
        """Nearest unreviewed point to `center` (search grows 300 m -> 80 km), then the unreviewed
        points within CLUSTER_M of it (at most CLUSTER_MAX, nearest first)."""
        exclude = set(exclude)
        if center is None:
            ext = self.layer.extent()
            center = ext.center()
        seed = None
        r = 300.0
        while r <= 80000.0 and seed is None:
            found = self._unreviewed_in(self._rect_around(center, r), exclude)
            if found:
                seed = min(found, key=lambda t: (t[1].x() - center.x()) ** 2 + (t[1].y() - center.y()) ** 2)
            r *= 2
        if seed is None:
            found = self._unreviewed_in(self.layer.extent(), exclude)
            if not found:
                return [], None
            seed = min(found, key=lambda t: (t[1].x() - center.x()) ** 2 + (t[1].y() - center.y()) ** 2)
        sp = seed[1]
        near = self._unreviewed_in(self._rect_around(sp, CLUSTER_M), exclude)
        near.sort(key=lambda t: (t[1].x() - sp.x()) ** 2 + (t[1].y() - sp.y()) ** 2)
        near = near[:CLUSTER_MAX] or [seed]
        bbox = QgsRectangle(min(p.x() for _, p in near), min(p.y() for _, p in near),
                            max(p.x() for _, p in near), max(p.y() for _, p in near))
        return [f for f, _ in near], bbox

    def _prefetch_after(self, current):
        """Starts downloading the area after this one, behind everything on screen."""
        try:
            center = self._center_of(list(current)[:50])
            fids, _ = self.find_area(center, exclude=current)
            for f in fids[:CLUSTER_MAX]:
                url = self.layer.getFeature(f)[self.idx_link]
                if url not in (None, '') and str(url) != 'NULL':
                    self.loader.submit(('download', str(url)), 50, str(url), None, False)
        except Exception as e:
            print('Sign Review: prefetch of the next area failed:', e)

    # Finalized signs are done: their kept photo leaves the grid, so the page shows only what is left
    def split_picked(self):
        super().split_picked()
        done = getattr(self, 'finalized', None)
        if done:
            from ..config import PER_PAGE
            self.items = [i for i in self.items if i[0] not in done]
            self.pages = max(1, (len(self.items) + PER_PAGE - 1) // PER_PAGE)

    # ── 16.6  make_best() : the selected photo becomes the ★ BEST of its sign ────────────────
    def make_best_selected(self):
        """★ Make best (blue bar): one selected photo per sign becomes its ★ BEST."""
        done, skipped = set(), 0
        for fid in sorted(self.selected):
            n = self.sign_no.get(fid)
            if not n or n in done:
                skipped += 1
                continue
            self.best[n] = fid
            self.sign_members[n] = [fid] + [f for f in self.sign_members[n] if f != fid]
            done.add(n)
        if not done:
            iface.messageBar().pushInfo('Sign Review', 'The selected photo is not part of a sign')
            return
        bar = self.scroll.verticalScrollBar()
        pos = bar.value()                               # stay where you are on the page
        self.selected.clear()
        self.goto(self.page)
        bar.setValue(pos)
        QTimer.singleShot(0, lambda: bar.setValue(pos))
        self.selection_changed()
        self.update_best_folder()
        msg = f'★ BEST changed for {len(done)} sign{"s" if len(done) > 1 else ""}'
        if skipped:
            msg += f' ({skipped} other selected photos ignored: one per sign)'
        iface.messageBar().pushInfo('Sign Review', msg)

    # ── 16.8  autosave ────────────────────────────────────────────────────────────────────────
    def _autosave_toggled(self, on):
        if on:
            self.autosave_timer.start()
            self.clock_timer.start()
        else:
            self.autosave_timer.stop()
            self.clock_timer.stop()
        self._show_clock()

    def _show_clock(self):
        if not self.autosave_timer.isActive():
            self.clock_lbl.setText('')
            return
        left = max(0, self.autosave_timer.remainingTime() // 1000)
        self.clock_lbl.setText(f'⏱ next save {left // 60}:{left % 60:02d}')

    def autosave(self):
        if not self.layer.isEditable() or not self.layer.isModified():
            return
        self._busy = True
        try:
            ok = self.layer.commitChanges(False)        # False = stay in edit mode
        except TypeError:
            ok = self.layer.commitChanges()
            self.layer.startEditing()
        finally:
            self._busy = False
        if ok:
            iface.messageBar().pushInfo('Sign Review', f'Auto-saved {time.strftime("%H:%M")}')
        else:
            self.chk_autosave.setChecked(False)
            iface.messageBar().pushWarning('Sign Review', 'Auto-save failed and was switched off: '
                                           + '; '.join(self.layer.commitErrors()[:3]))


def _timed(name, fn):
    def run(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            print(f'Sign Review timing: {name} {1000 * (time.perf_counter() - t):.0f} ms')
    return run
