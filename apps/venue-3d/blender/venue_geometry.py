#!/usr/bin/env python3
"""Skeleton validation and plain-Python geometry for venue-3d.

Standard library only: this module is imported by build_venue.py inside Blender,
and it runs on its own (python3 venue_geometry.py skeleton.json) to check a skeleton
without Blender.

Coordinates are plan coordinates in metres: x = east, y = north, z = up.
Angles are compass bearings in degrees, clockwise from north.
Every mesh is closed and consistently wound (outward normals), so Blender booleans work.
"""
import json
import math
import re
import sys

ROOF_TYPES = ("dome", "flat", "cone", "saddle")
NODE_ID = re.compile(r"^[a-z0-9_]{1,40}$")
EPS = 1e-6


# ----------------------------------------------------------------- validation

def _num(obj, key, where, errors, positive=True, required=True, default=None):
    """Read a number; record an error if it is missing or not positive."""
    if key not in obj:
        if required:
            errors.append(f"{where}.{key}: required")
        return default
    v = obj[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        errors.append(f"{where}.{key}: must be a number")
        return default
    if positive and v <= 0:
        errors.append(f"{where}.{key}: must be > 0")
    return v


def _id(obj, where, errors, seen):
    v = obj.get("id")
    if not isinstance(v, str) or not NODE_ID.match(v):
        errors.append(f"{where}.id: must match [a-z0-9_]{{1,40}} (it becomes a node name)")
        return None
    if v in seen:
        errors.append(f"{where}.id: duplicate '{v}'")
    seen.add(v)
    return v


def _validate_saddle(roof, top_r, errors, warnings):
    """Saddle: rim heights on the x and y axes and the centre height, all above the wall top."""
    hx = _num(roof, "edge_height_x", "roof", errors, positive=False)
    hy = _num(roof, "edge_height_y", "roof", errors, positive=False)
    hc = _num(roof, "center_height", "roof", errors, positive=False)
    for key, v in (("edge_height_x", hx), ("edge_height_y", hy), ("center_height", hc)):
        if v is not None and v < 0:
            errors.append(f"roof.{key}: must be >= 0 (heights are measured from the wall top)")
    _num(roof, "thickness", "roof", errors, required=False)
    eave = _num(roof, "eave_radius", "roof", errors, required=False)
    ov = roof.get("overhang", 0)
    if eave is not None and top_r is not None:
        if eave < top_r - EPS:
            errors.append(f"roof.eave_radius: {eave:g} m is inside the wall top ({top_r:g} m)")
        elif "overhang" in roof and isinstance(ov, (int, float)) and abs(eave - (top_r + ov)) > 0.01:
            errors.append(f"roof.eave_radius ({eave:g}) and roof.overhang ({ov:g}) disagree: "
                          f"wall top {top_r:g} + overhang {ov:g} = {top_r + ov:g}")
    if None not in (hx, hy, hc) and (hx - hc) * (hy - hc) >= 0:
        warnings.append("roof: rim heights are not on opposite sides of the centre height — "
                        "this is a bowl or a dome, not a saddle")


def validate(sk):
    """Check a skeleton. Returns (errors, warnings); an empty errors list means it can be built."""
    errors, warnings = [], []
    if not isinstance(sk, dict):
        return ["skeleton: must be a JSON object"], []

    seg = sk.get("segments", 64)
    if not isinstance(seg, int) or isinstance(seg, bool) or not 8 <= seg <= 256:
        errors.append("segments: must be an integer 8..256")

    drum = sk.get("drum")
    if not isinstance(drum, dict):
        errors.append("drum: required object")
        drum = {}
    r = _num(drum, "radius", "drum", errors, default=1)
    h = _num(drum, "height", "drum", errors, default=1)
    top_r = _num(drum, "top_radius", "drum", errors, required=False, default=r)

    levels = sk.get("levels")
    level_ids = set()
    if not isinstance(levels, list) or not levels:
        errors.append("levels: required non-empty list")
        levels = []
    prev_top = 0.0
    for i, lv in enumerate(levels):
        where = f"levels[{i}]"
        if not isinstance(lv, dict):
            errors.append(f"{where}: must be an object")
            continue
        _id(lv, where, errors, level_ids)
        z = _num(lv, "z", where, errors, positive=False, default=0)
        lh = _num(lv, "height", where, errors, default=1)
        if z is not None and z < 0:
            errors.append(f"{where}.z: must be >= 0")
        if z is not None and lh is not None:
            if z < prev_top - EPS:
                errors.append(f"{where}: overlaps the level below (z {z} < {prev_top})")
            elif z > prev_top + EPS:
                warnings.append(f"{where}: gap of {z - prev_top:g} m below this level")
            prev_top = z + lh
    if levels and h is not None and prev_top > h + EPS:
        errors.append(f"levels: top at {prev_top:g} m is above drum.height {h:g} m")
    elif levels and h is not None and prev_top < h - EPS:
        warnings.append(f"levels: top at {prev_top:g} m is below drum.height {h:g} m — the rest is not split into levels")

    ring = sk.get("ring")
    if ring is not None:
        if not isinstance(ring, dict):
            errors.append("ring: must be an object")
        else:
            ri = _num(ring, "inner_radius", "ring", errors)
            ro = _num(ring, "outer_radius", "ring", errors)
            _num(ring, "height", "ring", errors)
            if ri is not None and ro is not None and ro <= ri:
                errors.append("ring.outer_radius: must be greater than inner_radius")

    pylons = sk.get("pylons")
    if pylons is not None:
        if not isinstance(pylons, dict):
            errors.append("pylons: must be an object")
        else:
            c = pylons.get("count")
            if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= 99:
                errors.append("pylons.count: must be an integer 0..99")
            _num(pylons, "start_angle_deg", "pylons", errors, positive=False, required=False)
            for k in ("radius", "width", "depth", "height"):
                _num(pylons, k, "pylons", errors)

    roof = sk.get("roof")
    if roof is not None:
        if not isinstance(roof, dict):
            errors.append("roof: must be an object")
        else:
            rtype = roof.get("type")
            if rtype not in ROOF_TYPES:
                errors.append(f"roof.type: must be one of {', '.join(ROOF_TYPES)}")
            ov = _num(roof, "overhang", "roof", errors, positive=False, required=False, default=0)
            if ov is not None and ov < 0:
                errors.append("roof.overhang: must be >= 0")
            if rtype == "saddle":
                _validate_saddle(roof, top_r, errors, warnings)
            else:
                _num(roof, "height", "roof", errors, required=rtype != "flat")

    wing_ids = set()
    for i, w in enumerate(sk.get("wings") or []):
        where = f"wings[{i}]"
        if not isinstance(w, dict):
            errors.append(f"{where}: must be an object")
            continue
        _id(w, where, errors, wing_ids)
        _num(w, "x", where, errors, positive=False)
        _num(w, "y", where, errors, positive=False)
        for k in ("width", "depth", "height"):
            _num(w, k, where, errors)
        _num(w, "rotation_deg", where, errors, positive=False, required=False)

    ent_ids = set()
    levels_by_id = {lv.get("id"): lv for lv in levels if isinstance(lv, dict)}
    for i, e in enumerate(sk.get("entrances") or []):
        where = f"entrances[{i}]"
        if not isinstance(e, dict):
            errors.append(f"{where}: must be an object")
            continue
        _id(e, where, errors, ent_ids)
        has_angle, has_pos = "angle_deg" in e, "position" in e
        if has_angle == has_pos:
            errors.append(f"{where}: give exactly one of angle_deg or position")
        if has_angle:
            _num(e, "angle_deg", where, errors, positive=False)
        if has_pos:
            p = e.get("position")
            if not (isinstance(p, list) and len(p) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in p)):
                errors.append(f"{where}.position: must be [x, y]")
            _num(e, "facing_deg", where, errors, positive=False)
        _num(e, "width", where, errors)
        eh = _num(e, "height", where, errors)
        lv = levels_by_id.get(e.get("level"))
        if lv is None:
            errors.append(f"{where}.level: must be one of the level ids")
        elif eh is not None and isinstance(lv.get("height"), (int, float)) and eh > lv["height"] + EPS:
            errors.append(f"{where}.height: {eh} m is taller than its level ({lv['height']} m)")

    clash = (level_ids & wing_ids) | (level_ids & ent_ids) | (wing_ids & ent_ids)
    if clash:
        errors.append(f"ids used twice across levels/wings/entrances: {sorted(clash)}")
    return errors, warnings


