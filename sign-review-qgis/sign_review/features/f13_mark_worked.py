# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 13 - COLOUR THE POINTS YOU HAVE WORKED ON
A point that is no longer at its camera position (original_x / original_y) has been worked
on - Relocate, Snap together or moved by hand. Such points are drawn in their own colour
(MARK_COLOR in config.py, default magenta) on the map, and their tiles say "✓ relocated",
so you can see which areas are done and do not review them twice.

How: the layer keeps its own style; only its fill colour gets a rule (data-defined):
    moved = metres between the point and (original_x, original_y) > MARK_MOVED_M
    colour = MARK_COLOR if moved, else the layer's normal colour
The rule runs for every point on every redraw (zoom, pan), so it must be cheap: for layers in
EPSG:4326 or EPSG:3857 it is plain arithmetic. (Before 1.5.8 it called transform() per point,
which made the map redraw slowly - points vanished on zoom and came back in batches.)
Nothing is added to the attribute table. "Reset to camera" puts a point back -> normal colour.
The rule is saved with the project (.qgz). Switch it off with the 🎨 button.
"""

import math

from qgis.core import QgsProperty, QgsRenderContext, QgsSymbolLayer

from ..config import ORIG_X_FIELD, ORIG_Y_FIELD, MARK_COLOR, MARK_MOVED_M

MARK_MOVED_DEG = MARK_MOVED_M / 111320.0


def _fill_key():
    """FillColor key - QGIS 3.30+ / 4 use the scoped enum, older QGIS the flat name."""
    prop = getattr(QgsSymbolLayer, 'Property', None)
    if prop is not None and hasattr(prop, 'FillColor'):
        return prop.FillColor
    return QgsSymbolLayer.PropertyFillColor


WEB_MERCATOR = ('EPSG:3857', 'EPSG:900913', 'EPSG:102100', 'EPSG:102113', 'EPSG:3785')


def moved_expression(authid=''):
    """Colour rule for a layer whose CRS is `authid`. Distances in metres."""
    ox, oy = f'to_real("{ORIG_X_FIELD}")', f'to_real("{ORIG_Y_FIELD}")'
    if authid == 'EPSG:4326':
        # degrees -> metres: 111 320 m per degree of latitude, x cos(lat) for longitude
        d = (f"sqrt(((x($geometry) - {ox}) * 111320 * cos(radians({oy}))) ^ 2 + "
             f"((y($geometry) - {oy}) * 111320) ^ 2)")
    elif authid in WEB_MERCATOR:
        # camera lon/lat -> Web Mercator x/y (the EPSG:3857 formula), then Mercator metres
        # are scaled by 1 / cos(lat) - multiply back to get real metres on the ground
        mx = f'({ox} * 20037508.342789244 / 180)'
        my = f'(ln(tan(radians(90 + {oy}) / 2)) * 6378137)'
        d = (f"sqrt((x($geometry) - {mx}) ^ 2 + (y($geometry) - {my}) ^ 2) * cos(radians({oy}))")
    else:
        # any other CRS: exact but slower (one transform per point)
        return (f"if(distance(transform($geometry, layer_property(@layer, 'crs'), 'EPSG:4326'), "
                f"make_point({ox}, {oy})) > {MARK_MOVED_DEG:.8f}, '{MARK_COLOR}', NULL)")
    return f"if({d} > {MARK_MOVED_M}, '{MARK_COLOR}', NULL)"


def _is_ours(expr):
    """True if a colour rule was added by Sign Review (any version)."""
    return f'"{ORIG_X_FIELD}"' in expr and f"'{MARK_COLOR}'" in expr


class MarkWorkedMixin:
    """Colour of relocated points - mixed into the review window."""

    # ── 13.1  mark_layer() : switch the colour rule on / off ──────────────────────────────────
    def mark_layer(self, on):
        """Adds (on=True) or removes (on=False) the 'relocated colour' rule on every symbol
        of the layer's style. The layer's own colours stay as they are."""
        try:
            renderer = self.layer.renderer()
            if renderer is None:
                return 0
            key = _fill_key()
            want = moved_expression(self.layer.crs().authid())
            changed = 0
            for sym in renderer.symbols(QgsRenderContext()):
                for i in range(sym.symbolLayerCount()):
                    sl = sym.symbolLayer(i)
                    cur = sl.dataDefinedProperties().property(key)
                    ours = cur.isActive() and _is_ours(cur.expressionString() or '')
                    if on and not (ours and cur.expressionString() == want):
                        if cur.isActive() and not ours:
                            continue            # the style already has its own colour rule - leave it
                        # new rule, or the old slow one saved in a project -> replace
                        sl.setDataDefinedProperty(key, QgsProperty.fromExpression(want))
                        changed += 1
                    elif not on and ours:
                        sl.setDataDefinedProperty(key, QgsProperty())
                        changed += 1
            if changed:
                self.layer.triggerRepaint()
                try:
                    from qgis.utils import iface
                    iface.layerTreeView().refreshLayerSymbology(self.layer.id())
                except Exception:
                    pass
            return changed
        except Exception as e:
            print('Sign Review: could not change the layer colour:', e)
            return 0

    # ── 13.2  is_moved() : point no longer at its camera position? ────────────────────────────
    def is_moved(self, fid):
        """True if the point has been moved away from original_x / original_y."""
        cam = self.get_info(fid).get('cam')
        if not cam or self.idx_ox < 0 or self.idx_oy < 0:
            return False
        try:
            f = self.layer.getFeature(fid)
            if not f.hasGeometry():
                return False
            p = self.to_wgs.transform(f.geometry().centroid().asPoint())
        except Exception:
            return False
        kx = 111320.0 * math.cos(math.radians(cam[1]))
        return math.hypot((p.x() - cam[0]) * kx, (p.y() - cam[1]) * 111320.0) > MARK_MOVED_M

    # ── 13.3  mark_tiles() : "✓ relocated" under the tiles of moved points ────────────────────
    def mark_tiles(self, fids):
        """Adds / removes the "✓ relocated" line on the tiles shown for these points."""
        fids = set(fids or [])
        note = f'<br><span style="color:{MARK_COLOR};font-weight:bold">✓ relocated</span>'
        for t in list(getattr(self, 'tiles', [])) + list(getattr(self, 'extra_tiles', [])):
            if getattr(t, 'fid', None) not in fids:
                continue
            try:
                text = t.cap.text().replace(note, '')
                t.cap.setText(text + note if self.is_moved(t.fid) else text)
            except RuntimeError:
                pass
