"""The Blender-free half of prepare_glb.py: rules, colours, size planning and a GLB reader.

Standard library only, so it is tested without Blender:

    python3 -m unittest discover -s blender/tests -v

Check a rules file without Blender:

    python3 blender/glb_prep.py rules.json

Read back what an exported .glb holds (nodes, colours, triangles, UV, Draco):

    python3 blender/glb_prep.py --report model.glb

Rules (JSON) — which Blender objects become which node of the web model:

    {"level_0": ["walls_0.00", "columns_0.00"], "level_1": ["walls_*_1"], "roof": ["Roof"]}

or, with colours for nodes whose Blender material gives none:

    {"nodes": {"level_0": ["walls_0.00"]},
     "colors": {"level_0": "#b9bec6", "roof": [0.2, 0.25, 0.3]},
     "roughness": 0.8, "default_color": "#c8ccd1"}

A pattern is an object name, a collection name (all objects in it, nested ones too) or a
glob (`*`, `?`, `[...]`). Each object goes to the first node that claims it. Colours: "#rrggbb"
is sRGB like CSS; a list [r, g, b] is linear 0..1 like Blender's colour fields.
"""
import fnmatch
import json
import re
import struct
import sys

NODE_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,63}$")
DEFAULT_COLOR_SRGB = "#c8ccd1"
DEFAULT_ROUGHNESS = 0.8
GLOB_CHARS = set("*?[")


# ------------------------------------------------------------------ colours

def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    c = min(max(c, 0.0), 1.0)
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def parse_color(value):
    """'#rrggbb' (sRGB) or [r, g, b(, a)] (linear) → linear (r, g, b); None if not a colour."""
    if isinstance(value, str):
        m = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
        if not m:
            return None
        h = m.group(1)
        return tuple(round(srgb_to_linear(int(h[i:i + 2], 16) / 255), 6) for i in (0, 2, 4))
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        if all(isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1 for c in value):
            return tuple(float(c) for c in value[:3])
    return None


def color_hex(rgb):
    """Linear (r, g, b) → '#rrggbb' in sRGB (for logs and reports)."""
    return "#" + "".join(f"{round(linear_to_srgb(c) * 255):02x}" for c in rgb[:3])


def _socket(node, *names):
    """First input of a shader node with one of these names (duck-typed: works on fakes in tests)."""
    inputs = getattr(node, "inputs", None) or []
    for name in names:
        for sock in inputs:
            if getattr(sock, "name", None) == name:
                return sock
    return None


def _mean(colors):
    colors = [c for c in colors if c is not None]
    if not colors:
        return None
    return tuple(sum(c[i] for c in colors) / len(colors) for i in range(3))


def socket_color(sock, depth=0):
    """A plain colour for a shader input: its own value, or a simple guess through the node that feeds it.

    Understood: RGB, Color Ramp (mean of the stops), Mix (mean of the two colours), Reroute, and nodes
    that only shift a colour (Hue/Saturation, Bright/Contrast, Gamma, Invert — their input is taken).
    Textures and anything else → None: there is no single colour to read without baking.
    """
    if sock is None or depth > 8:
        return None
    if not getattr(sock, "is_linked", False):
        v = getattr(sock, "default_value", None)
        try:
            return tuple(float(v[i]) for i in range(3))
        except (TypeError, IndexError, ValueError):
            return None
    links = getattr(sock, "links", None) or []
    if not links:
        return None
    node = links[0].from_node
    kind = getattr(node, "type", "")
    if kind == "RGB":  # its colour is the value of its output socket (which is linked, so read it directly)
        outs = getattr(node, "outputs", None) or []
        try:
            return tuple(float(outs[0].default_value[i]) for i in range(3))
        except (TypeError, IndexError, ValueError, AttributeError):
            return None
    if kind == "VALTORGB":
        ramp = getattr(node, "color_ramp", None)
        return _mean([tuple(e.color[:3]) for e in getattr(ramp, "elements", [])])
    if kind in ("MIX", "MIX_RGB"):
        a = _socket(node, "A", "Color1")
        b = _socket(node, "B", "Color2")
        # the Mix node (3.4+) has float, vector and colour A/B — take the colour ones
        cols = [s for s in (getattr(node, "inputs", None) or [])
                if getattr(s, "name", None) in ("A", "B") and getattr(s, "type", "RGBA") == "RGBA"]
        if len(cols) == 2:
            a, b = cols
        return _mean([socket_color(a, depth + 1), socket_color(b, depth + 1)])
    if kind in ("REROUTE", "HUE_SAT", "BRIGHTCONTRAST", "GAMMA", "INVERT"):
        sock_in = _socket(node, "Color", "Input")
        if sock_in is None and getattr(node, "inputs", None):
            sock_in = node.inputs[0]
        c = socket_color(sock_in, depth + 1)
        if c is not None and kind == "INVERT":
            c = tuple(1 - x for x in c)
        return c
    return None


