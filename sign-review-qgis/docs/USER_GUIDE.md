# Sign Review – User Guide

Everything the review window can do, in the order you use it.

```text
OPEN
  Click your point layer in the Layers panel, select a cluster of points on the map
  (nothing selected = whole layer, if it has fewer than 300 points) and click Sign Review
  (Ctrl+Shift+R). Photos download in the background the first time (Cancel stops it).

THE WINDOW
  Row 1   ◀ Prev  Next ▶   📁 Closest photos (N)   📍 Nearby
  Row 2   Camera FOV, Sign width, Min dist, Max dist, Same-sign dist, Curb offset
  Blue bar  Select all  │  Clear  Reset to camera  Relocate  Delete
  Grid    photos cropped to the sign, LEFT | RIGHT of the camera
  Tile    tick box + caption, buttons Map / Street / Near

LEFT | RIGHT COLUMNS
  focal = (W/2) / tan(FOV/2),   angle = atan((box centre x - W/2) / focal)
  angle < 0 -> LEFT columns,    angle > 0 -> RIGHT columns
  Inside each side the photos of one sign stay together, nearest first.

SELECTING
  Drag over the photos      lasso: every photo the rectangle touches is selected
  Click                     select / unselect one photo
  Shift+click               select every photo from the last clicked one to this one
  Tick box                  select / unselect
  Right-click               the whole photo of that tile (box in red)
  Select all / Clear        in the blue bar  (Ctrl+A / Esc do the same)
  Selected points are highlighted on the map (yellow with a blue outline).

RELOCATE  (blue bar, with a selection)
  Each point is moved from the camera to the sign with its own photo:
     bearing  = heading + angle
     distance = sign width x focal / box width
  If the point would land on the road (closer than "Curb offset" sideways to the driving
  line) it is moved out beside the curb.
  Reset to camera puts the selected points back on original_x / original_y.
  Delete deletes the selected points.
  Nothing is permanent until Save Layer Edits; Undo (Ctrl+Z) works until then.

📁 CLOSEST PHOTOS
  One window with the highlighted photo of every sign (gold frame, "★ BEST" - also in
  the main grid): the photo NEAREST to the camera whose box is NOT cut off at the photo
  border. Only one per sign. Sorted LEFT | RIGHT. Nothing is ticked automatically; the
  same blue bar works there.

📍 NEARBY + 🧲 SNAP TOGETHER
  Click "📍 Nearby", then click a point on the map: a popup shows that point (CLICKED)
  and every point within 1 m of it. Type a distance in the "within" box or scroll the
  mouse wheel over it to show points farther away (up to 500 m).
  The Near button under a photo does the same for that point.
  Tick the points that are the same sign (none ticked = all shown), choose
  "onto the clicked point" or "onto their middle" and click "🧲 Snap together".
  Right-click on the map or click "📍 Nearby" again to switch the map tool off.

MAP / STREET
  Map     pans the map to the point and flashes it
  Street  opens Google Street View at the camera position, facing the camera heading
```
