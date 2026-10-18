// Safety.js - shared UX safety helpers (single source; symlinked into each plugin as ../shared/Safety.js)
// - Mode switches are undoable for UNDO_MS ("已切换至 <mode> · U 撤销").
// - Window close has NO undo: first press arms, a second press within CONFIRM_MS closes.
.pragma library

var UNDO_MS = 5000;
var CONFIRM_MS = 2000;
var CLOSE_AGAIN_TEXT = "再按一次关闭";

function switchedText(name) { return "已切换至 " + name + " · U 撤销"; }
function undoneText(name) { return "已撤销 · 回到 " + name; }

// Returns true when `key` was already armed (=> perform the close now).
function isArmed(armedKey, key) { return !!key && armedKey === key; }
