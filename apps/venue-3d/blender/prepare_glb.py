"""Prepare any .blend (or .glb) for the <venue-3d> viewer: merged nodes per level, plain colours, under a size cap.

    blender -b --python blender/prepare_glb.py -- in.blend rules.json out.glb [--max-mb 5]

Also runs with the `bpy` module from PyPI (same API, no Blender UI):

    python3 blender/prepare_glb.py -- in.blend rules.json out.glb

What it does, in order:
  1. Merges the objects into the nodes named in rules.json ({"level_0": ["walls_0.00", ...], ...}; see
     glb_prep.py for the format). Objects no rule claims stay as their own nodes (--drop-unmatched drops them).
  2. Welds vertices closer than --merge-dist, dissolves flat faces into n-gons (--planar-angle; the shape
     stays), drops loose edges and points.
  3. Replaces every material with a plain one: the Base Color and Roughness of its Principled BSDF, or the
     node's colour from rules.json when there is nothing to read (procedural textures, no Principled).
     No baking. With no textures left, UV maps and colour attributes are removed.
  4. Exports glTF binary and, while the file is over --max-mb, tries in turn: no normals (the viewer
     shades flat), Draco compression (--draco auto|on|off; the viewer ships the decoder), and finally
     collapse decimation — the only step that changes the shape.

Exit codes: 0 OK, 1 bad input, 2 usage, 3 still over the cap after every step (the file is kept).
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402  (first: with the PyPI module, bmesh only exists after bpy is imported)
import bmesh  # noqa: E402

import glb_prep as gp  # noqa: E402
from build_venue import export_glb, make_material, script_args  # noqa: E402

MESHLIKE = {"MESH", "CURVE", "SURFACE", "META", "FONT"}
MAX_DECIMATE_ROUNDS = 8


def log(msg):
    print(f"[prepare_glb] {msg}", flush=True)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="prepare_glb.py", description="Prepare a .blend for the venue-3d viewer.")
    p.add_argument("source", help=".blend (or .glb/.gltf) to prepare")
    p.add_argument("rules", help="rules.json: which objects make which node, fallback colours")
    p.add_argument("out", help="output .glb")
    p.add_argument("--max-mb", type=float, default=5.0, help="size cap of the .glb in MB (default 5)")
    p.add_argument("--merge-dist", type=float, default=0.001, help="weld vertices closer than this, m (default 0.001)")
    p.add_argument("--planar-angle", type=float, default=0.5,
                   help="dissolve faces flatter than this, degrees; 0 turns it off (default 0.5)")
    p.add_argument("--draco", choices=("auto", "on", "off"), default="auto",
                   help="Draco compression: only when needed (auto), always, never")
    p.add_argument("--keep-normals", action="store_true", help="never drop normals to save size")
    p.add_argument("--drop-unmatched", action="store_true", help="leave out objects no rule claims")
    return p.parse_args(argv)


def load_source(path):
    if path.lower().endswith((".glb", ".gltf")):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.wm.open_mainfile(filepath=path)


class Palette:
    """Plain materials, one per colour: the Principled BSDF of the source, else the node's colour from the rules."""

    def __init__(self, rules):
        self.rules = rules
        self.by_key = {}
        self.cache = {}
        self.fallbacks = []

    def material_for(self, source, node):
        key = (source.name if source is not None else None, node)
        if key not in self.cache:
            rgb, rough = gp.material_color(source) if source is not None else (None, None)
            if rgb is None:
                rgb = gp.node_color(node, self.rules)
                self.fallbacks.append((node, source.name if source is not None else "(no material)"))
            if rough is None:
                rough = self.rules["roughness"]
            self.cache[key] = self.plain(rgb, rough)
        return self.cache[key]

    def plain(self, rgb, rough):
        hexc = gp.color_hex(rgb)
        key = (hexc, round(rough, 2))
        if key not in self.by_key:
            mat = make_material(f"{hexc[1:]}_r{round(rough * 100):02d}", (*rgb, 1.0))
            bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf.inputs["Roughness"].default_value = rough
            self.by_key[key] = mat
        return self.by_key[key]


def strip_layers(mesh):
    """No textures → no need for UV maps or colour attributes."""
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    colors = getattr(mesh, "color_attributes", None)
    while colors is not None and len(colors):
        colors.remove(colors[0])


def merged_mesh(node, objects, depsgraph, palette, args):
    """One mesh in world space from several objects (modifiers applied), cleaned up."""
    bm = bmesh.new()
    materials = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        me = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=False, depsgraph=depsgraph)
        me.transform(obj.matrix_world)
        if obj.matrix_world.determinant() < 0 and hasattr(me, "flip_normals"):
            me.flip_normals()  # mirrored objects would come out inside-out
        strip_layers(me)
        remap = []
        for slot in (obj.material_slots or [None]):
            mat = palette.material_for(slot.material if slot is not None else None, node)
            if mat not in materials:
                materials.append(mat)
            remap.append(materials.index(mat))
        index = [0] * len(me.polygons)
        me.polygons.foreach_get("material_index", index)
        me.polygons.foreach_set("material_index", [remap[min(i, len(remap) - 1)] for i in index])
        bm.from_mesh(me)  # appends to what is already in bm
        bpy.data.meshes.remove(me)

    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=args.merge_dist)
    welded = before - len(bm.verts)
    loose_edges = [e for e in bm.edges if not e.link_faces]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    loose_verts = [v for v in bm.verts if not v.link_faces]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    faces_before = len(bm.faces)
    if args.planar_angle > 0 and bm.faces:
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(args.planar_angle), use_dissolve_boundaries=False,
                                 verts=bm.verts, edges=bm.edges, delimit={"MATERIAL"})
    mesh = bpy.data.meshes.new(node)
    bm.to_mesh(mesh)
    bm.free()
    for mat in materials:
        mesh.materials.append(mat)
    mesh.update()
    log(f"{node}: {len(objects)} objects, welded {welded} vertices, "
        f"{faces_before} → {len(mesh.polygons)} faces, {len(mesh.vertices)} vertices")
    return mesh


