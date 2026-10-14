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
                self.assertIn("Tokens.themeFiles", s, f.name)
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


if __name__ == "__main__":
    unittest.main()
