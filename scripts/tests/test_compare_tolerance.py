"""Tests for the numeric tolerance in scripts/compare.py.

Run:  python3 -m unittest discover -s plugins/code-modernization/scripts/tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import compare as cmp  # noqa: E402

TOL = {"rel": 1e-9, "abs": 0, "why": "last-digit rounding of exp() between libm versions"}


class ToleranceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def case(self, name, legacy, new, **extra):
        for side, data in (("legacy", legacy), ("new", new)):
            os.makedirs(os.path.join(self.tmp, side), exist_ok=True)
            with open(os.path.join(self.tmp, side, name), "wb") as fh:
                fh.write(data)
        return {"id": name, "legacy": "legacy/" + name, "new": "new/" + name, **extra}

    def run_cases(self, cases, **top):
        path = os.path.join(self.tmp, "cases.json")
        with open(path, "w") as fh:
            json.dump({"system": "s", "cases": cases, **top}, fh)
        return cmp.run(path, os.path.join(self.tmp, "EQUIVALENCE.json"))

    def test_a_tiny_float_difference_is_same_within_the_declared_tolerance_and_says_so(self):
        res = self.run_cases([self.case("a", b"total 1234.5678901234\nrate 0.05\n", b"total 1234.5678901239\nrate 0.05\n", tolerance=TOL)])
        rec = res["cases"][0]
        self.assertEqual(rec["verdict"], "same")
        self.assertEqual(rec["withinTolerance"]["differing"], 1)
        self.assertLess(rec["withinTolerance"]["maxRelativeDifference"], 1e-9)
        self.assertIn("declared tolerance", rec["reason"])
        self.assertIn("libm", rec["reason"])
        self.assertEqual(res["totals"]["sameWithinTolerance"], 1)
        self.assertIsNone(cmp.verdict_of(res))
        self.assertTrue(res["selfCheck"]["passed"], res["selfCheck"])

    def test_without_a_tolerance_the_same_outputs_differ_and_no_new_key_appears(self):
        res = self.run_cases([self.case("a", b"1234.5678901234\n", b"1234.5678901239\n")])
        self.assertEqual(res["cases"][0]["verdict"], "differs")
        self.assertNotIn("sameWithinTolerance", res["totals"])

    def test_a_difference_outside_the_tolerance_differs(self):
        res = self.run_cases([self.case("a", b"total 100.0\n", b"total 100.5\n", tolerance=TOL)])
        rec = res["cases"][0]
        self.assertEqual(rec["verdict"], "differs")
        self.assertIn("beyond the declared tolerance", rec["reason"])
        self.assertIn("NOT PROVEN" if cmp.verdict_of(res) else "", "NOT PROVEN")

    def test_integers_and_text_must_match_exactly_even_with_a_tolerance(self):
        loose = {"rel": 0.01, "abs": 0, "why": "test"}
        for legacy, new in ((b"count 1000000\n", b"count 1000001\n"), (b"name alpha 1.5\n", b"name alphb 1.5\n"),
                            (b"1.5 2.5\n", b"1.5\n"), (b"x 10\n", b"x 10.0\n")):
            res = self.run_cases([self.case("a", legacy, new, tolerance=loose)])
            self.assertEqual(res["cases"][0]["verdict"], "differs", (legacy, new))

    def test_exponent_forms_compare_by_value(self):
        res = self.run_cases([self.case("a", b"v 1.5e3\n", b"v 1500.0000000000002\n", tolerance=TOL)])
        self.assertEqual(res["cases"][0]["verdict"], "same")

    def test_a_tolerance_needs_a_reason_and_a_sane_size(self):
        legacy = self.case("a", b"1.0\n", b"1.0\n")
        for bad in ({"rel": 1e-9}, {"rel": 1e-9, "why": "  "}, {"rel": 0.5, "why": "x"}, {"why": "x"}, {"rel": -1, "why": "x"},
                    {"rel": "big", "why": "x"}, {"rel": float("nan"), "why": "x"}, "1e-9"):
            with self.assertRaises(cmp.InputError, msg=repr(bad)):
                self.run_cases([dict(legacy, tolerance=bad)])

    def test_a_default_tolerance_applies_to_every_case_and_a_case_can_switch_it_off(self):
        a = self.case("a", b"1.00000000000\n", b"1.00000000001\n")
        b = self.case("b", b"1.00000000000\n", b"1.00000000001\n", tolerance=None)
        res = self.run_cases([a, b], tolerance=TOL)
        self.assertEqual([r["verdict"] for r in res["cases"]], ["same", "differs"])

    def test_the_self_check_fails_when_the_tolerance_would_hide_any_change(self):
        # every byte is a tolerated float digit and the tolerance is 1%: a one-byte change to a low digit is invisible,
        # but the leading-digit change must still be caught, so the check passes here and the outputs still compare
        res = self.run_cases([self.case("a", b"5.5\n", b"5.5\n", tolerance={"abs": 100, "why": "absurdly loose"})])
        self.assertFalse(res["selfCheck"]["passed"])
        self.assertIn("tolerance may be too loose", res["selfCheck"]["detail"])
        self.assertIn("self-check failed", cmp.verdict_of(res))

    def test_masks_and_tolerance_work_together(self):
        res = self.run_cases([self.case("a", b"at 2026-09-24 10:00:00 value 2.0000000001\n", b"at 2027-01-01 11:11:11 value 2.0000000002\n",
                                        mask=[{"regex": r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", "why": "run time"}], tolerance=TOL)])
        self.assertEqual(res["cases"][0]["verdict"], "same")

    def test_large_outputs_are_not_tolerance_compared(self):
        big = b"1.0 " * (cmp.MAX_TOLERANT_BYTES // 4 + 10)
        rec = self.run_cases([self.case("a", big, big[:-3] + b"2.0", tolerance=TOL)])["cases"][0]
        self.assertEqual(rec["verdict"], "differs")


if __name__ == "__main__":
    unittest.main()