def material_color(material):
    """(rgb, roughness) from a Blender material's Principled BSDF, or (None, None) if there is none to read.

    rgb is linear, as Blender stores it and as glTF wants it. Roughness is None when it is driven by a texture.
    """
    tree = getattr(material, "node_tree", None)
    nodes = getattr(tree, "nodes", None) or []
    bsdf = next((n for n in nodes if getattr(n, "type", "") == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None, None
    rgb = socket_color(_socket(bsdf, "Base Color"))
    rough_sock = _socket(bsdf, "Roughness")
    rough = None
    if rough_sock is not None and not getattr(rough_sock, "is_linked", False):
        try:
            rough = float(rough_sock.default_value)
        except (TypeError, ValueError):
            rough = None
    return rgb, rough


# ------------------------------------------------------------------ rules

def parse_rules(raw):
    """Check a rules object. Never raises: returns (rules, errors, warnings); rules is None only if unusable."""
    errors, warnings = [], []
    if not isinstance(raw, dict):
        return None, ["rules: must be a JSON object"], warnings
    extended = isinstance(raw.get("nodes"), dict)
    node_map = raw["nodes"] if extended else raw
    if extended:
        for key in raw:
            if key not in ("nodes", "colors", "roughness", "default_color"):
                warnings.append(f"{key}: unknown field (ignored)")
    nodes = {}
    for name, patterns in node_map.items():
        if not isinstance(name, str) or not NODE_NAME.match(name):
            errors.append(f"nodes.{name}: node name must be 1-63 of [A-Za-z0-9_.-]")
            continue
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
            errors.append(f"nodes.{name}: must be a non-empty list of object/collection names or globs")
            continue
        nodes[name] = list(patterns)
    if not nodes and not errors:
        errors.append("rules: no nodes — nothing would be merged")

    colors = {}
    raw_colors = raw.get("colors", {}) if extended else {}
    if not isinstance(raw_colors, dict):
        errors.append("colors: must be an object {node: colour}")
        raw_colors = {}
    for name, value in raw_colors.items():
        rgb = parse_color(value)
        if rgb is None:
            errors.append(f"colors.{name}: must be \"#rrggbb\" or [r, g, b] in 0..1")
        else:
            colors[name] = rgb
            if name not in nodes:
                warnings.append(f"colors.{name}: no node with this name (used only for unmatched objects of that name)")

    roughness = raw.get("roughness", DEFAULT_ROUGHNESS) if extended else DEFAULT_ROUGHNESS
    if not isinstance(roughness, (int, float)) or isinstance(roughness, bool) or not 0 <= roughness <= 1:
        errors.append("roughness: must be a number in 0..1")
        roughness = DEFAULT_ROUGHNESS
    default = parse_color(raw.get("default_color", DEFAULT_COLOR_SRGB) if extended else DEFAULT_COLOR_SRGB)
    if default is None:
        errors.append("default_color: must be \"#rrggbb\" or [r, g, b] in 0..1")
        default = parse_color(DEFAULT_COLOR_SRGB)
    rules = {"nodes": nodes, "colors": colors, "roughness": float(roughness), "default_color": default}
    return (rules if nodes else None), errors, warnings


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        return parse_rules(json.load(f))


def _matches(pattern, name):
    return fnmatch.fnmatchcase(name, pattern) if GLOB_CHARS & set(pattern) else name == pattern


def assign_objects(object_names, collections, rules):
    """Which objects go into which node.

    object_names: names of the mesh-like objects, in scene order.
    collections: {collection name: [object names in it, nested included]}.
    → (groups {node: [object names]}, unmatched [object names], warnings)
    """
    warnings = []
    groups = {name: [] for name in rules["nodes"]}
    owner = {}
    for node, patterns in rules["nodes"].items():
        for pattern in patterns:
            hits = [o for o in object_names if _matches(pattern, o)]
            for coll, members in collections.items():
                if _matches(pattern, coll):
                    hits.extend(m for m in members if m in object_names)
            if not hits:
                warnings.append(f"{node}: pattern {pattern!r} matches no object or collection")
            for obj in hits:
                if obj in owner:
                    if owner[obj] != node:
                        warnings.append(f"{obj}: claimed by {owner[obj]} and {node} — stays in {owner[obj]}")
                    continue
                owner[obj] = node
                groups[node].append(obj)
    for node, members in groups.items():
        if not members:
            warnings.append(f"{node}: empty — no node is written")
    unmatched = [o for o in object_names if o not in owner]
    return {n: m for n, m in groups.items() if m}, unmatched, warnings


def node_color(node, rules):
    """The fallback colour for a node (rules → default)."""
    return rules["colors"].get(node, rules["default_color"])


def node_extras(node):
    """glTF extras for a merged node: level_* nodes say which level they are (the viewer also reads this)."""
    return {"level": node} if node.startswith("level_") else {}


# ------------------------------------------------------------------ size

def plan_ratio(size, cap, floor=0.02, margin=0.92):
    """How much of the geometry to keep so the file gets under `cap` bytes (the size is ~ linear in triangles)."""
    if size <= cap:
        return 1.0
    return max(floor, min(1.0, cap * margin / size))


# ------------------------------------------------------------------ GLB reader

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def read_glb(data):
    """Bytes (or a path) of a .glb → (gltf JSON dict, binary chunk bytes). Raises ValueError if not a GLB."""
    if isinstance(data, str):
        with open(data, "rb") as f:
            data = f.read()
    if len(data) < 20:
        raise ValueError("not a GLB: too short")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2:
        raise ValueError("not a GLB 2.0 file")
    if length != len(data):
        raise ValueError(f"GLB length {length} != file size {len(data)}")
    gltf, binary, offset = None, b"", 12
    while offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        body = data[offset + 8: offset + 8 + chunk_len]
        if chunk_type == CHUNK_JSON:
            gltf = json.loads(body.decode("utf-8"))
        elif chunk_type == CHUNK_BIN:
            binary = body
        offset += 8 + chunk_len
    if gltf is None:
        raise ValueError("GLB has no JSON chunk")
    return gltf, binary


def summarize_glb(gltf, size=None):
    """What a viewer will get from the file: per node its colours, triangles and attributes."""
    materials = gltf.get("materials", [])
    accessors = gltf.get("accessors", [])
    meshes = gltf.get("meshes", [])
    used = set(gltf.get("extensionsUsed", []))
    nodes = []
    for node in gltf.get("nodes", []):
        entry = {"name": node.get("name", ""), "extras": node.get("extras", {}), "colors": [],
                 "triangles": 0, "attributes": set()}
        if "mesh" in node:
            for prim in meshes[node["mesh"]].get("primitives", []):
                entry["attributes"].update(prim.get("attributes", {}).keys())
                if "indices" in prim:
                    entry["triangles"] += accessors[prim["indices"]]["count"] // 3
                elif "POSITION" in prim.get("attributes", {}):
                    entry["triangles"] += accessors[prim["attributes"]["POSITION"]]["count"] // 3
                mat = materials[prim["material"]] if "material" in prim else {}
                pbr = mat.get("pbrMetallicRoughness", {})
                entry["colors"].append({
                    "material": mat.get("name", ""),
                    "base_color": tuple(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0))),
                    "roughness": pbr.get("roughnessFactor", 1.0),
                    "textured": "baseColorTexture" in pbr,
                })
        entry["attributes"] = sorted(entry["attributes"])
        nodes.append(entry)
    return {
        "size": size,
        "nodes": nodes,
        "triangles": sum(n["triangles"] for n in nodes),
        "draco": "KHR_draco_mesh_compression" in used,
        "textures": len(gltf.get("textures", [])),
        "uv": any(a.startswith("TEXCOORD_") for n in nodes for a in n["attributes"]),
        "normals": any(a == "NORMAL" for n in nodes for a in n["attributes"]),
    }


