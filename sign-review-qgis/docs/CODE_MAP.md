# Code map – one block per feature

Every feature of the plugin lives in its own file in `sign_review/features/`.
Each file starts with the block title and its formula, and inside it every function has a
numbered banner (`# ── 2.1  camera_angle() : …`). The review window (`ui/reviewer.py`) only
builds the buttons and mixes the blocks together.

```text
QGIS toolbar button (plugin.py) -> app.py -> ui/reviewer.py  (the window)
                                               ├─ block 1  photo data          features/f01_photo_data.py
                                               ├─ block 2  angle + distance    features/f02_distance.py
                                               ├─ block 3  Left | Right        features/f03_left_right.py
                                               ├─ block 4  same sign (DBSCAN)  features/f04_same_sign.py
                                               ├─ block 5  best photo          features/f05_best_photo.py
                                               ├─ block 6  selecting           features/f06_selection.py
                                               ├─ block 7  lasso               features/f07_lasso.py
                                               ├─ block 8  Relocate / Reset    features/f08_relocate.py
                                               ├─ block 9  Nearby + Snap       features/f09_nearby_snap.py
                                               ├─ block 10 Delete              features/f10_delete.py
                                               ├─ block 11 Map / Street / photo features/f11_map_street_photo.py
                                               └─ block 12 Closest photos      features/f12_closest_photos.py
```

## Block 1 - Reading The Layer And The Photos

File: `sign_review/features/f01_photo_data.py`

```text
Reads the fields of every point (img_link, boxes, heading, original_x / original_y,
confidence) and remembers them, downloads the photos in the background and knows
each photo's width and height in pixels.
```

| # | Function | What it does |
| --- | --- | --- |
| 1.1 | `build_info` | collect the fields of one feature |
| 1.2 | `conf_of` | lowest detector confidence |
| 1.3 | `all_info` | fields of the whole layer (built on demand) |
| 1.4 | `get_info` | fields of one point (cached) |
| 1.5 | `camera_of` | camera position from original_x / original_y |
| 1.6 | `hash_key` | key of one photo + box |
| 1.7 | `hash_of` | look fingerprint of a sign (dHash) |
| 1.8 | `sharp_of` | sharpness of a sign crop |
| 1.9 | `width_of` | photo width in pixels (W) |
| 1.10 | `height_of` | photo height in pixels |
| 1.11 | `photo_id` | same photo = same camera position + heading |
| 1.12 | `ensure_downloads` | download every photo not in the cache yet |
| 1.13 | `caption` | text under a tile: fid \| distance \| angle |

## Block 2 - Camera Angle And Distance To The Sign

File: `sign_review/features/f02_distance.py`

```text
    focal    = (W / 2) / tan(FOV / 2)                 W = photo width in pixels
    angle    = atan((box centre x - W / 2) / focal)   < 0 = left of camera, > 0 = right
    distance = sign width x focal / box width         a sign looks smaller farther away
The distance is kept between "Min dist" and "Max dist".
```

| # | Function | What it does |
| --- | --- | --- |
| 2.1 | `camera_angle` | angle of the sign seen from the camera |
| 2.2 | `distance_of` | distance from the camera to the sign |
| 2.3 | `box_width` | width of the box in pixels |

## Block 3 - Left | Right Columns

File: `sign_review/features/f03_left_right.py`

```text
Every photo goes to the LEFT columns when its camera angle is negative and to the
RIGHT columns when it is positive (see block 2). Photos taken driving the other way
are marked with ⇅. The grid is drawn with the left half and the right half side by side.
```

| # | Function | What it does |
| --- | --- | --- |
| 3.1 | `main_heading` | main driving direction of the cluster |
| 3.2 | `is_opposite` | photo taken driving the other way? |
| 3.3 | `classify_sides` | L / R for every photo from its own angle |
| 3.4 | `flow` | lay the tiles out: LEFT half | RIGHT half |

## Block 4 - Grouping Photos Of The Same Sign

File: `sign_review/features/f04_same_sign.py`

