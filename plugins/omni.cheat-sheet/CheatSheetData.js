.pragma library

// Pure data helpers for the cheat-sheet HUD.
//
// Everything here operates on rows handed over by the OmniPal Engine
// (`omni-profile cheatsheet --json`, which joins profiles/*.json with
// schema/actions.json). This file deliberately contains NO keybindings:
// AGENTS.md 铁律 3 keeps the shortcut truth in schema/ + profiles/.
//
// The keycap tables below are cosmetic DISPLAY transforms only: they relabel
// modifier tokens the engine already emitted (SUPER -> ⌘ in mac mode). They
// never enumerate combos, so a new binding surfaces in the HUD untouched.
//
// CATEGORY_LABELS is cosmetic display metadata only. A category that is not
// listed renders with its raw schema id, so adding a new category to
// schema/actions.json surfaces in the HUD without a plugin change.

var CATEGORY_LABELS = {
  window: "窗口管理",
  snap: "窗口吸附",
  navigation: "工作区 / 导航",
  launcher: "启动器",
  apps: "系统应用",
  tools: "效率工具",
  system: "会话与安全",
  other: "其他"
};

function categoryLabel(category) {
  var id = String(category || "other");
  return CATEGORY_LABELS[id] !== undefined ? CATEGORY_LABELS[id] : id;
}

// rows: [{ key, name, category, description }, ...]
//   -> [{ id, label, items: [{ key, name, description }, ...] }, ...]
//
// Group order follows first appearance, i.e. the order of the active profile's
// bindings. Sorting here would silently override the profile author's intent.
function groupByCategory(rows) {
  var out = [];
  var index = {};
  if (!rows || !rows.length) return out;

  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    if (!row) continue;
    var id = String(row.category || "other");
    var group = index[id];
    if (!group) {
      group = { id: id, label: categoryLabel(id), items: [] };
      index[id] = group;
      out.push(group);
    }
    group.items.push({
      key: String(row.key || ""),
      name: String(row.name || ""),
      description: String(row.description || "")
    });
  }
  return out;
}

// "SUPER + SHIFT + S" -> ["SUPER", "SHIFT", "S"] for one chip per key.
// Engine-side formatting owns the separator; a lone "+" (or any combo that
// degrades to nothing) falls back to the raw string so nothing disappears.
function splitCombo(key) {
  var raw = String(key || "");
  var parts = raw.split("+");
  var out = [];
  for (var i = 0; i < parts.length; i++) {
    var part = parts[i].trim();
    if (part) out.push(part);
  }
  return out.length ? out : [raw];
}

// Deterministic body height so the card sizes itself before any delegate is
// laid out — no post-layout resize flash when the HUD is summoned.
function contentHeight(groups, rowHeight, headerHeight, groupGap) {
  var total = 0;
  if (!groups || !groups.length) return total;
  for (var i = 0; i < groups.length; i++) {
    total += headerHeight + groups[i].items.length * rowHeight;
    if (i < groups.length - 1) total += groupGap;
  }
  return total;
}

// ------------------------------------------------------------- keycaps ---

// Canonical modifier name for a raw token ("MOD4"/"Win"/"CMD" -> "super").
// Empty string when the part is not a modifier.
var MODIFIER_ALIASES = {
  SUPER: "super", MOD4: "super", WIN: "super", META: "super",
  CMD: "super", COMMAND: "super",
  ALT: "alt", OPTION: "alt", MOD1: "alt",
  CTRL: "ctrl", CONTROL: "ctrl",
  SHIFT: "shift"
};

function partModifier(part) {
  var up = String(part || "").trim().toUpperCase();
  return MODIFIER_ALIASES[up] !== undefined ? MODIFIER_ALIASES[up] : "";
}

// Non-modifier tokens shared by every mode (engine emits `comma`, `slash`, …).
var SHARED_KEY_LABELS = {
  RETURN: "↵", ENTER: "↵", ESCAPE: "Esc", ESC: "Esc",
  BACKSPACE: "⌫", DELETE: "Del", TAB: "⇥", SPACE: "␣",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→",
  COMMA: ",", PERIOD: ".", SLASH: "/", SEMICOLON: ";", APOSTROPHE: "'",
  MINUS: "-", EQUAL: "=", BACKSLASH: "\\", GRAVE: "`",
  PRINT: "PrtSc", PAUSE: "Pause", CAPS_LOCK: "Caps"
};