# ----------------------------------------------------------------- meshes
# Each generator returns (verts, faces); verts are (x, y, z), faces are index tuples
# wound counter-clockwise when seen from outside.

def _circle(r, z, n):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z) for i in range(n)]


def cylinder(r, z0, z1, n):
    return frustum(r, r, z0, z1, n)


def frustum(r0, r1, z0, z1, n):
    """Truncated cone: radius r0 at z0, r1 at z1 (a cylinder when they are equal)."""
    verts = _circle(r0, z0, n) + _circle(r1, z1, n) + [(0.0, 0.0, z0), (0.0, 0.0, z1)]
    cb, ct = 2 * n, 2 * n + 1
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))       # side
        faces.append((cb, j, i))                  # bottom, facing down
        faces.append((ct, n + i, n + j))          # top, facing up
    return verts, faces


def ring(r_in, r_out, z0, z1, n):
    verts = _circle(r_out, z0, n) + _circle(r_out, z1, n) + _circle(r_in, z0, n) + _circle(r_in, z1, n)
    ob, ot, ib, it = 0, n, 2 * n, 3 * n
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((ob + i, ob + j, ot + j, ot + i))   # outer wall
        faces.append((ib + j, ib + i, it + i, it + j))   # inner wall, facing the centre
        faces.append((ot + i, ot + j, it + j, it + i))   # top
        faces.append((ob + j, ob + i, ib + i, ib + j))   # bottom
    return verts, faces


