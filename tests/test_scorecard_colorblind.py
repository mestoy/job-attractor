"""Story S30 (2026-09-10): the scorecard template's good, warn and bad tokens stay readable for
colorblind users in both themes. Parses the tokens out of templates/scorecard/scorecard-template.html
and asserts WCAG AA contrast of state text on its soft background, plus CIE dE separation of every
state pair under protanopia, deuteranopia and tritanopia (Machado 2009 matrices, severity 1.0).
Also asserts every pill and chip class carries a glyph, so state never rides on hue alone.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
TEMPLATE = os.path.join(KIT, "templates", "scorecard", "scorecard-template.html")

MIN_CONTRAST = 4.5
MIN_DE = 20.0
CVD = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb):
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = _lum(_hex(a)), _lum(_hex(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def simulate(h, kind):
    r, g, b = (_lin(c) for c in _hex(h))
    m = CVD[kind]
    return tuple(max(0.0, min(1.0, m[i][0] * r + m[i][1] * g + m[i][2] * b)) for i in range(3))


def lab(rgb):
    r, g, b = rgb
    X = r * 0.4124 + g * 0.3576 + b * 0.1805
    Y = r * 0.2126 + g * 0.7152 + b * 0.0722
    Z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(X / 0.95047), f(Y), f(Z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def de(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def token_blocks(text):
    """Returns {'light': {...}, 'dark': {...}} of --good/--warn/--bad and their -soft values."""
    blocks = {}
    root = re.search(r":root\{(.*?)\}", text, re.S)
    dark = re.search(r':root\[data-theme="dark"\]\{(.*?)\}', text, re.S)
    for name, m in (("light", root), ("dark", dark)):
        assert m, f"{name} token block not found"
        toks = dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})", m.group(1)))
        blocks[name] = toks
    return blocks


class ScorecardColorblindTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE, encoding="utf-8") as f:
            cls.text = f.read()
        cls.blocks = token_blocks(cls.text)

    def test_state_text_meets_aa_on_its_soft_background_in_both_themes(self):
        for theme, t in self.blocks.items():
            for state in ("good", "warn", "bad"):
                c = contrast(t[state], t[state + "-soft"])
                self.assertGreaterEqual(c, MIN_CONTRAST, f"{theme} {state}: {c:.2f}:1")

    def test_every_state_pair_separates_under_each_colorblindness(self):
        for theme, t in self.blocks.items():
            for kind in CVD:
                sim = {s: lab(simulate(t[s], kind)) for s in ("good", "warn", "bad")}
                for a, b in (("good", "bad"), ("good", "warn"), ("warn", "bad")):
                    d = de(sim[a], sim[b])
                    self.assertGreaterEqual(d, MIN_DE, f"{theme} {kind} {a}-{b}: dE {d:.0f}")

    def test_media_dark_block_matches_the_data_theme_dark_block(self):
        media = re.search(r'prefers-color-scheme: dark\)\{\s*:root:not\(\[data-theme="light"\]\)\{(.*?)\}', self.text, re.S)
        self.assertTrue(media)
        toks = dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})", media.group(1)))
        for k in ("good", "good-soft", "warn", "warn-soft", "bad", "bad-soft"):
            self.assertEqual(toks[k], self.blocks["dark"][k], k)

    def test_pills_and_chips_carry_a_glyph_not_only_a_hue(self):
        for sel in (".pill.good::before", ".pill.warn::before", ".pill.bad::before", ".pill.acc::before",
                    ".chip.strong::before", ".chip.partial::before"):
            self.assertIn(sel, self.text, sel)


if __name__ == "__main__":
    unittest.main()
