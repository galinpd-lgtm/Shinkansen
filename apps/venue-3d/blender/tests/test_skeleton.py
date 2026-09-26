"""Tests for skeleton validation and geometry — no Blender needed.

    cd apps/venue-3d && python3 -m unittest discover -s blender/tests -v
"""
import copy
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import venue_geometry as vg  # noqa: E402

EXAMPLE = vg.load(os.path.join(os.path.dirname(HERE), "skeleton.example.json"))


def errors_of(sk):
    return vg.validate(sk)[0]


class Example(unittest.TestCase):
    def test_example_is_valid(self):
        errors, warnings = vg.validate(EXAMPLE)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_node_names(self):
        parts, cutters = vg.build_parts(EXAMPLE)
        names = [p["name"] for p in parts]
        self.assertEqual(names[:5], ["level_0", "level_1", "level_2", "ring", "roof"])
        self.assertEqual([n for n in names if n.startswith("pylon_")], [f"pylon_{i:02d}" for i in range(1, 13)])
        self.assertIn("wing_west", names)
        self.assertEqual(sorted(n for n in names if n.startswith("entrance_")),
                         sorted(f"entrance_{e['id']}" for e in EXAMPLE["entrances"]))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(cutters), len(EXAMPLE["entrances"]))

    def test_every_mesh_is_closed_and_outward(self):
        parts, cutters = vg.build_parts(EXAMPLE)
        for p in parts + cutters:
            with self.subTest(p["name"]):
                self.assertTrue(vg.is_closed_manifold(p["verts"], p["faces"]))
                self.assertGreater(vg.signed_volume(p["verts"], p["faces"]), 0)