def box(cx, cy, z0, width, depth, height, bearing_deg=0.0):
    """Box centred on (cx, cy); width along local x, depth along local y.
    bearing_deg turns local +y from north towards east (clockwise seen from above)."""
    a = math.radians(bearing_deg)
    ca, sa = math.cos(a), math.sin(a)
    verts = []
    for z in (z0, z0 + height):
        for lx, ly in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            x, y = lx * width / 2, ly * depth / 2
            verts.append((cx + x * ca + y * sa, cy - x * sa + y * ca, z))
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return verts, faces


def dome(r, z0, height, n, rings=12):
    """Half ellipsoid: base radius r at z0, top at z0 + height, closed underneath."""
    verts, faces = [], []
    for k in range(rings):
        phi = (math.pi / 2) * k / rings
        verts += _circle(r * math.cos(phi), z0 + height * math.sin(phi), n)
    apex, base = len(verts), len(verts) + 1
    verts += [(0.0, 0.0, z0 + height), (0.0, 0.0, z0)]
    for k in range(rings - 1):
        for i in range(n):
            j = (i + 1) % n
            faces.append((k * n + i, k * n + j, (k + 1) * n + j, (k + 1) * n + i))
    top = (rings - 1) * n
    for i in range(n):
        j = (i + 1) % n
        faces.append((top + i, top + j, apex))
        faces.append((base, j, i))
    return verts, faces


def cone(r, z0, height, n):
    verts = _circle(r, z0, n) + [(0.0, 0.0, z0 + height), (0.0, 0.0, z0)]
    apex, base = n, n + 1
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, apex))
        faces.append((base, j, i))
    return verts, faces


def saddle_height(x, y, radius, hx, hy, hc):
    """Hyperbolic paraboloid over a circle: hc in the centre, hx on the rim at the x axis, hy at the y axis."""
    u, v = x / radius, y / radius
    return hc + (hx - hc) * u * u + (hy - hc) * v * v


def _polar_grid(radius, n, rings, height_fn):
    """Centre vertex, then `rings` circles out to `radius`; z from height_fn(x, y)."""
    verts = [(0.0, 0.0, height_fn(0.0, 0.0))]
    for k in range(1, rings + 1):
        rr = radius * k / rings
        for x, y, _ in _circle(rr, 0.0, n):
            verts.append((x, y, height_fn(x, y)))
    return verts