```text
Each photo gives one estimated sign position (camera + heading + angle + distance).
DBSCAN groups positions closer than "Same-sign dist" (default 15 m) as ONE sign,
separately for each driving direction and side. Two boxes in one photo are always two
signs. A sign seen in 2+ photos is also located where the camera rays cross (least
squares) - used only for grouping, never to move points.
```

| # | Function | What it does |
| --- | --- | --- |
| 4.1 | `near_first` | order photos nearest first |
| 4.2 | `sign_ray` | camera position + viewing direction of one photo |
| 4.3 | `order_items` | group, locate and order all photos |
| 4.4 | `box_features` | height, shape and look of a box |
| 4.5 | `split_same_place` | two signs on one pole -> two groups |
| 4.6 | `locate_sign` | sign position from all its photos |
| 4.7 | `regroup` | settings changed -> group again |

## Block 5 - Best Photo (Gold Frame) And Quality Flags

File: `sign_review/features/f05_best_photo.py`

```text
The highlighted photo of a sign ("★ BEST", gold frame) is the photo NEAREST to the
camera whose box is NOT cut off at the photo border. One per sign.
Quality flags under a tile (information only): edge, tiny, low conf, blurry, 1 photo, off-ray.
```

| # | Function | What it does |
| --- | --- | --- |
| 5.1 | `best_photo` | nearest photo that is not cut off |
| 5.2 | `is_cut_off` | box touches the photo border? |
| 5.3 | `box_problem` | cut off or tiny? |
| 5.4 | `quality_flags` | the red notes under a tile |
| 5.5 | `near_set` | close-up photos of a sign |
| 5.6 | `sharp_at` | sharpness at a fixed width |
| 5.7 | `rel_sharpness` | sharpness compared with the sharpest close-up |

## Block 6 - Selecting Photos (Click, Shift+Click, Select All, Clear)

File: `sign_review/features/f06_selection.py`

```text
Click = select / unselect, Shift+click = a run of photos, tick box = select,
Select all / Clear in the blue bar (Ctrl+A / Esc). Selected points are highlighted
on the map in yellow with a blue outline.
```

| # | Function | What it does |
| --- | --- | --- |
| 6.1 | `click_select` | click / Shift+click on a photo |
| 6.2 | `set_selected` | tick box on a tile |
| 6.3 | `select_many` | add many photos (used by the lasso) |
| 6.4 | `select_all_shown` | Select all |
| 6.5 | `clear_selection` | Clear |
| 6.6 | `selection_changed` | refresh tiles, bar and map |
| 6.7 | `handle_select_keys` | Ctrl+A, Esc, Delete key |
| 6.8 | `sync_selection_highlights` | highlight selected points on the map |
| 6.9 | `clear_selection_highlights` | remove the map highlights |
| 6.10 | `refresh_tiles` | redraw tile frames |
| 6.11 | `forget_tiles` | stop tracking tiles of a closed window |
| 6.12 | `resplit` | sort again into Left | Right |
| 6.13 | `reflow_all` | re-flow every open window |

## Block 7 - Lasso (Drag A Rectangle To Select Many Photos)

File: `sign_review/features/f07_lasso.py`

```text
Press the mouse on a photo and drag: a blue rectangle follows the mouse (and the grid
scrolls at the edges). On release every photo the rectangle touches is selected.
```

| # | Function | What it does |
| --- | --- | --- |
| 7.1 | `reviewer` | the main window |
| 7.2 | `lasso_press` | mouse pressed: remember the start |
| 7.3 | `lasso_move` | mouse moved: draw the rectangle |
| 7.4 | `lasso_release` | mouse released: select what it touches |

## Block 8 - Relocate And Reset To Camera

File: `sign_review/features/f08_relocate.py`

```text
Relocate moves each selected point from the camera to the sign, with ITS OWN photo:
    bearing  = heading + angle                (block 2)
    distance = sign width x focal / box width (block 2)
    new point = camera position + distance in the bearing direction
If the new point is on the road - closer than "Curb offset" (default 5 m) sideways to
the driving line - it is moved out beside the curb.
Reset to camera puts the selected points back on original_x / original_y.
```