class Geometry(unittest.TestCase):
    def test_cylinder_volume(self):
        n = 64
        v, f = vg.cylinder(10, 0, 5, n)
        polygon_area = 0.5 * n * 100 * math.sin(2 * math.pi / n)
        self.assertAlmostEqual(vg.signed_volume(v, f), polygon_area * 5, places=6)

    def test_ring_volume_is_outer_minus_inner(self):
        n = 48
        full = vg.signed_volume(*vg.cylinder(12, 0, 3, n))
        hole = vg.signed_volume(*vg.cylinder(8, 0, 3, n))
        self.assertAlmostEqual(vg.signed_volume(*vg.ring(8, 12, 0, 3, n)), full - hole, places=6)

    def test_box_rotation_is_a_compass_bearing(self):
        # a box 2 m wide, 10 m deep, turned to face east: its long side runs east-west
        v, f = vg.box(0, 0, 0, 2, 10, 1, 90)
        xs, ys = [p[0] for p in v], [p[1] for p in v]
        self.assertAlmostEqual(max(xs) - min(xs), 10)
        self.assertAlmostEqual(max(ys) - min(ys), 2)
        self.assertAlmostEqual(vg.signed_volume(v, f), 20)

    def test_bearing_point(self):
        for bearing, want in ((90, (10, 0)), (0, (0, 10)), (180, (0, -10)), (270, (-10, 0))):
            x, y = vg.bearing_point(10, bearing)
            self.assertAlmostEqual(x, want[0])
            self.assertAlmostEqual(y, want[1])

    def test_frustum_volume_and_lean(self):
        n = 64
        v, f = vg.frustum(10, 12, 0, 6, n)
        self.assertTrue(vg.is_closed_manifold(v, f))
        k = 0.5 * n * math.sin(2 * math.pi / n)  # area of the n-gon over r²
        self.assertAlmostEqual(vg.signed_volume(v, f), k * 6 / 3 * (100 + 120 + 144), places=6)

    def test_levels_follow_the_leaning_drum(self):
        parts = {p["name"]: p for p in vg.build_parts(EXAMPLE)[0]}
        def radius(name, z):
            return max(math.hypot(x, y) for x, y, zz in parts[name]["verts"] if abs(zz - z) < 1e-9)
        self.assertAlmostEqual(radius("level_0", 0), 40)
        self.assertAlmostEqual(radius("level_0", 6), 41)
        self.assertAlmostEqual(radius("level_2", 18), 43)

    def test_saddle_roof(self):
        roof = next(p for p in vg.build_parts(EXAMPLE)[0] if p["name"] == "roof")
        v, f = roof["verts"], roof["faces"]
        self.assertTrue(vg.is_closed_manifold(v, f))
        self.assertGreater(vg.signed_volume(v, f), 0)
        spec, top = EXAMPLE["roof"], EXAMPLE["drum"]["height"]
        eave = EXAMPLE["drum"]["top_radius"] + spec["overhang"]
        def z_at(x, y):
            return max(p[2] for p in v if abs(p[0] - x) < 1e-6 and abs(p[1] - y) < 1e-6)
        self.assertAlmostEqual(z_at(eave, 0), top + spec["edge_height_x"])   # високият ръб по X
        self.assertAlmostEqual(z_at(0, eave), top + spec["edge_height_y"])   # ниският ръб по Y
        self.assertAlmostEqual(z_at(0, 0), top + spec["center_height"])
        self.assertAlmostEqual(max(math.hypot(p[0], p[1]) for p in v), eave)
        self.assertAlmostEqual(min(p[2] for p in v), top)                    # пълнежът стъпва на стената

    def test_saddle_height_formula(self):
        self.assertEqual(vg.saddle_height(0, 0, 10, 12, 3, 7), 7)
        self.assertEqual(vg.saddle_height(10, 0, 10, 12, 3, 7), 12)
        self.assertEqual(vg.saddle_height(0, -10, 10, 12, 3, 7), 3)

    def test_roof_types(self):
        for t in ("dome", "flat", "cone"):
            sk = copy.deepcopy(EXAMPLE)
            sk["roof"] = {"type": t, "height": 9, "overhang": 1.5}
            roof = next(p for p in vg.build_parts(sk)[0] if p["name"] == "roof")
            with self.subTest(t):
                self.assertTrue(vg.is_closed_manifold(roof["verts"], roof["faces"]))
                self.assertAlmostEqual(min(z for _, _, z in roof["verts"]), EXAMPLE["drum"]["height"])

    def test_pylons_start_angle(self):
        parts = vg.build_parts(EXAMPLE)[0]
        p1 = next(p for p in parts if p["name"] == "pylon_01")
        cx = sum(v[0] for v in p1["verts"]) / 8
        cy = sum(v[1] for v in p1["verts"]) / 8
        self.assertAlmostEqual(math.degrees(math.atan2(cx, cy)), 15, places=6)
        self.assertAlmostEqual(math.hypot(cx, cy), 52, places=6)

    def test_entrance_canopy_sits_at_its_level(self):
        sk = copy.deepcopy(EXAMPLE)
        sk["entrances"][0]["level"] = "level_1"
        sk["entrances"][0]["height"] = 4
        canopy = next(p for p in vg.build_parts(sk)[0] if p["name"] == "entrance_north")
        self.assertAlmostEqual(min(z for _, _, z in canopy["verts"]), 6 + 4)


