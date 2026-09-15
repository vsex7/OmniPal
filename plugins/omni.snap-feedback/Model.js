.pragma library

// OmniPal 窗口吸附与 Snap Layouts 布局模型 (Model.js)
// 遵循 AGENTS.md 单一事实源规范：从 schema/snap_layouts.json 动态载入，零硬编码副本

var ZONES = {};
var TEMPLATES = [];

function loadSchemaJson(rawJson) {
  if (!rawJson) return;
  try {
    var d = typeof rawJson === "string" ? JSON.parse(rawJson) : rawJson;
    if (d.zones) ZONES = d.zones;
    if (d.templates && Array.isArray(d.templates)) TEMPLATES = d.templates;
  } catch (e) {}
}

/**
 * 根据屏幕和避让距离计算指定区域的高亮几何盒
 */
function calculateBox(zone, screenWidth, screenHeight, gap, reserved) {
  var g = typeof gap === "number" ? gap : 10;
  var res = (reserved && typeof reserved === "object") ? reserved : { top: 34, bottom: 0, left: 0, right: 0 };
  var resTop = typeof res.top === "number" ? res.top : 0;
  var resBottom = typeof res.bottom === "number" ? res.bottom : 0;
  var resLeft = typeof res.left === "number" ? res.left : 0;
  var resRight = typeof res.right === "number" ? res.right : 0;

  var sw = Math.max(200, typeof screenWidth === "number" ? screenWidth : 1920);
  var sh = Math.max(200, typeof screenHeight === "number" ? screenHeight : 1080);

  var z = ZONES[zone] || { xr: 0.0, yr: 0.0, wr: 0.5, hr: 1.0, icon: "◧", label: zone };
  var usableW = sw - resLeft - resRight - g * 2;
  var usableH = sh - resTop - resBottom - g * 2;

  var isLeftEdge = (z.xr === 0.0);
  var isRightEdge = (z.xr + z.wr >= 0.99);
  var isTopEdge = (z.yr === 0.0);
  var isBottomEdge = (z.yr + z.hr >= 0.99);

  var tw = Math.floor(usableW * z.wr) - Math.floor(g * (1 - (isRightEdge && isLeftEdge ? 1 : 0)) / 2);
  var th = Math.floor(usableH * z.hr) - Math.floor(g * (1 - (isTopEdge && isBottomEdge ? 1 : 0)) / 2);
  var tx = resLeft + g + Math.floor(usableW * z.xr) + Math.floor(g * (isLeftEdge ? 0 : 0.5));
  var ty = resTop + g + Math.floor(usableH * z.yr) + Math.floor(g * (isTopEdge ? 0 : 0.5));

  var finalW = Math.max(40, tw);
  var finalH = Math.max(40, th);

  return {
    x: tx,
    y: ty,
    width: finalW,
    height: finalH,
    dim: finalW + " × " + finalH + " px",
    icon: z.icon || "◧",
    label: z.label || zone
  };
}
