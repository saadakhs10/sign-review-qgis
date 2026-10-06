# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 4 - GROUPING PHOTOS OF THE SAME SIGN
Each photo gives one estimated sign position (camera + heading + angle + distance).
DBSCAN groups positions closer than "Same-sign dist" (default 15 m) as ONE sign,
separately for each driving direction and side. Two boxes in one photo are always two
signs. A sign seen in 2+ photos is also located where the camera rays cross (least
squares) - used only for grouping, never to move points.
"""

import math

from ..core.io import cached
from ..core.parsing import largest_box
from ..core.geometry import LocalXY, dbscan, ray_intersection
from ..core.imaging import (dhash, bit_distance)


class SameSignMixin:
    """Grouping photos of the same sign - mixed into the review window."""

    # ── 4.1  near_first() : order photos nearest first ────────────────────────────────────────
    def near_first(self, fids, pos=None):
        """Sort points: nearest sign first, unknown distance last."""
        pos = pos or {f: i for i, f in enumerate(fids)}
        def key(f):
            dist = self.distance_of(f)
            return (dist is None, dist if dist is not None else 0, pos.get(f, 0))
        return sorted(fids, key=key)

    # ── 4.2  sign_ray() : camera position + viewing direction of one photo ────────────────────
    def sign_ray(self, fid, L):
        """Camera position and viewing direction towards the sign, in local metres.
        -> ((cx, cy), (dx, dy), single-view position (x, y)) or None."""
        d = self.get_info(fid)
        b = largest_box(d['boxes'])
        w = self.width_of(fid)
        if not b or not w or d['cam'] is None or d['heading'] is None:
            return None
        focal = (w / 2.0) / math.tan(math.radians(self.sp_fov.value() / 2.0))
        ang = math.degrees(math.atan(((b[0] + b[2]) / 2.0 - w / 2.0) / focal))
        brg = math.radians(d['heading'] + ang)
        dx, dy = math.sin(brg), math.cos(brg)
        cx, cy = L.xy(*d['cam'])
        dist = self.sp_sign.value() * focal / max(1, b[2] - b[0])
        dist = min(max(dist, self.sp_min.value()), self.sp_max.value())
        return (cx, cy), (dx, dy), (cx + dist * dx, cy + dist * dy)

    # ── 4.3  order_items() : group, locate and order all photos ───────────────────────────────
    def order_items(self):
        """Group the photos of the same physical sign and locate it - pure geometry:
          1. every photo -> camera position, viewing ray (heading + camera angle) and a
             single-view sign position (distance from box size)
          2. photos are split by driving direction and by side (angle < 0 / > 0), so a
             group never mixes the two columns
          3. DBSCAN on the single-view positions (eps = 'Same-sign dist') inside each split
             -> one group per sign per direction
          4. least-squares intersection of each group's rays -> the sign's position
          5. groups from opposite directions whose positions are within eps are linked ->
             'sign N' = one physical sign (its best photo is selected automatically)
          6. quality flags per photo (edge, tiny, low conf, off-ray, 1 photo)
        Signs are ordered by their nearest photo, photos inside a sign nearest first."""
        self.sign_no, self.sign_members, self.sign_pos = {}, {}, {}
        self.flags, self.rays, self.L = {}, {}, None
        fids = [i[0] for i in self.items]
        if not fids or not self.ensure_downloads(fids, 'Downloading photos…'):
            return
        cams = [self.get_info(f)['cam'] for f in fids if self.get_info(f)['cam']]
        if not cams:
            return
        L = self.L = LocalXY(sum(c[0] for c in cams) / len(cams), sum(c[1] for c in cams) / len(cams))
        ref = self.main_heading(fids)
        rays = self.rays
        for f in fids:
            r = self.sign_ray(f, L)
            if r:
                rays[f] = r
        eps = self.sp_group.value()

        splits = {}
        for f in rays:
            h = self.get_info(f)['heading']
            fwd = ref is None or math.cos(math.radians(h - ref)) >= 0
            ang = self.camera_angle(f)
            splits.setdefault((fwd, ang is not None and ang >= 0), []).append(f)
        groups = []
        for members in splits.values():
            labels = dbscan([rays[f][2] for f in members], eps, min_samples=1)
            by = {}
            for f, lab in zip(members, labels):
                by.setdefault(lab, []).append(f)
            for g in by.values():
                groups += self.split_same_place(self.near_first(g))

        located = [(g, self.locate_sign(g, rays, L)) for g in groups]

        def fwd_of(g):
            h = self.get_info(g[0])['heading']
            return ref is None or math.cos(math.radians(h - ref)) >= 0
        pts = [L.xy(p[0], p[1]) for _, p in located]
        cand = []
        for a in range(len(located)):
            for b in range(a + 1, len(located)):
                if fwd_of(located[a][0]) != fwd_of(located[b][0]):
                    dd = math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
                    if dd <= eps:
                        cand.append((dd, a, b))
        partner = {}
        for dd, a, b in sorted(cand):
            if a not in partner and b not in partner:
                partner[a], partner[b] = b, a
        phys, seen = [], set()
        for a in range(len(located)):
            if a in seen:
                continue
            seen.add(a)
            parts = [located[a]]
            if a in partner:
                seen.add(partner[a])
                parts.append(located[partner[a]])
            phys.append(parts)
        signs = []
        for parts in phys:
            members = self.near_first([f for g, _ in parts for f in g])
            best = max(parts, key=lambda gp: ({'triangulated': 2, 'averaged': 1}.get(gp[1][2], 0), len(gp[0])))
            signs.append((members, best[1], parts))
        signs.sort(key=lambda s: (self.distance_of(s[0][0]) or 1e9))

        order = []
        for n, (members, pos, parts) in enumerate(signs, 1):
            self.sign_members[n] = members
            self.sign_pos[n] = pos
            for f in members:
                self.sign_no[f] = n
            order += members
        order += [f for f in fids if f not in rays]

        for f in fids:
            self.flags[f] = self.quality_flags(f)
        self.rel = {}
        for n, m in self.sign_members.items():
            self.rel.update(self.rel_sharpness(m))
        for f, rs in self.rel.items():
            if rs < 0.5:
                self.flags[f].append('blurry')
        self.best = {}
        order = []
        for n in sorted(self.sign_members):
            m = self.sign_members[n]
            b = self.best_photo(m)
            if b is not None:
                self.best[n] = b
                self.sign_members[n] = [b] + [f for f in m if f != b]
            order += self.sign_members[n]
        order += [f for f in fids if f not in rays]
        by_fid = {i[0]: i for i in self.items}
        self.items = [by_fid[f] for f in order]
        tri = sum(1 for v in self.sign_pos.values() if v[2] == 'triangulated')
        bad = sum(1 for f in fids if self.flags[f])
        self.source_lbl.setText(self.source_lbl.text() +
                                f'   –   <b>{len(signs)} physical signs</b> ({tri} triangulated)'
                                f'   –   {bad} photos flagged')

    # ── 4.4  box_features() : height, shape and look of a box ─────────────────────────────────
    def box_features(self, f):
        """Where / what the box is in its photo: vertical centre (0 = top, 1 = bottom),
        aspect ratio and look fingerprint - used to tell apart two signs on one pole."""
        b = largest_box(self.get_info(f)['boxes'])
        hh = self.height_of(f) or 1
        yc = (b[1] + b[3]) / 2.0 / hh
        asp = max(1e-3, (b[2] - b[0]) / float(max(1, b[3] - b[1])))
        h = self.hash_of(f)
        if h is None:
            d = self.get_info(f)
            h = dhash(cached(d['url']), d['boxes'])
            if h is not None:
                self.hashes[self.hash_key(d)] = format(h, '016x')
        return yc, asp, h

    # ── 4.5  split_same_place() : two signs on one pole -> two groups ─────────────────────────
    def split_same_place(self, group):
        """A DBSCAN group can hold TWO (or more) signs standing at the same place, e.g.
        a speed limit sign with a plaque under it on one pole. Rule: two boxes in the SAME
        photo are always different signs. The photo with most boxes gives the 'seeds';
        every other photo's boxes are matched to the seeds by vertical position in the
        picture, box shape and look (each seed takes at most one box per photo)."""
        by_photo = {}
        for f in group:
            by_photo.setdefault(self.photo_id(f), []).append(f)
        k = max(len(v) for v in by_photo.values())
        if k == 1:
            return [group]
        seed_photo = min((v for v in by_photo.values() if len(v) == k),
                         key=lambda v: min((self.distance_of(f) or 1e9) for f in v))
        seeds = sorted(seed_photo, key=lambda f: self.box_features(f)[0])
        feats = [self.box_features(f) for f in seeds]
        out = [[f] for f in seeds]

        def cost(f, j):
            yc, asp, h = self.box_features(f)
            syc, sasp, sh = feats[j]
            c = 2.0 * abs(yc - syc) + abs(math.log(asp / sasp))
            if h is not None and sh is not None:
                c += bit_distance(h, sh) / 64.0
            return c

        for pid, boxes in by_photo.items():
            if boxes is seed_photo:
                continue
            pairs = sorted((cost(f, j), f, j) for f in boxes for j in range(len(seeds)))
            used_f, used_j = set(), set()
            for c, f, j in pairs:
                if f in used_f or j in used_j:
                    continue
                out[j].append(f)
                used_f.add(f)
                used_j.add(j)
            for f in boxes:
                if f not in used_f:
                    out.append([f])
        return [self.near_first(g) for g in out]

    # ── 4.6  locate_sign() : sign position from all its photos ────────────────────────────────
    def locate_sign(self, g, rays, L):
        """Position of one physical sign from all its photos -> (lon, lat, method, rms).
        Photos whose box is cut off or tiny are left out when at least 2 good ones remain."""
        good = [f for f in g if not self.box_problem(f)]
        if len(good) >= 2:
            g = good
        singles = [rays[f][2] for f in g]
        mx = sum(p[0] for p in singles) / len(singles)
        my = sum(p[1] for p in singles) / len(singles)
        if len(g) >= 2:
            cams = [rays[f][0] for f in g]
            dirs = [rays[f][1] for f in g]
            angs = [math.degrees(math.atan2(d[0], d[1])) for d in dirs]
            spread = max(abs((a - b + 180) % 360 - 180) for a in angs for b in angs)
            if spread >= 3.0:
                res = ray_intersection(cams, dirs)
                if res:
                    px, py, rms, front = res
                    far = max(math.hypot(px - c[0], py - c[1]) for c in cams)
                    if front and rms <= 8.0 and far <= self.sp_max.value() * 2.5:
                        lon, lat = L.lonlat(px, py)
                        return lon, lat, 'triangulated', rms
            lon, lat = L.lonlat(mx, my)
            return lon, lat, 'averaged', None
        lon, lat = L.lonlat(mx, my)
        return lon, lat, 'single photo', None

    # ── 4.7  regroup() : settings changed -> group again ──────────────────────────────────────
    def regroup(self, *args):
        """Settings changed -> group and locate the signs again."""
        base = self.source_lbl.text().split('   –   ')[0]
        self.source_lbl.setText(base)
        self.order_items()
        self.sides, self.road_axis = self.classify_sides(self.order())
        self.goto(min(self.page, self.pages - 1))
        self.selection_changed()
        self.update_best_folder()
