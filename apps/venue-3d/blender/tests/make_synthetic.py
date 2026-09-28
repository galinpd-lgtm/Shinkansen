"""A made-up, heavy .blend for testing prepare_glb.py — no real building.

    python3 blender/tests/make_synthetic.py -- out.blend        # with the bpy module from PyPI
    blender -b --python blender/tests/make_synthetic.py -- out.blend

Three levels in collections ("Level 0.00", …), each with walls, columns and a slab; a dome roof; a lamp
post no rule claims; a camera and a light. Built to be awkward the way exported CAD models are:
  - far too many vertices on flat faces (subdivided walls and slabs) and every face with its own
    vertices (split edges) — welding and planar dissolve must win this back without changing the shape;
  - a dense curved roof that cannot be dissolved;
  - procedural materials: a noise texture into Base Color (nothing to read → the colour from the rules),
    a Color Ramp and a Mix of two RGB nodes (read through), a plain Principled (read directly),
    a Diffuse BSDF without Principled (→ rules), and UV maps everywhere.
"""
import math
import os
import sys

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Matrix  # noqa: E402

LEVELS = (0.0, 4.0, 8.0)
RADIUS = 30.0


def script_args():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def principled(mat):
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True  # older versions; newer ones always have nodes
    tree = mat.node_tree
    bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    return tree, bsdf


def materials():
    concrete = bpy.data.materials.new("Concrete")
    _, bsdf = principled(concrete)
    bsdf.inputs["Base Color"].default_value = (0.50, 0.50, 0.52, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.9

    brick = bpy.data.materials.new("Brick_procedural")
    tree, bsdf = principled(brick)
    noise = tree.nodes.new("ShaderNodeTexNoise")
    tree.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])

    glass = bpy.data.materials.new("Glass_ramp")
    tree, bsdf = principled(glass)
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.2, 0.4, 0.6, 1.0)
    ramp.color_ramp.elements[1].color = (0.4, 0.6, 0.8, 1.0)
    tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.1

    tiles = bpy.data.materials.new("RoofTiles_mix")
    tree, bsdf = principled(tiles)
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    a, b = tree.nodes.new("ShaderNodeRGB"), tree.nodes.new("ShaderNodeRGB")
    a.outputs[0].default_value = (0.6, 0.1, 0.1, 1.0)
    b.outputs[0].default_value = (0.2, 0.1, 0.1, 1.0)
    col_in = [s for s in mix.inputs if s.type == "RGBA"]
    tree.links.new(a.outputs[0], col_in[0])
    tree.links.new(b.outputs[0], col_in[1])
    col_out = next(s for s in mix.outputs if s.type == "RGBA")
    tree.links.new(col_out, bsdf.inputs["Base Color"])

    steel = bpy.data.materials.new("Steel_diffuse")
    tree, bsdf = principled(steel)
    tree.nodes.remove(bsdf)
    diffuse = tree.nodes.new("ShaderNodeBsdfDiffuse")
    out = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
    tree.links.new(diffuse.outputs[0], out.inputs["Surface"])
    return {"concrete": concrete, "brick": brick, "glass": glass, "tiles": tiles, "steel": steel}


def new_bm():
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    return bm


def finish(name, bm, collection, mats, split=False):
    """bm → object; with split=True every face gets its own vertices (like a CAD export)."""
    if split:
        bmesh.ops.split_edges(bm, edges=bm.edges[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for m in mats:
        mesh.materials.append(m)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def wall_ring(bm, z, height, segments=24, cuts=10, thickness=0.4):
    """Flat wall panels around a circle, each heavily subdivided (many vertices, all coplanar)."""
    for i in range(segments):
        a0, a1 = 2 * math.pi * i / segments, 2 * math.pi * (i + 1) / segments
        res = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
        verts = res["verts"]
        length = 2 * RADIUS * math.sin(math.pi / segments)
        mid = (a0 + a1) / 2
        for v in verts:
            x, y, zz = v.co
            v.co = (x * length, y * thickness, (zz + 0.5) * height)
        bmesh.ops.rotate(bm, verts=verts, cent=(0, 0, 0),
                         matrix=Matrix.Rotation(mid + math.pi / 2, 3, "Z"))
        bmesh.ops.translate(bm, verts=verts, vec=(RADIUS * math.cos(mid), RADIUS * math.sin(mid), z))
        edges = list({e for v in verts for e in v.link_edges})
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True)


def columns(bm, z, height, count=16, segments=32):
    for i in range(count):
        a = 2 * math.pi * i / count
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=0.35, radius2=0.35,
                                    depth=height, calc_uvs=True)
        bmesh.ops.translate(bm, verts=res["verts"],
                            vec=((RADIUS - 3) * math.cos(a), (RADIUS - 3) * math.sin(a), z + height / 2))


def slab(bm, z, cuts=40):
    res = bmesh.ops.create_grid(bm, x_segments=cuts, y_segments=cuts, size=RADIUS, calc_uvs=True)
    bmesh.ops.translate(bm, verts=res["verts"], vec=(0, 0, z))


def dome(bm, z, u=192, v=96):
    res = bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=RADIUS + 1, calc_uvs=True)
    bmesh.ops.delete(bm, geom=[x for x in res["verts"] if x.co.z < -0.01], context="VERTS")
    bmesh.ops.scale(bm, vec=(1, 1, 0.35), verts=bm.verts[:])
    bmesh.ops.translate(bm, verts=bm.verts[:], vec=(0, 0, z))


def main():
    args = script_args()
    if len(args) != 1:
        print("usage: make_synthetic.py -- out.blend")
        return 2
    out = os.path.abspath(args[0])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    m = materials()
    for z in LEVELS:
        coll = bpy.data.collections.new(f"Level {z:.2f}")
        scene.collection.children.link(coll)
        bm = new_bm()
        wall_ring(bm, z, 4.0)
        finish(f"walls_{z:.2f}", bm, coll, [m["brick"]], split=True)
        bm = new_bm()
        columns(bm, z, 4.0)
        finish(f"columns_{z:.2f}", bm, coll, [m["concrete"]])
        bm = new_bm()
        slab(bm, z)
        finish(f"slab_{z:.2f}", bm, coll, [m["concrete"]], split=True)
        bm = new_bm()
        res = bmesh.ops.create_grid(bm, x_segments=20, y_segments=4, size=6, calc_uvs=True)
        bmesh.ops.rotate(bm, verts=res["verts"], cent=(0, 0, 0),
                         matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
        bmesh.ops.translate(bm, verts=res["verts"], vec=(0, -RADIUS - 0.3, z + 2))
        finish(f"glazing_{z:.2f}", bm, coll, [m["glass"]])
    bm = new_bm()
    dome(bm, LEVELS[-1] + 4.0)
    finish("roof", bm, scene.collection, [m["tiles"]])
    bm = new_bm()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.15, radius2=0.1, depth=6, calc_uvs=True)
    bmesh.ops.translate(bm, verts=bm.verts[:], vec=(RADIUS + 12, 0, 3))
    finish("lamp_post", bm, scene.collection, [m["steel"]])
    # things the web model does not need
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(cam)
    lamp = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    scene.collection.objects.link(lamp)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    verts = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
    print(f"[make_synthetic] OK {out} ({verts} vertices)")
    return 0


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