// Per-mode native keycap relabeling. Anything unlisted falls through to the
// raw token, so unknown keys never vanish from the sheet.
var KEYCAP_MAC = {
  SUPER: "⌘", MOD4: "⌘", WIN: "⌘", META: "⌘", CMD: "⌘", COMMAND: "⌘",
  ALT: "⌥", OPTION: "⌥", MOD1: "⌥",
  CTRL: "⌃", CONTROL: "⌃",
  SHIFT: "⇧",
  RETURN: "↵", ENTER: "↵", ESCAPE: "⎋", ESC: "⎋",
  BACKSPACE: "⌫", DELETE: "⌦", TAB: "⇥", SPACE: "␣",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→"
};

var KEYCAP_WINDOWS = {
  SUPER: "⊞ Win", MOD4: "⊞ Win", WIN: "⊞ Win", META: "⊞ Win", CMD: "⊞ Win",
  ALT: "Alt", OPTION: "Alt", MOD1: "Alt",
  CTRL: "Ctrl", CONTROL: "Ctrl",
  SHIFT: "Shift",
  RETURN: "↵ Enter", ENTER: "↵ Enter", ESCAPE: "Esc", ESC: "Esc",
  BACKSPACE: "⌫", DELETE: "Del", TAB: "⇥ Tab", SPACE: "␣",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→"
};

var KEYCAP_GENERIC = {
  SUPER: "Super", MOD4: "Super", WIN: "Super", META: "Super", CMD: "Super",
  ALT: "Alt", OPTION: "Alt", MOD1: "Alt",
  CTRL: "Ctrl", CONTROL: "Ctrl",
  SHIFT: "Shift",
  RETURN: "Enter", ENTER: "Enter", ESCAPE: "Esc", ESC: "Esc",
  BACKSPACE: "⌫", DELETE: "Del", TAB: "Tab", SPACE: "␣",
  UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→"
};

// One raw key token -> physical keycap label for the given profile mode.
function formatKeyCap(part, mode) {
  var raw = String(part || "").trim();
  if (!raw) return "";
  var up = raw.toUpperCase();
  var m = String(mode || "").toLowerCase();
  var table = m === "mac" ? KEYCAP_MAC : (m === "windows" ? KEYCAP_WINDOWS : KEYCAP_GENERIC);
  if (table[up] !== undefined) return table[up];
  if (SHARED_KEY_LABELS[up] !== undefined) return SHARED_KEY_LABELS[up];
  if (up.length <= 2 && up >= "A" && up !== "") return up; // single letters / F4-style: keep raw caps
  return raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
}

// Does the combo contain at least one modifier that is currently held?
// pressedModifiers: { super:bool, alt:bool, ctrl:bool, shift:bool } (or an
// array of lowercase modifier names). False when nothing is pressed.
function isModifierActive(keyCombo, pressedModifiers) {
  if (!pressedModifiers) return false;
  var pressed = [];
  if (Array.isArray(pressedModifiers)) {
    pressed = pressedModifiers;
  } else {
    for (var k in pressedModifiers) {
      if (pressedModifiers[k]) pressed.push(String(k).toLowerCase());
    }
  }
  if (!pressed.length) return false;
  var parts = splitCombo(keyCombo);
  for (var i = 0; i < parts.length; i++) {
    var mod = partModifier(parts[i]);
    if (mod && pressed.indexOf(mod) !== -1) return true;
  }
  return false;
}

// ------------------------------------------------------- category filter ---

// All categories present in the rows, first-appearance order, each with a
// count, prefixed by a synthetic "all" entry: [{id:"all",label:"全部",count:N}, …]
function extractCategories(rows) {
  var out = [{ id: "all", label: "全部", count: 0 }];
  if (!rows || !rows.length) return out;
  out[0].count = rows.length;
  var index = {};
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    if (!row) continue;
    var id = String(row.category || "other");
    if (index[id] === undefined) {
      index[id] = out.length;
      out.push({ id: id, label: categoryLabel(id), count: 1 });
    } else {
      out[index[id]].count += 1;
    }
  }
  return out;
}

// Precise filtering by BOTH the free-text query and the selected category
// pill. "all" (or empty) skips the category constraint; empty query skips
// the text constraint.
function filterRows(rawRows, query, selectedCategory) {
  var rows = rawRows || [];
  var q = String(query || "").trim().toLowerCase();
  var cat = String(selectedCategory || "all");
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    if (!row) continue;
    if (cat !== "all" && String(row.category || "other") !== cat) continue;
    if (q !== "") {
      var k = String(row.key || "").toLowerCase();
      var n = String(row.name || "").toLowerCase();
      var d = String(row.description || "").toLowerCase();
      if (k.indexOf(q) === -1 && n.indexOf(q) === -1 && d.indexOf(q) === -1) continue;
    }
    out.push(row);
  }
  return out;
}