class Validation(unittest.TestCase):
    def mutate(self, fn):
        sk = copy.deepcopy(EXAMPLE)
        fn(sk)
        return errors_of(sk)

    def assert_error(self, fn, needle):
        errs = self.mutate(fn)
        self.assertTrue(any(needle in e for e in errs), errs)

    def test_not_an_object(self):
        self.assertEqual(errors_of([]), ["skeleton: must be a JSON object"])

    def test_missing_drum(self):
        self.assert_error(lambda s: s.pop("drum"), "drum: required")

    def test_negative_and_non_numeric(self):
        self.assert_error(lambda s: s["drum"].update(radius=-3), "drum.radius: must be > 0")
        self.assert_error(lambda s: s["drum"].update(height="18"), "drum.height: must be a number")
        self.assert_error(lambda s: s["drum"].update(height=True), "drum.height: must be a number")

    def test_ring_radii(self):
        self.assert_error(lambda s: s["ring"].update(outer_radius=30), "greater than inner_radius")

    def test_levels_overlap_and_top(self):
        self.assert_error(lambda s: s["levels"][1].update(z=5), "overlaps")
        self.assert_error(lambda s: s["levels"][2].update(height=10), "above drum.height")

    def test_level_gap_is_a_warning(self):
        sk = copy.deepcopy(EXAMPLE)
        sk["levels"][1]["z"] = 6.5
        sk["levels"][1]["height"] = 5.5
        errors, warnings = vg.validate(sk)
        self.assertEqual(errors, [])
        self.assertTrue(any("gap" in w for w in warnings))

    def test_roof_type(self):
        self.assert_error(lambda s: s["roof"].update(type="pyramid"), "roof.type")

    def test_saddle_fields(self):
        self.assert_error(lambda s: s["roof"].pop("edge_height_x"), "roof.edge_height_x: required")
        self.assert_error(lambda s: s["roof"].update(center_height=-1), "roof.center_height: must be >= 0")
        self.assert_error(lambda s: s["roof"].update(eave_radius=40), "inside the wall top")
        self.assert_error(lambda s: s["roof"].update(eave_radius=50), "disagree")
        ok = copy.deepcopy(EXAMPLE)
        ok["roof"]["eave_radius"] = 46
        self.assertEqual(errors_of(ok), [])

    def test_saddle_that_is_a_bowl_warns(self):
        sk = copy.deepcopy(EXAMPLE)
        sk["roof"].update(edge_height_x=10, edge_height_y=8, center_height=2)
        errors, warnings = vg.validate(sk)
        self.assertEqual(errors, [])
        self.assertTrue(any("not a saddle" in w for w in warnings))

    def test_drum_top_radius(self):
        self.assert_error(lambda s: s["drum"].update(top_radius=0), "drum.top_radius: must be > 0")

    def test_pylon_count(self):
        self.assert_error(lambda s: s["pylons"].update(count=2.5), "pylons.count")

    def test_ids(self):
        self.assert_error(lambda s: s["entrances"][1].update(id="north"), "duplicate 'north'")
        self.assert_error(lambda s: s["entrances"][0].update(id="Главен вход"), "[a-z0-9_]")
        self.assert_error(lambda s: s["wings"][0].update(id="level_0"), "ids used twice")

    def test_entrance_angle_or_position(self):
        self.assert_error(lambda s: s["entrances"][0].update(position=[1, 2]), "exactly one of")
        self.assert_error(lambda s: s["entrances"][0].pop("angle_deg"), "exactly one of")
        self.assert_error(lambda s: s["entrances"][4].pop("facing_deg"), "facing_deg: required")
        self.assert_error(lambda s: s["entrances"][4].update(position=[1]), "position: must be [x, y]")

    def test_entrance_level(self):
        self.assert_error(lambda s: s["entrances"][0].update(level="level_9"), "level: must be one of")
        self.assert_error(lambda s: s["entrances"][0].update(height=7), "taller than its level")

    def test_optional_parts_may_be_missing(self):
        sk = copy.deepcopy(EXAMPLE)
        for k in ("ring", "pylons", "roof", "wings", "entrances"):
            sk.pop(k)
        self.assertEqual(errors_of(sk), [])
        names = [p["name"] for p in vg.build_parts(sk)[0]]
        self.assertEqual(names, ["level_0", "level_1", "level_2"])


SUMMARY = os.path.join(os.path.dirname(os.path.dirname(HERE)), "core", "tests", "fixtures", "parts.summary.json")


class CrossCheck(unittest.TestCase):
    """core/tests/fixtures/parts.summary.json must match this geometry; the JS tests check their port against it.
    After a geometry change: python3 blender/tests/test_skeleton.py --write-summary"""

    def test_summary_is_current(self):
        with open(SUMMARY, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), vg.summary(vg.build_parts(EXAMPLE)[0]))


class Cli(unittest.TestCase):
    def test_main(self):
        path = os.path.join(os.path.dirname(HERE), "skeleton.example.json")
        self.assertEqual(vg.main([path]), 0)
        self.assertEqual(vg.main([]), 2)
        self.assertEqual(vg.main([path + ".missing"]), 1)


if __name__ == "__main__":
    if "--write-summary" in sys.argv:
        with open(SUMMARY, "w", encoding="utf-8") as fh:
            json.dump(vg.summary(vg.build_parts(EXAMPLE)[0]), fh, indent=1)
            fh.write("\n")
        print(f"wrote {SUMMARY}")
    else:
        unittest.main()