| # | Function | What it does |
| --- | --- | --- |
| 8.1 | `estimate` | sign position from one photo (+ curb offset) |
| 8.2 | `relocate` | move the points (one undo step) |
| 8.3 | `relocate_selected` | Relocate button |
| 8.4 | `reset_to_camera` | put points back on the camera |
| 8.5 | `reset_selected` | Reset to camera button |
| 8.6 | `make_geom` | point geometry in the layer type |
| 8.7 | `ensure_editing` | switch the layer to editing |
| 8.8 | `refresh_moved` | redraw after points moved |

## Block 9 - Nearby (Near) And Snap Together

File: `sign_review/features/f09_nearby_snap.py`

```text
📍 Nearby: click a point on the map (or Near under a tile) -> a popup shows that point and
every point whose CURRENT position is within the distance you set (starts at 1 m; type a
value or scroll), nearest first, Left | Right.
🧲 Snap together: moves the ticked points (or all shown) onto ONE spot - the clicked point
or their middle. Points already there are not moved.
```

| # | Function | What it does |
| --- | --- | --- |
| 9.1 | `point_lonlat` | current position of a point (WGS 84) |
| 9.2 | `points_near` | points within a distance, in metres |
| 9.3 | `open_nearby` | open / update the Nearby popup |
| 9.4 | `toggle_near_tool` | 📍 Nearby map tool on / off |
| 9.5 | `near_click` | click on the map -> nearest point |
| 9.6 | `snap_together` | put the points on one spot |
| 9.7 | `NearbyDialog` | the Nearby popup window |

## Block 10 - Delete

File: `sign_review/features/f10_delete.py`

```text
Deletes the selected points from the layer in one undo step. Nothing is permanent
until Save Layer Edits.
```

| # | Function | What it does |
| --- | --- | --- |
| 10.1 | `delete_selected` | Delete button (asks first) |
| 10.2 | `delete_fids` | delete and refresh every window |

## Block 11 - Map, Street And Full Photo

File: `sign_review/features/f11_map_street_photo.py`

```text
Map    = pan the QGIS map to the point and flash it.
Street = open Google Street View at the camera position, facing the camera heading.
Right-click on a tile = the whole photo with its box in red.
```

| # | Function | What it does |
| --- | --- | --- |
| 11.1 | `pan_to` | Map button |
| 11.2 | `open_streetview` | Street button |
| 11.3 | `show_full` | right-click on a tile |
| 11.4 | `FullImageDialog` | the full photo window |

## Block 12 - 📁 Closest Photos Window

File: `sign_review/features/f12_closest_photos.py`

```text
Like opening a folder: one window with the highlighted photo of every sign (block 5),
sorted Left | Right. Nothing is ticked automatically.
```

| # | Function | What it does |
| --- | --- | --- |
| 12.1 | `open_best` | 📁 Closest photos button |
| 12.2 | `update_best_folder` | count on the button, refresh the window |
| 12.3 | `BestDialog` | the Closest photos window |

## Other files

| File | What it does |
| --- | --- |
| `sign_review/plugin.py` | Toolbar button, menu entry, shortcut Ctrl+Shift+R |
| `sign_review/app.py` | Opens / closes the review window for the active layer |
| `sign_review/config.py` | Field names and default settings (FOV, sign width, curb offset, …) |
| `sign_review/ui/reviewer.py` | The review window: buttons, settings row, paging; mixes blocks 1–12 |
| `sign_review/ui/widgets.py` | Re-flowing tile grid, progress dialog, window helpers |
| `sign_review/ui/tile.py` | One photo tile: tick box, caption, Map / Street / Near buttons |
| `sign_review/ui/selection_bar.py` | The blue bar: Select all, Clear, Reset to camera, Relocate, Delete |
| `sign_review/core/io.py` | Download and cache photos |
| `sign_review/core/parsing.py` | Read the boxes and numbers from the attributes |
| `sign_review/core/geometry.py` | Local metres, DBSCAN, least-squares ray intersection |
| `sign_review/core/imaging.py` | Crop and draw the box, look fingerprint, sharpness |
