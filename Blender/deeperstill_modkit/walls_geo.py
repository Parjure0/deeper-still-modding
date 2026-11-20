"""Geometry of the wall and floor tools (pure Python, no Blender module).

Units: Blender units = centimetres (scene unit scale 0.01), Z up.

- Wall: every edge of an outline is extruded straight up into a quad
  (Height). With "Dark base" on, the extrusion is cut in two at the dark
  band height so that the band gets its own row of vertices. Each point
  keeps `AO_Base` (1 at the bottom row when the dark base is on, else 0),
  each face `AO_Wall` = 1, and the wall `AO_Height` (dark band height when
  the band is lower than the wall, else the wall height): the Blender tool
  then gives the wall its thickness, cuts the openings and paints the `AO`
  colour (dark_base_factor).
- Floor: the faces of an outline become a slab (Thickness downwards): the
  original faces on top, a copy moved down with its faces turned over,
  and side faces along the outline's border.
- Box UV projection (tile size in cm).
"""

import math


def extrude_edges(points, edges, height, dark_base=False, dark_height=30.0):
    """Wall faces made from the outline edges.

    points: [(x, y, z)] ; edges: [(i, j)] ; height, dark_height: cm.
    Returns a dict: verts [(x, y, z)], faces [(a, b, c, d)], ao_base [float]
    per vertex, ao_height (cm), split (bool: band row present).
    Face order for the edge (i, j): i, i up, j up, j (normal on the left of
    i -> j seen from above)."""
    split = bool(dark_base) and 0.0 < dark_height < height
    used = sorted({k for e in edges for k in e})
    index = {k: n for n, k in enumerate(used)}
    rows = [0.0, dark_height, height] if split else [0.0, height]
    verts, ao_base = [], []
    for r, dz in enumerate(rows):
        for k in used:
            x, y, z = points[k]
            verts.append((x, y, z + dz))
            ao_base.append(1.0 if (r == 0 and dark_base) else 0.0)
    n = len(used)
    faces = []
    for r in range(len(rows) - 1):
        lo, hi = r * n, (r + 1) * n
        for i, j in edges:
            a, b = index[i], index[j]
            faces.append((lo + a, hi + a, hi + b, lo + b))
    return {"verts": verts, "faces": faces, "ao_base": ao_base,
            "ao_height": dark_height if split else height, "split": split}


def extrude_floor(points, faces, thickness):
    """Slab made from the outline faces.

    points: [(x, y, z)] ; faces: [[i, j, k...]] ; thickness: cm (downwards).
    Returns a dict: verts, faces, source (index of the outline face each
    new face comes from, for its material). The top faces keep the outline
    vertices; the bottom and the sides use their own vertices (not merged
    with the top)."""
    verts = [tuple(p) for p in points]
    out_faces = [tuple(f) for f in faces]
    source = list(range(len(faces)))
    used = sorted({k for f in faces for k in f})
    low = {}
    for k in used:
        x, y, z = points[k]
        low[k] = len(verts)
        verts.append((x, y, z - thickness))
    # Top row of the sides: own copy of the border vertices.
    border = {}
    count = {}
    owner = {}
    for fi, f in enumerate(faces):
        for a, b in zip(f, list(f[1:]) + [f[0]]):
            key = (min(a, b), max(a, b))
            count[key] = count.get(key, 0) + 1
            owner[(a, b)] = fi
    top = {}
    for fi, f in enumerate(faces):
        # Bottom: the face moved down, turned over.
        out_faces.append(tuple(low[k] for k in reversed(f)))
        source.append(fi)
    for (a, b), fi in sorted(owner.items(), key=lambda kv: kv[1]):
        if count[(min(a, b), max(a, b))] != 1:
            continue
        for k in (a, b):
            if k not in top:
                x, y, z = points[k]
                top[k] = len(verts)
                verts.append((x, y, z))
        border[(a, b)] = fi
        # Side under the border edge a -> b of an upward face: outwards.
        out_faces.append((top[b], top[a], low[a], low[b]))
        source.append(fi)
    return {"verts": verts, "faces": out_faces, "source": source}


def dark_base_factor(distance, ao_height, hit):
    """Darkness (0 = white, 1 = black) of a wall point `distance` cm above
    the bottom of the wall, for a dark band `ao_height` cm high."""
    if not hit or distance >= 100000.0:
        return 0.0
    t = (distance - 0.5) / max(ao_height, 1.0)
    return 1.0 - min(max(t, 0.0), 1.0)


def box_uv(co, normal, tile):
    """UV of a point `co` (cm) of a face of normal `normal`: projection along
    the main axis of the normal, one unit every `tile` cm."""
    axis = max(range(3), key=lambda i: abs(normal[i]))
    a, b = [i for i in range(3) if i != axis]
    if axis == 0 and normal[0] < 0 or axis == 1 and normal[1] > 0:
        return (-co[a] / tile, co[b] / tile)
    return (co[a] / tile, co[b] / tile)


def face_angle(n1, n2):
    """Angle (radians) between two unit normals."""
    d = max(-1.0, min(1.0, n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]))
    return math.acos(d)


def box_mesh(width, depth, height):
    """Box (opening): x in [-w/2, w/2], y in [-d/2, d/2], z in [0, h].
    Returns (verts, faces) with outward normals."""
    w, d = width / 2.0, depth / 2.0
    verts = [(x, y, z) for x in (-w, w) for y in (-d, d) for z in (0.0, height)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return verts, faces