def format_report(summary):
    lines = []
    size = summary["size"]
    head = f"{size / 1024 / 1024:.2f} MB, " if size is not None else ""
    flags = ", ".join(f for f, on in (("Draco", summary["draco"]), ("normals", summary["normals"]),
                                      ("UV", summary["uv"])) if on) or "positions only"
    lines.append(f"{head}{len(summary['nodes'])} nodes, {summary['triangles']} triangles, {flags}, "
                 f"{summary['textures']} textures")
    for n in summary["nodes"]:
        cols = " ".join(color_hex(c["base_color"]) + ("+tex" if c["textured"] else "") for c in n["colors"])
        lines.append(f"  {n['name']}: {n['triangles']} tris, {cols or 'no mesh'}")
    return "\n".join(lines)


def main(argv):
    if len(argv) == 2 and argv[0] == "--report":
        with open(argv[1], "rb") as f:
            data = f.read()
        print(format_report(summarize_glb(read_glb(data)[0], len(data))))
        return 0
    if len(argv) != 1:
        print("usage: python3 glb_prep.py rules.json | python3 glb_prep.py --report model.glb", file=sys.stderr)
        return 2
    try:
        rules, errors, warnings = load_rules(argv[0])
    except (OSError, ValueError) as e:
        print(f"ERROR cannot read {argv[0]}: {e}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    for node, patterns in rules["nodes"].items():
        print(f"{node} ← {', '.join(patterns)}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
