# SPDX-License-Identifier: GPL-2.0-or-later
"""Reading the layer attributes: bounding boxes and numbers."""

import ast
import math
import re


def parse_boxes(v):
    """'[(1822, 252, 1872, 300)]' -> [(1822, 252, 1872, 300)]"""
    if v is None:
        return []
    s = str(v).strip().strip('"').strip("'")
    try:
        b = ast.literal_eval(s)
    except Exception:
        nums = [int(float(n)) for n in re.findall(r'-?\d+(?:\.\d+)?', s)]
        b = [tuple(nums[i:i + 4]) for i in range(0, len(nums) - 3, 4)]
    if isinstance(b, (list, tuple)) and len(b) == 4 and not isinstance(b[0], (list, tuple)):
        b = [b]
    out = []
    for bb in b or []:
        try:
            if len(bb) == 4:
                out.append(tuple(int(float(x)) for x in bb))
        except Exception:
            pass
    return out


def largest_box(boxes):
    return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if boxes else None


def to_float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except Exception:
        return None
