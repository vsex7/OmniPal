.pragma library

// Parses `omni-profile doctor --json` -> takeovers for display (cheat sheet + settings).
// No key lists here (AGENTS.md 铁律 3): every combo comes from the Engine.
//
// doctor.takeovers = { <mode>: { mode, source: "live"|"baseline"|"none", count,
//   takeovers: [{ combo, name, fixed, native: [{ description, dispatcher, arg }] }] }
//   | { mode, error } }

var KEY_NAMES = {
  SUPER: "Super", CTRL: "Ctrl", CONTROL: "Ctrl", ALT: "Alt", SHIFT: "Shift",
  SPACE: "Space", RETURN: "Enter", ENTER: "Enter", ESCAPE: "Esc", ESC: "Esc",
  TAB: "Tab", SLASH: "/", LEFT: "Left", RIGHT: "Right", UP: "Up", DOWN: "Down",
  BACKSPACE: "Backspace", DELETE: "Delete", PRINT: "Print", COMMA: ",", PERIOD: ".",
  MINUS: "-", EQUAL: "=", GRAVE: "`"
};

// "SUPER + SHIFT + SPACE" -> "Super+Shift+Space" (docs/GLOSSARY.md 按键写法)
function prettyCombo(combo) {
  // Merged rows list several combos as "A / B"; prettify each side.
  var groups = String(combo || "").split("/");
  var out = [];
  for (var gi = 0; gi < groups.length; gi++) {
    var parts = groups[gi].split("+");
    var pretty = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i].trim();
      if (!p) continue;
      var up = p.toUpperCase();
      if (KEY_NAMES[up] !== undefined) pretty.push(KEY_NAMES[up]);
      else if (/^F[0-9]+$/.test(up) || p.length === 1) pretty.push(up);
      else pretty.push(up.charAt(0) + up.slice(1).toLowerCase());
    }
    out.push(pretty.join("+"));
  }
  return out.join(" / ");
}

// What the native bind did: description first, dispatcher+arg as fallback.
function nativeText(native) {
  var list = Array.isArray(native) ? native : [];
  var out = [];
  for (var i = 0; i < list.length; i++) {
    var n = list[i] || {};
    var t = String(n.description || "").trim();
    if (!t) t = (String(n.dispatcher || "") + " " + String(n.arg || "")).trim();
    if (t && t !== "__lua" && out.indexOf(t) < 0) out.push(t);
  }
  return out.length ? out.join("；") : "未命名的原生快捷键";
}

function parseDoctor(raw) {
  if (raw && typeof raw === "object") return raw;
  var text = String(raw || "").trim();
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) {}
  // doctor may print a trailing log line; keep the outermost object.
  var a = text.indexOf("{"), b = text.lastIndexOf("}");
  if (a < 0 || b <= a) return null;
  try { return JSON.parse(text.slice(a, b + 1)); } catch (e2) { return null; }
}

// -> { status: "ok"|"empty"|"none"|"error"|"unknown", source, items: [{ combo, key, name, was, fixed }], hint }
function forMode(doctor, mode) {
  var d = parseDoctor(doctor);
  var res = { status: "unknown", source: "", items: [], hint: "" };
  if (!d || typeof d !== "object" || !d.takeovers || typeof d.takeovers !== "object") {
    res.hint = "读不到接管信息（omni-profile doctor --json 没有 takeovers）。";
    return res;
  }
  var m = d.takeovers[String(mode || "")];
  if (!m || typeof m !== "object") {
    res.hint = "没有这个模式的接管信息。";
    return res;
  }
  if (m.error) {
    res.status = "error";
    res.hint = "读取接管信息失败：" + String(m.error);
    return res;
  }
  res.source = String(m.source || "");
  var list = Array.isArray(m.takeovers) ? m.takeovers : [];
  for (var i = 0; i < list.length; i++) {
    var e = list[i] || {};
    if (!e.combo) continue;
    res.items.push({
      combo: prettyCombo(e.combo),
      key: String(e.combo),
      name: String(e.name || e.action || ""),
      was: nativeText(e.native),
      fixed: e.fixed === true
    });
  }
  if (res.source === "none") {
    res.status = "none";
    res.hint = "读不到 Hyprland 当前的快捷键，暂时无法列出会接管哪些原生快捷键。";
  } else {
    res.status = res.items.length ? "ok" : "empty";
    if (!res.items.length) res.hint = "不接管任何 Omarchy 原生快捷键。";
  }
  return res;
}
