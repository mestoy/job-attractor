"""Kit issue #145: scripts/new_card.py called kit_config.panel_seats() with no guard, so a partner whose OWN kit_config.py predates that function
(the file is personal and an update never overwrites it) crashed with AttributeError while scaffolding a card. It now asks with getattr and falls
back to the shipped CPO/CTO/CEO panel, and it also survives a panel_seats that raises or returns nonsense. Fixtures are fictional."""
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)


def load_new_card():
    spec = importlib.util.spec_from_file_location("new_card_under_test", os.path.join(SCRIPTS, "new_card.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def panel_section(md):
    return md.split("## 11. Panel")[1].split("\n## ")[0]


class OldKitConfig(unittest.TestCase):
    def setUp(self):
        self.nc = load_new_card()

    def with_config(self, **attrs):
        self.nc.kit_config = types.SimpleNamespace(**attrs)

    def test_a_kit_config_with_no_panel_seats_no_longer_crashes_and_gets_the_shipped_panel(self):
        self.with_config()      # an older, personal kit_config: no panel_seats at all
        md = self.nc.render_skeleton("Acme Corp", {}, {}, today="2026-09-21")
        sec = panel_section(md)
        for seat in ("CPO", "CTO", "CEO"):
            self.assertIn("- **%s __**" % seat, sec)
        self.assertNotIn("optional seat", sec)

    def test_the_fallback_is_exactly_the_shipped_default_panel(self):
        real = load_new_card()
        import kit_config
        saved = kit_config.PANEL_SEATS
        kit_config.PANEL_SEATS = []
        try:
            shipped = kit_config.panel_seats()
        finally:
            kit_config.PANEL_SEATS = saved
        self.with_config()
        self.assertEqual(self.nc._panel_seats(), shipped)

    def test_a_panel_seats_that_raises_falls_back_instead_of_crashing(self):
        def boom():
            raise RuntimeError("partner's own edit is broken")
        self.with_config(panel_seats=boom)
        md = self.nc.render_skeleton("Acme Corp", {}, {}, today="2026-09-21")
        self.assertIn("- **CEO __**", panel_section(md))

    def test_a_panel_seats_that_returns_nonsense_falls_back(self):
        for bad in (None, "CPO,CTO", [], [{}], [{"name": ""}], 7, [("CPO", 1)]):
            with self.subTest(bad=bad):
                self.with_config(panel_seats=lambda b=bad: b)
                self.assertEqual([s["name"] for s in self.nc._panel_seats()], ["CPO", "CTO", "CEO"])

    def test_a_configured_panel_is_still_honored_including_an_optional_seat(self):
        seats = [{"name": "CPO", "weight": 1.0, "optional": False}, {"name": "Delivery", "weight": 1.0, "optional": True}]
        self.with_config(panel_seats=lambda: seats)
        sec = panel_section(self.nc.render_skeleton("Acme Corp", {}, {}, today="2026-09-21"))
        self.assertIn("- **CPO __**", sec)
        self.assertIn("- **Delivery __** — OWED: the sentence that produced this number. (optional seat, a preference and not a gate)", sec)
        self.assertNotIn("CTO", sec)

    def test_a_seat_that_carries_only_a_name_renders_and_is_not_optional(self):
        """A partner's own panel_seats may return bare {"name": ...} dicts: no KeyError on the missing optional flag."""
        self.with_config(panel_seats=lambda: [{"name": "CPO"}, {"name": "Taste"}])
        sec = panel_section(self.nc.render_skeleton("Acme Corp", {}, {}, today="2026-09-21"))
        self.assertIn("- **Taste __** — OWED: the sentence that produced this number.", sec)
        self.assertNotIn("optional seat", sec)

    def test_the_real_kit_config_still_works_unchanged(self):
        nc = load_new_card()
        sec = panel_section(nc.render_skeleton("Acme Corp", {}, {}, today="2026-09-21"))
        self.assertIn("- **CPO __**", sec)

    def test_no_other_call_in_new_card_reaches_into_kit_config_unguarded(self):
        """The same hole could sit elsewhere: every kit_config attribute new_card.py uses must be reached through getattr or be a name every
        kit_config has always had."""
        import ast
        tree = ast.parse(open(os.path.join(SCRIPTS, "new_card.py"), encoding="utf-8").read())
        bare = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "kit_config"]
        self.assertEqual(bare, [], "unguarded kit_config access: %s" % bare)


if __name__ == "__main__":
    unittest.main()