def saddle_roof(wall_r, z0, n, hx, hy, hc, eave_r, thickness, rings=10):
    """Saddle roof as two closed shells in one mesh:
    a thin canopy (thickness) out to eave_r, and an infill from the flat wall top (z0)
    up to the canopy's underside inside wall_r, so no gap opens where the rim rises."""
    verts, faces = [], []

    def shell(top_fn, bottom_fn, radius):
        base = len(verts)
        top = _polar_grid(radius, n, rings, top_fn)
        bottom = _polar_grid(radius, n, rings, bottom_fn)
        verts.extend(top + bottom)
        t, b = base, base + len(top)
        ring_at = lambda k, i: 1 + (k - 1) * n + (i % n)  # noqa: E731
        for i in range(n):
            faces.append((t, t + ring_at(1, i), t + ring_at(1, i + 1)))       # top fan, facing up
            faces.append((b, b + ring_at(1, i + 1), b + ring_at(1, i)))       # bottom fan, facing down
        for k in range(1, rings):
            for i in range(n):
                a0, a1 = ring_at(k, i), ring_at(k, i + 1)
                c0, c1 = ring_at(k + 1, i), ring_at(k + 1, i + 1)
                faces.append((t + a0, t + c0, t + c1, t + a1))
                faces.append((b + a0, b + a1, b + c1, b + c0))
        for i in range(n):                                                   # rim wall
            o0, o1 = ring_at(rings, i), ring_at(rings, i + 1)
            faces.append((b + o0, b + o1, t + o1, t + o0))

    surface = lambda x, y: z0 + saddle_height(x, y, eave_r, hx, hy, hc)  # noqa: E731
    shell(surface, lambda x, y: surface(x, y) - thickness, eave_r)
    # infill: slightly inside the wall and just under the canopy, so the two shells never touch
    inner = wall_r - 0.05
    shell(lambda x, y: max(surface(x, y) - thickness - 0.02, z0 + 0.02), lambda x, y: z0, inner)
    return verts, faces


def bearing_point(radius, bearing_deg):
    a = math.radians(bearing_deg)
    return radius * math.sin(a), radius * math.cos(a)


# ----------------------------------------------------------------- the whole venue

