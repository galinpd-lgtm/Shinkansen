"""Build a venue model from skeleton.json and export it as glTF binary.

    blender -b --python build_venue.py -- skeleton.json out.glb

Also runs with the `bpy` module from PyPI (same API, no Blender UI):

    python3 build_venue.py -- skeleton.json out.glb

Everything comes from the numbers in skeleton.json (see skeleton.schema.md). Each element
is its own named node — level_0, level_1, ring, roof, pylon_01, wing_<id>, entrance_<id> —
so the web viewer can hide levels and pin hotspots. Openings are cut with booleans.

Written against Blender 5.x. Where the API has enums or names that moved between versions
(export format, boolean solver, material setup), the script tries a list of candidates
instead of assuming one value.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402  (first: with the PyPI module, bmesh only exists after bpy is imported)
import bmesh  # noqa: E402

import venue_geometry as vg  # noqa: E402

# Flat, calm colours (linear RGBA). The viewer can restyle the page, not the model.
MATERIALS = {
    "building": (0.62, 0.64, 0.67, 1.0),
    "roof": (0.36, 0.42, 0.50, 1.0),
    "pylon": (0.80, 0.81, 0.83, 1.0),
    "wing": (0.55, 0.57, 0.60, 1.0),
    "accent": (0.85, 0.45, 0.12, 1.0),
}
BOOLEAN_SOLVERS = ("EXACT", "MANIFOLD", "FLOAT", "FAST")
GLTF_FORMATS = ("GLB", "GLTF_BINARY")


def log(msg):
    print(f"[build_venue] {msg}", flush=True)


def script_args():
    """Arguments after '--' (Blender keeps its own options before it)."""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(name, rgba):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    if getattr(mat, "node_tree", None) is None:
        try:
            mat.use_nodes = True  # older versions; newer ones always have nodes and deprecate this
        except (AttributeError, TypeError):
            pass
    tree = getattr(mat, "node_tree", None)
    if tree is not None:
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        for socket_name, value in (("Base Color", rgba), ("Roughness", 0.8), ("Metallic", 0.0)):
            socket = bsdf.inputs.get(socket_name)
            if socket is not None:
                socket.default_value = value
    return mat


def add_mesh(name, verts, faces, material=None, props=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if material is not None:
        obj.data.materials.append(material)
    for key, value in (props or {}).items():
        if value is not None:
            obj[key] = value  # exported as glTF extras
    return obj


def set_first_valid(obj, attr, candidates):
    """Assign the first candidate the property accepts; returns it or None."""
    for value in candidates:
        try:
            setattr(obj, attr, value)
            return value
        except (TypeError, ValueError):
            continue
    return None


def cut(target, cutter):
    """Subtract cutter from target by evaluating a boolean modifier (no operator context needed)."""
    mod = target.modifiers.new(name=f"cut_{cutter.name}", type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    set_first_valid(mod, "solver", BOOLEAN_SOLVERS)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = target.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    old = target.data
    name = old.name
    target.modifiers.remove(mod)
    target.data = new_mesh
    bpy.data.meshes.remove(old)
    new_mesh.name = name  # after removing the old mesh, so the name stays without a .001 suffix


def overlaps(a, b):
    """Axis-aligned bounding boxes of two objects intersect."""
    def bounds(o):
        xs = [v.co.x for v in o.data.vertices]
        ys = [v.co.y for v in o.data.vertices]
        zs = [v.co.z for v in o.data.vertices]
        return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    ax0, ax1, ay0, ay1, az0, az1 = bounds(a)
    bx0, bx1, by0, by1, bz0, bz1 = bounds(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1 and az0 < bz1 and bz0 < az1


def export_glb(path):
    op = bpy.ops.export_scene.gltf
    known = set(op.get_rna_type().properties.keys())
    wanted = {
        "filepath": path,
        "export_yup": True,        # glTF is Y-up: plan (x, y, z) becomes (x, z, -y)
        "export_apply": True,
        "export_extras": True,     # custom properties (kind, level) → node extras
        "export_cameras": False,
        "export_lights": False,
        "export_draco_mesh_compression_enable": False,
    }
    kwargs = {k: v for k, v in wanted.items() if k in known}
    last_error = None
    for fmt in GLTF_FORMATS:
        try:
            result = op(export_format=fmt, **kwargs)
        except TypeError as e:  # unknown enum value in this version
            last_error = e
            continue
        if "FINISHED" in result:
            return fmt
        last_error = RuntimeError(f"exporter returned {result}")
    raise RuntimeError(f"glTF export failed with every format {GLTF_FORMATS}: {last_error}")


def main():
    args = script_args()
    if len(args) != 2:
        log("usage: blender -b --python build_venue.py -- skeleton.json out.glb")
        return 2
    src, out = args
    try:
        sk = vg.load(src)
    except (OSError, ValueError) as e:
        log(f"ERROR cannot read {src}: {e}")
        return 1
    errors, warnings = vg.validate(sk)
    for w in warnings:
        log(f"WARNING {w}")
    if errors:
        for e in errors:
            log(f"ERROR {e}")
        return 1

    log(f"Blender {bpy.app.version_string}")
    reset_scene()
    materials = {name: make_material(name, rgba) for name, rgba in MATERIALS.items()}
    parts, cutters = vg.build_parts(sk)

    objects = {}
    for p in parts:
        objects[p["name"]] = add_mesh(p["name"], p["verts"], p["faces"], materials[p["material"]],
                                      {"kind": p["kind"], "level": p["level"]})
    for c in cutters:
        cutter = add_mesh(c["name"], c["verts"], c["faces"])
        cutter.hide_render = True
        for name in c["targets"]:
            target = objects.get(name)
            if target is not None and overlaps(target, cutter):
                cut(target, cutter)
        bpy.data.objects.remove(cutter, do_unlink=True)

    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fmt = export_glb(out)
    size_kb = os.path.getsize(out) / 1024
    log(f"OK {out} ({fmt}, {size_kb:.0f} KB, {len(objects)} nodes, {len(cutters)} openings)")
    return 0


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
