# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure geometry, no Qt widgets: local metric frame, DBSCAN clustering,
least-squares intersection of camera rays and compass names."""

import math

from qgis.core import QgsWkbTypes


def geometry_type(kind):
    """'Line' / 'Point' geometry type for QgsRubberBand on any QGIS 3.x / 4.x."""
    try:
        from qgis.core import Qgis
        return getattr(Qgis.GeometryType, kind)
    except Exception:
        return getattr(QgsWkbTypes, kind + 'Geometry')


class LocalXY:
    """Metres east / north around a reference point (accurate for a few km)."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = 111320.0 * math.cos(math.radians(lat0))

    def xy(self, lon, lat):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * 111320.0

    def lonlat(self, x, y):
        return self.lon0 + x / self.kx, self.lat0 + y / 111320.0


def dbscan(points, eps, min_samples=1):
    """DBSCAN clustering of 2-D points (metres). Returns one label per point, -1 = noise.
    Uses a grid of eps-sized cells so only neighbouring cells are compared."""
    n = len(points)
    cell = {}
    for i, (x, y) in enumerate(points):
        cell.setdefault((int(x // eps), int(y // eps)), []).append(i)

    def neighbours(i):
        x, y = points[i]
        cx, cy = int(x // eps), int(y // eps)
        out = []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for j in cell.get((gx, gy), ()):
                    if (points[j][0] - x) ** 2 + (points[j][1] - y) ** 2 <= eps * eps:
                        out.append(j)
        return out

    labels = [None] * n
    cluster = -1
    for i in range(n):
        if labels[i] is not None:
            continue
        nb = neighbours(i)
        if len(nb) < min_samples:
            labels[i] = -1
            continue
        cluster += 1
        labels[i] = cluster
        queue = [j for j in nb if j != i]
        while queue:
            j = queue.pop()
            if labels[j] == -1:
                labels[j] = cluster
            if labels[j] is not None:
                continue
            labels[j] = cluster
            nbj = neighbours(j)
            if len(nbj) >= min_samples:
                queue.extend(nbj)
    return labels


def ray_intersection(cams, dirs):
    """Least-squares point closest to all rays  c + t*d  (2-D, metres).
    Minimises the sum of squared perpendicular distances:
        sum_i (I - d_i d_i^T) (p - c_i) = 0   ->   A p = b
    Returns (x, y, rms_m, all_in_front) or None if the rays are (almost) parallel."""
    a11 = a12 = a22 = b1 = b2 = 0.0
    for (cx, cy), (dx, dy) in zip(cams, dirs):
        m11, m12, m22 = 1 - dx * dx, -dx * dy, 1 - dy * dy
        a11 += m11; a12 += m12; a22 += m22
        b1 += m11 * cx + m12 * cy
        b2 += m12 * cx + m22 * cy
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-6:
        return None
    px = (a22 * b1 - a12 * b2) / det
    py = (a11 * b2 - a12 * b1) / det
    sq, front = 0.0, True
    for (cx, cy), (dx, dy) in zip(cams, dirs):
        vx, vy = px - cx, py - cy
        along = vx * dx + vy * dy
        front = front and along > 0
        sq += (vx * vx + vy * vy) - along * along
    return px, py, math.sqrt(max(0.0, sq) / len(cams)), front


def compass(deg):
    names = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return names[int(((deg % 360) + 22.5) // 45) % 8]
