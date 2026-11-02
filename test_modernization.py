import unittest
from copy import deepcopy

from catalog import ensure_catalog
from core import DEFAULT, quote, validate
from pricing import effective, enrich
from quality import LEVELS, resolve
from test_rendering import sample_profile


class ModernizationTests(unittest.TestCase):
    def item(self, n):
        return {
            "selected": list(range(n)),
            "options": {"paper": "A4", "color": "黑白", "duplex": "单面", "copies": 1},
        }

    def test_list_price_then_optional_discounts(self):
        c = deepcopy(DEFAULT)
        r = {
            "paper": "A4",
            "color": "黑白",
            "duplex": "单面",
            "unit": "面",
            "base_price": "0.20",
            "discount_enabled": False,
            "discounts": [[21, "0.15"]],
            "mode": "progressive",
        }
        c["prices"] = [r]
        validate(c)
        self.assertEqual(quote(c, [self.item(25)])["total"], "5.00")
        r["discount_enabled"] = True
        self.assertEqual(quote(c, [self.item(25)])["total"], "4.75")
        r.update(mode="volume", discounts=[[20, "0.15"]])
        self.assertEqual(quote(c, [self.item(25)])["total"], "3.75")
        self.assertEqual(quote(c, [self.item(19)])["total"], "3.80")

    def test_legacy_rates_survive_new_form(self):
        c = deepcopy(DEFAULT)
        old = quote(c, [self.item(25)])["total"]
        c["prices"] = [effective(enrich(r)) for r in c["prices"]]
        self.assertEqual(quote(c, [self.item(25)])["total"], old)

    def test_discount_cannot_exceed_list_price(self):
        c = deepcopy(DEFAULT)
        c["prices"] = [
            dict(
                c["prices"][0],
                base_price="0.20",
                discount_enabled=True,
                discounts=[[20, "0.30"]],
            )
        ]
        with self.assertRaises(ValueError):
            validate(c)

    def test_hp_and_epson_have_independent_quality_bindings(self):
        c = deepcopy(DEFAULT)
        c["native_quality_enabled"] = True
        name = "EPSON L15158"
        standard = dict(sample_profile(), printer=name, name="标准")
        high = dict(sample_profile(), printer=name, name="高")
        rule = {"paper": "A4", "color": "黑白", "duplex": "单面"}
        c["printers"] = [
            {"name": "HP LaserJet Pro M403d", "dpi": [600, 1200], "rules": [rule]},
            {
                "name": name,
                "dpi": [600],
                "rules": [rule],
                "quality_profiles": [standard, high],
            },
        ]
        for level, dpi, profile in [(LEVELS[0], 600, "标准"), (LEVELS[1], 1200, "高")]:
            o = {"quality_level": level, "dpi": 600}
            self.assertEqual(resolve(c, "HP LaserJet Pro M403d", o)["dpi"], dpi)
            self.assertEqual(resolve(c, name, o)["profile"]["name"], profile)
        c["printers"][1]["quality_profiles"] = []
        self.assertIsNone(resolve(c, name, {"quality_level": LEVELS[1]})["profile"])

    def test_removed_background_options_are_discarded(self):
        c = ensure_catalog(
            dict(
                DEFAULT,
                light_background_enabled=True,
                background_choice_initialized=True,
            )
        )
        self.assertNotIn("light_background_enabled", c)
        self.assertNotIn("background_choice_initialized", c)


if __name__ == "__main__":
    unittest.main()
