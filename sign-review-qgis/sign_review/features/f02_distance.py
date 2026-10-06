# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 2 - CAMERA ANGLE AND DISTANCE TO THE SIGN
    focal    = (W / 2) / tan(FOV / 2)                 W = photo width in pixels
    angle    = atan((box centre x - W / 2) / focal)   < 0 = left of camera, > 0 = right
    distance = sign width x focal / box width         a sign looks smaller farther away
The distance is kept between "Min dist" and "Max dist".
"""

import math

from ..core.parsing import largest_box


class DistanceMixin:
    """Camera angle and distance to the sign - mixed into the review window."""

    # ── 2.1  camera_angle() : angle of the sign seen from the camera ──────────────────────────
    def camera_angle(self, fid):
        """Angle of the sign from the camera's centre line, from the FOV:
             focal = (W / 2) / tan(FOV / 2)
             angle = atan((box centre x - W / 2) / focal)
        negative = sign is LEFT of the camera, positive = RIGHT. None if unknown."""
        d = self.get_info(fid)
        b = largest_box(d['boxes'])
        if not b:
            return None
        w = self.width_of(fid)
        if not w:
            return None
        focal = (w / 2.0) / math.tan(math.radians(self.sp_fov.value() / 2.0))
        cx = (b[0] + b[2]) / 2.0
        return math.degrees(math.atan((cx - w / 2.0) / focal))

    # ── 2.2  distance_of() : distance from the camera to the sign ─────────────────────────────
    def distance_of(self, fid):
        """Estimated camera-to-sign distance in metres (None if image or box missing)."""
        d = self.get_info(fid)
        b = largest_box(d['boxes'])
        if not b or not d['url']:
            return None
        w = self.width_of(fid)
        if not w:
            return None
        focal = (w / 2.0) / math.tan(math.radians(self.sp_fov.value() / 2.0))
        return self.sp_sign.value() * focal / max(1, b[2] - b[0])

    # ── 2.3  box_width() : width of the box in pixels ─────────────────────────────────────────
    def box_width(self, f):
        b = largest_box(self.get_info(f)['boxes'])
        return (b[2] - b[0]) if b else 0
