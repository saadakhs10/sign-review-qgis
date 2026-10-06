# Changelog

All notable changes to Sign Review. Newest first.

## 1.5.0

- Published on GitHub (saadakhs10/sign-review-qgis) with automatic releases; Help and Report-an-issue links in the plugin menu; comments cleaned up

## 1.4.0

- Code split into one file per feature (sign_review/features/, blocks 1-12); docs/CODE_MAP.md and LIBRARIES.txt added. No change in behaviour

## 1.3.3

- Fix: after changing the Nearby distance or page, an old photo tile could stay on screen as a duplicate

## 1.3.2

- Gold "★ BEST" highlight = the photo nearest to the camera whose box is not cut off (one per sign; blur and size no longer change the pick)

## 1.3.1

- Right-click a photo tile = full photo again; Nearby distance starts at 1 m but can be typed or scrolled higher (up to 500 m)

## 1.3.0

- Simplified: only Left|Right columns, lasso, Select all / Clear / Relocate / Reset to camera / Delete, Snap together, Nearby / Near, Closest photos, Map, Street. Removed Keep/Reject, Place, look-alike and full-image windows, cross-check / Check window

## 1.2.10

- Fix: "LEFT of camera (angle < 0°)" header was cut short; info text no longer squeezed into a narrow column

## 1.2.9

- Relocate cross-check: every moved point is compared with the board's other photos; disagreeing ones go to the new ⚠ Check window (Street View + Place by hand)

## 1.2.8

- Nearby only shows points within 1 m of the clicked point (never more); farther points are not shown

## 1.2.7

- 🧲 Snap together in the Nearby window: put points near each other on one spot (clicked point or their middle)

## 1.2.6

- 📍 Nearby: click a point on the map (or Near on a tile) to see the points placed near it in a popup window

## 1.2.5

- Compact tiles (crop-sized photo, info strip underneath); Relocate keeps points off the road (Curb offset)

## 1.2.4

- Full-image window shows the whole photo again, with minimize / maximize buttons

## 1.2.3

- Windows have minimize / maximize buttons, open fitted to the screen, button rows wrap in narrow windows

## 1.2.2

- Faster and no freezing: only the sign area is decoded, failed links are not retried, settings recalculate once, whole layer only loads below 300 points

## 1.2.1

- Relocate uses the per-photo formula again; no lines drawn on the map

## 1.2.0

- Closest-photos folder window, best photo per sign (nearest, not cut off, sharp), two signs on one pole kept apart

## 1.1.0

- Lasso / click selection, selection bar, map highlights, Left | Right of camera

## 1.0.0

- First version
