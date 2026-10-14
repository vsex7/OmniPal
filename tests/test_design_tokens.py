import json, pathlib, re, shutil, subprocess, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"
TOKENS = PLUGINS / "shared" / "Tokens.js"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RAW_RGBA = re.compile(r"Qt\.rgba\(\s*[\d.]")


class DesignTokenTests(unittest.TestCase):
    def qml_files(self):
        return sorted(PLUGINS.rglob("*.qml"))

    def test_no_hardcoded_hex_colors_in_qml(self):
        hits = []
        for f in self.qml_files():
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if HEX.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
        self.assertEqual(hits, [], "hardcoded hex colours outside Tokens.js:\n" + "\n".join(hits))

    def test_no_literal_rgba_in_qml(self):
        hits = [f"{f.relative_to(ROOT)}:{n}" for f in self.qml_files()
                for n, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if RAW_RGBA.search(l)]
        self.assertEqual(hits, [])

    def test_no_literal_monospace_font(self):
        hits = [f"{f.relative_to(ROOT)}:{n}" for f in self.qml_files()
                for n, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if '"monospace"' in l]
        self.assertEqual(hits, [])

    def test_root_plugins_follow_omarchy_theme(self):
        for f in PLUGINS.glob("omni.*/*.qml"):
            s = f.read_text(encoding="utf-8")
            if "  id: root\n" in s:
                # Native Omarchy chrome: Commons singletons + qs.Ui kit; Tokens.js
                # is only the colors.toml palette fallback.
                self.assertIn("import qs.Commons", s, f.name)
                self.assertIn("import qs.Ui", s, f.name)
                self.assertNotIn('import "Tokens.js"', s, f.name)
                self.assertNotIn("Tokens.build(", s, f.name)
                self.assertRegex(s, r"\b(BorderSurface|Button|OverlayWindow|Panel)\s*\{", f.name)

    def test_shared_theme_is_native(self):
        for f in [PLUGINS / "shared" / "OmniTheme.qml", *PLUGINS.glob("omni.*/OmniTheme.qml")]:
            s = f.read_text(encoding="utf-8")
            self.assertIn("import qs.Commons", s, f.name)
            self.assertIn("Commons.Color.menu", s, f.name)
            self.assertIn("Style.", s, f.name)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_colors_toml_parser_and_fallback(self):
        js = TOKENS.read_text(encoding="utf-8").replace(".pragma library", "")
        toml = json.dumps('mode = "dark"\n# comment\naccent = "#ff0000"\nred = "#112233"\nbogus = "nope"\n')
        script = js + f"""
var Qt = {{ color: function(c){{return {{r:0,g:0,b:0}};}}, rgba: function(){{return 'rgba';}} }};
var p = mergePalette(parseColorsToml({toml}));
var t = build(null, p);
console.log(JSON.stringify([p.accent, p.red, p.background, p.bogus || null, t.danger, t.accent, modeColors(p).omarchy]));
"""
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), ["#ff0000", "#112233", "#1a1b26", None, "#112233", "#ff0000", "#9ece6a"])

    def test_tokens_radius_is_omarchy_flat(self):
        s = TOKENS.read_text(encoding="utf-8")
        self.assertIn("radius = { none: 0, sm: 0, md: 0", s)
        self.assertIn("normal: 2", s)


    # ---- designer gap list (native Omarchy look) --------------------------
    def ui_files(self):
        return [f for f in PLUGINS.glob("omni.*/*.qml") if f.name != "OmniTheme.qml"]

    def _hits(self, pattern):
        rx = re.compile(pattern)
        out = []
        for f in self.ui_files():
            for n, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if l.strip().startswith("//"):
                    continue
                if rx.search(l):
                    out.append(f"{f.relative_to(ROOT)}:{n}: {l.strip()}")
        return out

    def test_no_emoji_in_ui(self):
        # Monochrome Nerd Font glyphs only (Icons.js); emoji/pictographs are banned.
        self.assertEqual(self._hits(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]"), [])

    def test_no_bold_caps_or_tracking(self):
        self.assertEqual(self._hits(r"font\.bold|letterSpacing|toUpperCase\(|Font\.Bold|Font\.DemiBold"), [])

    def test_no_hover_lift_animation(self):
        self.assertEqual(self._hits(r"Behavior on (scale|y)\b"), [])

    def test_no_custom_status_or_mode_colours(self):
        self.assertEqual(self._hits(r"modeColors|modeColor\(|currentColor|display\.color|theme\.(ok|warn|info|special|highlight)\b"), [])

    def test_icons_are_shared_nerd_glyphs(self):
        src = (PLUGINS / "shared" / "Icons.js").read_text(encoding="utf-8")
        glyphs = re.findall(r'^  \w+: "(.)",$', src, re.M)
        self.assertTrue(glyphs)
        for g in glyphs:
            cp = ord(g)
            self.assertTrue(0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD, hex(cp))
        for d in PLUGINS.glob("omni.*/"):
            if (d / "Icons.js").exists():
                self.assertEqual((d / "Icons.js").read_text(encoding="utf-8"), src, d.name)


if __name__ == "__main__":
    unittest.main()
