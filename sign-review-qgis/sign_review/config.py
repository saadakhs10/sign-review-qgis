# SPDX-License-Identifier: GPL-2.0-or-later
"""Settings of the Sign Review plugin.

Change field names here if your layer uses other names; the numeric values are the
starting values of the controls in the review window."""

import os
import tempfile

from qgis.core import QgsCoordinateReferenceSystem


# ---- layer fields ----
LINK_FIELD    = 'img_link'    # image URL
BOX_FIELD     = 'boxes'       # "[(x1, y1, x2, y2)]" in image pixels
HEADING_FIELD = 'heading'     # camera heading in degrees (0 = north, clockwise)
ORIG_X_FIELD  = 'original_x'  # camera longitude (WGS84)
ORIG_Y_FIELD  = 'original_y'  # camera latitude  (WGS84)
CONF_FIELD    = 'confidence'  # detector confidence(s), e.g. "0.9959,0.9927" (optional)

# quality checks (flags shown in red on the tiles)
EDGE_PX       = 8             # box closer than this to the image border -> "edge" (sign cut off)
TINY_PX       = 14            # box narrower than this -> "tiny" (too far to trust)
LOW_CONF      = 0.50          # detector confidence below this -> "low conf"
OUTLIER_M     = 3.0           # photo's ray misses its sign's position by more than this -> "off-ray"


PER_PAGE   = 24               # tiles per page
MAX_WHOLE_LAYER = 300         # with nothing selected, only load the whole layer if it is this small
COLS       = 4                # tiles per row (narrow window so the map stays visible)
THUMB      = 220              # tile size in pixels
PAD        = 150              # pixels of context around the box when cropping
THREADS    = 12               # parallel downloads

# starting values for the relocation (can be changed in the window)
CAMERA_HFOV_DEG = 90.0        # horizontal field of view of the camera
SIGN_WIDTH_M    = 0.75        # typical real width of a sign in metres
MIN_DIST_M      = 3.0         # never place a sign closer than this to the camera
MAX_DIST_M      = 40.0        # ... or further than this
CURB_OFFSET_M   = 5.0         # Relocate: a sign closer than this (sideways) to the camera's
                              # driving line is on the road -> pushed out to this distance,
                              # i.e. beside the curb (0 = off)

# same physical sign: DBSCAN neighbour distance in metres (photos whose estimated sign
# positions are closer than this belong to one sign) - can be changed in the window
GROUP_DIST_M    = 15.0

# Nearby window: points within this distance (metres, current positions) of the one you click.
# Starts at NEARBY_RADIUS_M; type a value or scroll in the window to change it (up to NEARBY_MAX_M).
NEARBY_RADIUS_M = 1.0
NEARBY_MAX_M    = 500.0
# 🧲 Snap together: points closer than this to the snap spot already count as together
SNAP_TOL_M = 0.01

# Relocate cross-check: a relocated point farther than this from where the board's OTHER photos
# put it is marked "⚠ check" (the estimate is kept) - can be changed in the window
CHECK_TOL_M = 4.0

# look-alike matching: max number of different bits out of 64 (0 = identical)
LOOK_TOLERANCE  = 8
# ------------------------------------------

CACHE = os.path.join(tempfile.gettempdir(), 'qgis_sign_review')
os.makedirs(CACHE, exist_ok=True)
HASH_FILE = os.path.join(CACHE, 'sign_hashes.json')
SHARP_FILE = os.path.join(CACHE, 'sign_sharpness.json')
WGS84 = QgsCoordinateReferenceSystem('EPSG:4326')
