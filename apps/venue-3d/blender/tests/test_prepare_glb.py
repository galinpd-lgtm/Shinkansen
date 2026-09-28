"""Tests for prepare_glb.py — the rules, colours and GLB reader without Blender; the whole run with it.

    cd apps/venue-3d && python3 -m unittest discover -s blender/tests -v

The end-to-end tests run only where Blender is at hand: the `bpy` module in this Python
(`pip install bpy==5.0.1`) or a Blender binary in $BLENDER. Otherwise they are skipped, and the
committed fixture fixtures/synthetic.prepared.glb (made by the same scripts, command below) is checked.

    python3 blender/tests/make_synthetic.py -- /tmp/synthetic.blend
    python3 blender/prepare_glb.py -- /tmp/synthetic.blend blender/tests/fixtures/synthetic.rules.json \
        blender/tests/fixtures/synthetic.prepared.glb --max-mb 0.3 --draco off
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BLENDER_DIR = os.path.dirname(HERE)
sys.path.insert(0, BLENDER_DIR)
import glb_prep as gp  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
RULES = os.path.join(FIXTURES, "synthetic.rules.json")
PREPARED = os.path.join(FIXTURES, "synthetic.prepared.glb")
PREPARED_CAP_MB = 0.3
MB = 1024 * 1024


# ------------------------------------------------------------------ fakes for Blender shader nodes

class Sock:
    def __init__(self, name, value=None, links=None, type="RGBA"):
        self.name, self.default_value, self.links, self.type = name, value, links or [], type
        self.is_linked = bool(self.links)


class Link:
    def __init__(self, from_node):
        self.from_node = from_node


class Node:
    def __init__(self, type, inputs=(), outputs=(), color_ramp=None):
        self.type, self.inputs, self.outputs, self.color_ramp = type, list(inputs), list(outputs), color_ramp


class Stop:
    def __init__(self, color):
        self.color = color


class Ramp:
    def __init__(self, *colors):
        self.elements = [Stop(c) for c in colors]


def material(base_color_socket, roughness=0.6):
    bsdf = Node("BSDF_PRINCIPLED", [base_color_socket, Sock("Roughness", roughness, type="VALUE")])
    return type("Mat", (), {"node_tree": type("Tree", (), {"nodes": [Node("OUTPUT_MATERIAL"), bsdf]})()})()


def linked(node):
    return Sock("Base Color", (1, 1, 1, 1), [Link(node)])


def rgb(*c):
    return Node("RGB", outputs=[Sock("Color", (*c, 1.0), [Link(None)])])


# ------------------------------------------------------------------ without Blender

class Colors(unittest.TestCase):
    def test_hex_is_srgb_list_is_linear(self):
        self.assertEqual(gp.parse_color("#ffffff"), (1.0, 1.0, 1.0))
        r, g, b = gp.parse_color("#808080")
        self.assertAlmostEqual(r, 0.2158605, places=5)  # sRGB 128 → linear
        self.assertEqual(gp.parse_color([0.2, 0.3, 0.4]), (0.2, 0.3, 0.4))
        self.assertEqual(gp.parse_color([0.2, 0.3, 0.4, 1]), (0.2, 0.3, 0.4))
        for bad in ("#fff", "red", [1, 2, 3], [0.1, 0.2], True, None, [True, 0, 0]):
            self.assertIsNone(gp.parse_color(bad), bad)

    def test_hex_round_trip(self):
        for h in ("#b9bec6", "#000000", "#ffffff", "#72849b"):
            self.assertEqual(gp.color_hex(gp.parse_color(h)), h)

    def test_principled_base_color_read_directly(self):
        self.assertEqual(gp.material_color(material(Sock("Base Color", (0.5, 0.5, 0.52, 1.0)))), ((0.5, 0.5, 0.52), 0.6))

    def test_simple_procedural_chains_are_followed(self):
        self.assertEqual(gp.material_color(material(linked(rgb(0.1, 0.2, 0.3))))[0], (0.1, 0.2, 0.3))
        ramp = Node("VALTORGB", color_ramp=Ramp((0.2, 0.4, 0.6, 1), (0.4, 0.6, 0.8, 1)))
        self.assertEqual([round(c, 6) for c in gp.material_color(material(linked(ramp)))[0]], [0.3, 0.5, 0.7])
        # the Mix node (3.4+) has float and vector A/B next to the colour ones — the colour ones count
        mix = Node("MIX", inputs=[Sock("Factor", 0.5, type="VALUE"), Sock("A", 0.0, type="VALUE"),
                                  Sock("B", 0.0, type="VALUE"), Sock("A", None, [Link(rgb(0.6, 0.1, 0.1))]),
                                  Sock("B", None, [Link(rgb(0.2, 0.1, 0.1))])])
        self.assertEqual([round(c, 6) for c in gp.material_color(material(linked(mix)))[0]], [0.4, 0.1, 0.1])
        reroute = Node("REROUTE", inputs=[Sock("Input", None, [Link(rgb(0.3, 0.3, 0.3))])])
        self.assertEqual(gp.material_color(material(linked(reroute)))[0], (0.3, 0.3, 0.3))
        invert = Node("INVERT", inputs=[Sock("Fac", 1.0, type="VALUE"), Sock("Color", (0.25, 0.5, 1.0, 1))])
        self.assertEqual(gp.material_color(material(linked(invert)))[0], (0.75, 0.5, 0.0))

    def test_nothing_to_read(self):
        noise = Node("TEX_NOISE", inputs=[Sock("Scale", 5.0, type="VALUE")])
        self.assertEqual(gp.material_color(material(linked(noise)))[0], None)  # → colour from the rules
        diffuse_only = type("Mat", (), {"node_tree": type("T", (), {"nodes": [Node("BSDF_DIFFUSE")]})()})()
        self.assertEqual(gp.material_color(diffuse_only), (None, None))
        self.assertEqual(gp.material_color(type("Mat", (), {"node_tree": None})()), (None, None))
        textured_roughness = material(Sock("Base Color", (0.1, 0.1, 0.1, 1)))
        textured_roughness.node_tree.nodes[1].inputs[1] = Sock("Roughness", 0.5, [Link(noise)], type="VALUE")
        self.assertEqual(gp.material_color(textured_roughness), ((0.1, 0.1, 0.1), None))


class Rules(unittest.TestCase):
    def test_simple_form(self):
        rules, errors, warnings = gp.parse_rules({"level_0": ["walls_0.00", "columns_0.00"], "roof": "Roof"})
        self.assertEqual(errors, [])
        self.assertEqual(rules["nodes"], {"level_0": ["walls_0.00", "columns_0.00"], "roof": ["Roof"]})
        self.assertEqual(rules["colors"], {})
        self.assertEqual(rules["roughness"], gp.DEFAULT_ROUGHNESS)

    def test_extended_form_fixture(self):
        rules, errors, warnings = gp.load_rules(RULES)
        self.assertEqual(errors, [])
        self.assertEqual(list(rules["nodes"]), ["level_0", "level_1", "level_2", "roof"])
        self.assertEqual(gp.color_hex(rules["colors"]["roof"]), "#72849b")
        self.assertTrue(any("lamp_post" in w for w in warnings))  # a colour for an object, not a node

    def test_bad_rules(self):
        self.assertEqual(gp.parse_rules([])[1], ["rules: must be a JSON object"])
        self.assertIsNone(gp.parse_rules({})[0])
        rules, errors, _ = gp.parse_rules({"nodes": {"level 0": ["a"], "ok": [], "roof": ["r"]},
                                           "colors": {"roof": "blue"}, "roughness": 2})
        joined = " | ".join(errors)
        for s in ("nodes.level 0", "nodes.ok", "colors.roof", "roughness"):
            self.assertIn(s, joined)
        self.assertEqual(list(rules["nodes"]), ["roof"])

    def test_assign_by_name_collection_and_glob(self):
        rules, _, _ = gp.load_rules(RULES)
        objects = ["walls_0.00", "columns_0.00", "walls_4.00", "columns_4.00", "slab_4.00", "glazing_4.00",
                   "walls_8.00", "slab_8.00", "roof", "lamp_post"]
        collections = {"Level 0.00": ["walls_0.00", "columns_0.00", "ghost"]}
        groups, unmatched, warnings = gp.assign_objects(objects, collections, rules)
        self.assertEqual(groups["level_0"], ["walls_0.00", "columns_0.00"])   # collection; "ghost" is no mesh
        self.assertEqual(groups["level_1"], ["walls_4.00", "columns_4.00", "slab_4.00", "glazing_4.00"])
        self.assertEqual(groups["level_2"], ["walls_8.00", "slab_8.00"])      # glob *_8.00
        self.assertEqual(groups["roof"], ["roof"])
        self.assertEqual(unmatched, ["lamp_post"])
        self.assertEqual(warnings, [])

    def test_first_rule_wins_and_misses_are_reported(self):
        rules, _, _ = gp.parse_rules({"a": ["x*"], "b": ["x1", "nothing"]})
        groups, unmatched, warnings = gp.assign_objects(["x1", "x2"], {}, rules)
        self.assertEqual(groups, {"a": ["x1", "x2"]})
        self.assertEqual(unmatched, [])
        self.assertTrue(any("claimed by a and b" in w for w in warnings))
        self.assertTrue(any("'nothing'" in w for w in warnings))
        self.assertTrue(any(w.startswith("b: empty") for w in warnings))

    def test_fallback_colour_and_extras(self):
        rules, _, _ = gp.load_rules(RULES)
        self.assertEqual(gp.color_hex(gp.node_color("level_1", rules)), "#a7adb5")
        self.assertEqual(gp.color_hex(gp.node_color("unknown", rules)), gp.DEFAULT_COLOR_SRGB)
        self.assertEqual(gp.node_extras("level_2"), {"level": "level_2"})
        self.assertEqual(gp.node_extras("roof"), {})


class Size(unittest.TestCase):
    def test_plan_ratio(self):
        self.assertEqual(gp.plan_ratio(4 * MB, 5 * MB), 1.0)
        self.assertAlmostEqual(gp.plan_ratio(10 * MB, 5 * MB), 0.46)
        self.assertEqual(gp.plan_ratio(1000 * MB, 5 * MB), 0.02)


class PreparedFixture(unittest.TestCase):
    """The committed output of prepare_glb.py on the synthetic model (see the module docstring)."""

    @classmethod
    def setUpClass(cls):
        with open(PREPARED, "rb") as f:
            cls.data = f.read()
        cls.gltf, cls.bin = gp.read_glb(cls.data)
        cls.summary = gp.summarize_glb(cls.gltf, len(cls.data))
        cls.nodes = {n["name"]: n for n in cls.summary["nodes"]}

    def test_under_the_cap(self):
        self.assertLess(len(self.data), PREPARED_CAP_MB * MB)

    def test_nodes_by_level_with_extras(self):
        self.assertEqual(list(self.nodes), ["level_0", "level_1", "level_2", "roof", "lamp_post"])
        for lv in ("level_0", "level_1", "level_2"):
            self.assertEqual(self.nodes[lv]["extras"], {"level": lv})

    def test_plain_colours_from_blender_and_from_the_rules(self):
        hexes = {name: [gp.color_hex(c["base_color"]) for c in n["colors"]] for name, n in self.nodes.items()}
        # walls: noise texture → the node's colour from the rules; columns/slab: Principled; glazing: Color Ramp
        self.assertEqual(hexes["level_0"], ["#b9bec6", "#bcbcbf", "#95bcda"])
        self.assertEqual(hexes["level_1"][0], "#a7adb5")
        self.assertEqual(hexes["roof"], ["#aa5959"])        # Mix of two RGB nodes, read through
        self.assertEqual(hexes["lamp_post"], ["#3a3f47"])   # Diffuse BSDF only → rules, by object name
        self.assertFalse(any(c["textured"] for n in self.nodes.values() for c in n["colors"]))

    def test_no_uv_no_textures(self):
        self.assertFalse(self.summary["uv"])
        self.assertEqual(self.summary["textures"], 0)
        self.assertNotIn("images", self.gltf)

    def test_reader_rejects_other_files(self):
        with self.assertRaises(ValueError):
            gp.read_glb(b"not a glb at all, not at all")
        with self.assertRaises(ValueError):
            gp.read_glb(self.data[:-4])


# ------------------------------------------------------------------ with Blender

def blender_cmd(script):
    if os.environ.get("BLENDER"):
        return [os.environ["BLENDER"], "-b", "--python", script, "--"]
    if importlib.util.find_spec("bpy") is not None:
        return [sys.executable, script, "--"]
    return None


HAVE_BLENDER = blender_cmd("x") is not None


@unittest.skipUnless(HAVE_BLENDER, "no Blender: install the bpy module (pip install bpy==5.0.1) or set $BLENDER")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.blend = os.path.join(cls.tmp.name, "synthetic.blend")
        cls.run_script(os.path.join(HERE, "make_synthetic.py"), cls.blend)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def run_script(script, *args):
        proc = subprocess.run(blender_cmd(script) + list(args), capture_output=True, text=True, timeout=600)
        return proc.returncode, proc.stdout + proc.stderr

    def prepare(self, name, *options):
        out = os.path.join(self.tmp.name, name)
        code, log = self.run_script(os.path.join(BLENDER_DIR, "prepare_glb.py"), self.blend, RULES, out, *options)
        self.assertEqual(code, 0, log[-3000:])
        with open(out, "rb") as f:
            data = f.read()
        return data, gp.summarize_glb(gp.read_glb(data)[0], len(data)), log

    def test_heavy_model_gets_under_the_cap_without_losing_shape(self):
        data, summary, log = self.prepare("a.glb", "--max-mb", "1")
        self.assertLess(len(data), 1 * MB)
        self.assertIn("welded", log)
        self.assertNotIn("decimate", log)                # welding and dissolving were enough
        self.assertEqual([n["name"] for n in summary["nodes"]], ["level_0", "level_1", "level_2", "roof", "lamp_post"])
        self.assertFalse(summary["uv"])

    def test_draco_when_needed(self):
        data, summary, log = self.prepare("b.glb", "--max-mb", "0.1")
        self.assertLess(len(data), 0.1 * MB)
        self.assertTrue(summary["draco"])
        self.assertNotIn("decimate", log)

    def test_decimation_is_the_last_resort(self):
        data, summary, log = self.prepare("c.glb", "--max-mb", "0.06", "--draco", "off")
        self.assertLess(len(data), 0.06 * MB)
        self.assertIn("decimate", log)
        self.assertFalse(summary["draco"])
        self.assertEqual(gp.color_hex(summary["nodes"][0]["colors"][0]["base_color"]), "#b9bec6")

    def test_bad_rules_stop_before_blender_work(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w") as f:
            f.write('{"nodes": {"level 0": []}}')
        code, log = self.run_script(os.path.join(BLENDER_DIR, "prepare_glb.py"), self.blend, bad,
                                    os.path.join(self.tmp.name, "x.glb"))
        self.assertEqual(code, 1, log)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "x.glb")))


if __name__ == "__main__":
    unittest.main()