def triangles(objs):
    return sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)


def decimate(objs, ratio):
    for obj in objs:
        mod = obj.modifiers.new(name="prepare_decimate", type="DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = ratio
        depsgraph = bpy.context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                              depsgraph=depsgraph)
        old = obj.data
        obj.modifiers.remove(mod)
        obj.data = new
        bpy.data.meshes.remove(old)
        new.name = obj.name


def export(out, normals, draco):
    export_glb(out, {
        "export_normals": normals,
        "export_texcoords": False,
        "export_tangents": False,
        "export_vertex_color": "NONE",
        "export_attributes": False,
        "export_animations": False,
        "export_skins": False,
        "export_morph": False,
        "use_active_scene": True,
        "export_draco_mesh_compression_enable": draco,
        "export_draco_mesh_compression_level": 6,
        "export_draco_position_quantization": 14,   # ~1 cm on a 150 m building
        "export_draco_normal_quantization": 10,
    })
    return os.path.getsize(out)


def main():
    try:
        args = parse_args(script_args())
    except SystemExit as e:
        return 2 if e.code else 0
    rules, errors, warnings = gp.load_rules(args.rules) if os.path.exists(args.rules) else (
        None, [f"{args.rules}: no such file"], [])
    for w in warnings:
        log(f"WARNING {w}")
    if errors:
        for e in errors:
            log(f"ERROR {e}")
        return 1
    if not os.path.exists(args.source):
        log(f"ERROR {args.source}: no such file")
        return 1
    cap = int(args.max_mb * 1024 * 1024)

    log(f"Blender {bpy.app.version_string}")
    load_source(os.path.abspath(args.source))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = [o for o in bpy.context.view_layer.objects if o.type in MESHLIKE and not o.hide_render]
    instancers = [o.name for o in bpy.context.view_layer.objects if o.instance_type == "COLLECTION"]
    if instancers:
        log(f"WARNING {len(instancers)} collection instances are skipped (make them real first): "
            + ", ".join(instancers[:5]))
    by_name = {o.name: o for o in objects}
    collections = {c.name: [o.name for o in c.all_objects] for c in bpy.data.collections}
    groups, unmatched, warnings = gp.assign_objects(list(by_name), collections, rules)
    for w in warnings:
        log(f"WARNING {w}")
    if unmatched:
        verb = "dropped" if args.drop_unmatched else "kept as their own nodes"
        log(f"WARNING {len(unmatched)} objects match no rule, {verb}: " + ", ".join(unmatched[:8])
            + (" …" if len(unmatched) > 8 else ""))
        if not args.drop_unmatched:
            for name in unmatched:
                groups[name if name not in groups else f"{name}_obj"] = [name]
    if not groups:
        log("ERROR nothing to export")
        return 1

    palette = Palette(rules)
    meshes = {node: merged_mesh(node, [by_name[n] for n in names], depsgraph, palette, args)
              for node, names in groups.items()}
    for node, source in palette.fallbacks:
        log(f"colour of {node} ← rules ({source}: no Principled BSDF colour to read)")

    for obj in list(bpy.data.objects):  # the sources, cameras, lights, empties
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    new_objects = []
    for node, mesh in meshes.items():
        obj = bpy.data.objects.new(node, mesh)
        scene.collection.objects.link(obj)
        for key, value in gp.node_extras(node).items():
            obj[key] = value  # exported as glTF extras
        new_objects.append(obj)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    normals, draco = True, args.draco == "on"
    size = export(out, normals, draco)
    log(f"export: {size / 1048576:.2f} MB ({triangles(new_objects)} triangles, cap {args.max_mb:g} MB)")
    if size > cap and not args.keep_normals:
        normals = False
        size = export(out, normals, draco)
        log(f"without normals (flat shading): {size / 1048576:.2f} MB")
    if size > cap and args.draco == "auto":
        draco = True
        size = export(out, normals, draco)
        log(f"with Draco: {size / 1048576:.2f} MB")
    for _ in range(MAX_DECIMATE_ROUNDS):
        if size <= cap:
            break
        ratio = gp.plan_ratio(size, cap)
        before = triangles(new_objects)
        decimate(new_objects, ratio)
        after = triangles(new_objects)
        size = export(out, normals, draco)
        log(f"decimate ×{ratio:.2f}: {before} → {after} triangles, {size / 1048576:.2f} MB")
        if after >= before:
            break

    gltf, _ = gp.read_glb(out)
    log("\n" + gp.format_report(gp.summarize_glb(gltf, size)))
    if size > cap:
        log(f"ERROR {out} is {size / 1048576:.2f} MB, still over the cap of {args.max_mb:g} MB")
        return 3
    log(f"OK {out}")
    return 0


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
