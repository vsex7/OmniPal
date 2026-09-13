.pragma library

// Pure data helpers for the cheat-sheet HUD.
//
// Everything here operates on rows handed over by the OmniPal Engine
// (`omni-profile cheatsheet --json`, which joins profiles/*.json with
// schema/actions.json). This file deliberately contains NO keybindings:
// AGENTS.md 铁律 3 keeps the shortcut truth in schema/ + profiles/.
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