def build_parts(sk):
    """Skeleton → parts and cutters.

    parts:   [{name, kind, level, material, verts, faces}] — one node each in the model
    cutters: [{name, targets, verts, faces}] — boolean-subtracted from the targets, then removed
    """
    n = sk.get("segments", 64)
    drum = sk["drum"]
    r = drum["radius"]
    top_r = drum.get("top_radius", r)
    parts, cutters = [], []

    def radius_at(z):
        """Drum radius at height z (the wall may lean in or out)."""
        return r + (top_r - r) * min(max(z / drum["height"], 0.0), 1.0)

    for lv in sk["levels"]:
        z0, z1 = lv["z"], lv["z"] + lv["height"]
        v, f = frustum(radius_at(z0), radius_at(z1), z0, z1, n)
        parts.append(dict(name=lv["id"], kind="level", level=lv["id"], material="building", verts=v, faces=f))

    ring_spec = sk.get("ring")
    if ring_spec:
        v, f = ring(ring_spec["inner_radius"], ring_spec["outer_radius"], 0.0, ring_spec["height"], n)
        parts.append(dict(name="ring", kind="ring", level=sk["levels"][0]["id"], material="building", verts=v, faces=f))

    roof = sk.get("roof")
    if roof:
        rr = roof.get("eave_radius", top_r + roof.get("overhang", 0))
        z0 = drum["height"]
        if roof["type"] == "saddle":
            v, f = saddle_roof(top_r, z0, n, roof["edge_height_x"], roof["edge_height_y"], roof["center_height"],
                               rr, roof.get("thickness", 0.6))
        elif roof["type"] == "dome":
            v, f = dome(rr, z0, roof["height"], n)
        elif roof["type"] == "cone":
            v, f = cone(rr, z0, roof["height"], n)
        else:
            v, f = cylinder(rr, z0, z0 + max(roof.get("height", 0.6), 0.2), n)
        parts.append(dict(name="roof", kind="roof", level=None, material="roof", verts=v, faces=f))

    pylons = sk.get("pylons")
    if pylons and pylons["count"]:
        step = 360.0 / pylons["count"]
        for i in range(pylons["count"]):
            b = pylons.get("start_angle_deg", 0) + i * step
            cx, cy = bearing_point(pylons["radius"], b)
            # depth runs radially (local +y points outward), width runs along the circle
            v, f = box(cx, cy, 0.0, pylons["width"], pylons["depth"], pylons["height"], b)
            parts.append(dict(name=f"pylon_{i + 1:02d}", kind="pylon", level=None, material="pylon", verts=v, faces=f))

    for w in sk.get("wings") or []:
        v, f = box(w["x"], w["y"], 0.0, w["width"], w["depth"], w["height"], w.get("rotation_deg", 0))
        parts.append(dict(name=f"wing_{w['id']}", kind="wing", level=sk["levels"][0]["id"], material="wing", verts=v, faces=f))

    levels = {lv["id"]: lv for lv in sk["levels"]}
    wall_targets = [lv["id"] for lv in sk["levels"]] + (["ring"] if ring_spec else []) + [f"wing_{w['id']}" for w in sk.get("wings") or []]
    for e in sk.get("entrances") or []:
        z0 = levels[e["level"]]["z"]
        if "angle_deg" in e:
            facing = e["angle_deg"]
            wall_in = min(radius_at(z0), radius_at(z0 + e["height"]))
            wall_out = max(radius_at(z0), radius_at(z0 + e["height"]))
            on_ring = ring_spec and z0 < ring_spec["height"]
            outer = max(wall_out, ring_spec["outer_radius"] if on_ring else 0)
            cx, cy = bearing_point(outer, facing)
            # through the ring and a few metres into the drum
            depth = (outer - wall_in) + 4.0
            ccx, ccy = bearing_point(outer - depth / 2 + 0.5, facing)
        else:
            cx, cy = e["position"]
            facing = e["facing_deg"]
            depth = 4.0
            ccx, ccy = cx, cy
        v, f = box(ccx, ccy, z0 - 0.05, e["width"], depth + 1.0, e["height"] + 0.05, facing)
        cutters.append(dict(name=f"cut_{e['id']}", targets=wall_targets, verts=v, faces=f))
        # the entrance node: a canopy just outside the opening, so it stays visible and clickable
        ox, oy = bearing_point(1.0, facing)
        v, f = box(cx + ox, cy + oy, z0 + e["height"], e["width"] + 1.0, 2.2, 0.4, facing)
        parts.append(dict(name=f"entrance_{e['id']}", kind="entrance", level=e["level"], material="accent", verts=v, faces=f))

    return parts, cutters


def is_closed_manifold(verts, faces):
    """Every directed edge appears once and its reverse once: closed and consistently wound."""
    seen = {}
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            seen[(a, b)] = seen.get((a, b), 0) + 1
    return all(c == 1 and seen.get((b, a)) == 1 for (a, b), c in seen.items())


def signed_volume(verts, faces):
    """Positive for outward-facing normals."""
    vol = 0.0
    for face in faces:
        p0 = verts[face[0]]
        for i in range(1, len(face) - 1):
            p1, p2 = verts[face[i]], verts[face[i + 1]]
            vol += (p0[0] * (p1[1] * p2[2] - p1[2] * p2[1])
                    - p0[1] * (p1[0] * p2[2] - p1[2] * p2[0])
                    + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0])) / 6.0
    return vol


def summary(parts):
    """Per node: vertex/face counts and bounds (rounded) — the JS port is checked against this."""
    out = {}
    for p in parts:
        xs, ys, zs = zip(*p["verts"])
        out[p["name"]] = {
            "verts": len(p["verts"]), "faces": len(p["faces"]),
            "min": [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)],
            "max": [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)],
        }
    return out


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv):
    if len(argv) != 1:
        print("usage: python3 venue_geometry.py skeleton.json", file=sys.stderr)
        return 2
    try:
        sk = load(argv[0])
    except (OSError, ValueError) as e:
        print(f"ERROR cannot read {argv[0]}: {e}", file=sys.stderr)
        return 1
    errors, warnings = validate(sk)
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    parts, cutters = build_parts(sk)
    print(f"OK {sk.get('name', '')}: {len(parts)} nodes ({', '.join(p['name'] for p in parts)}), "
          f"{len(cutters)} openings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
