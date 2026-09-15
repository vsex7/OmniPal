.pragma library

// OmniPal Overview 空间几何与排布计算模型 (Model.js)

var DEFAULT_ASPECT_RATIO = 16.0 / 9.0;
var DEFAULT_GRID_GAP = 20;
var DEFAULT_PADDING = 48;

/**
 * 计算多工作区卡片在屏幕中的最佳多行多列 16:9 排布网格
 */
function calculateGrid(count, width, height, options) {
  var opts = options || {};
  var gap = typeof opts.gap === "number" ? opts.gap : DEFAULT_GRID_GAP;
  var padding = typeof opts.padding === "number" ? opts.padding : DEFAULT_PADDING;
  var ar = typeof opts.aspectRatio === "number" ? opts.aspectRatio : DEFAULT_ASPECT_RATIO;

  var availWidth = Math.max(100, (typeof width === "number" ? width : 1920) - padding * 2);
  var availHeight = Math.max(100, (typeof height === "number" ? height : 1080) - padding * 2);
  var maxWLimit = typeof opts.maxCardWidth === "number" ? opts.maxCardWidth : Math.min(availWidth * 0.75, 960);
  var maxHLimit = Math.floor(maxWLimit / ar);

  if (!count || count <= 0) {
    var fallbackW = Math.min(maxWLimit, Math.floor(availWidth * 0.6));
    return {
      cols: 1,
      rows: 1,
      cardWidth: fallbackW,
      cardHeight: Math.floor(fallbackW / ar),
      cards: []
    };
  }

  var bestScore = -1;
  var bestCols = 1;
  var bestRows = 1;
  var bestCardW = 0;
  var bestCardH = 0;

  for (var cols = 1; cols <= count; cols++) {
    var rows = Math.ceil(count / cols);
    var maxWByCols = Math.floor((availWidth - (cols - 1) * gap) / cols);
    var maxHByRows = Math.floor((availHeight - (rows - 1) * gap) / rows);

    var cardW = maxWByCols;
    var cardH = Math.floor(cardW / ar);

    if (cardH > maxHByRows) {
      cardH = maxHByRows;
      cardW = Math.floor(cardH * ar);
    }
    if (cardW > maxWLimit) {
      cardW = maxWLimit;
      cardH = Math.floor(cardW / ar);
    }
    if (cardH > maxHLimit) {
      cardH = maxHLimit;
      cardW = Math.floor(cardH * ar);
    }

    if (cardW > 0 && cardH > 0) {
      // 桌面宽屏优先倾向横向排布
      var bonus = (cols >= rows) ? 1.06 : 1.0;
      var score = (cardW * cardH) * bonus;
      if (score > bestScore) {
        bestScore = score;
        bestCols = cols;
        bestRows = rows;
        bestCardW = cardW;
        bestCardH = cardH;
      }
    }
  }

  var colsActual = bestCols;
  var rowsActual = bestRows;
  var cardWidth = Math.max(160, bestCardW);
  var cardHeight = Math.max(90, bestCardH);

  var totalGridWidth = colsActual * cardWidth + (colsActual - 1) * gap;
  var totalGridHeight = rowsActual * cardHeight + (rowsActual - 1) * gap;
  var startY = padding + Math.max(0, Math.floor((availHeight - totalGridHeight) / 2));

  var cards = [];
  for (var i = 0; i < count; i++) {
    var c = i % colsActual;
    var r = Math.floor(i / colsActual);
    var countInThisRow = (r === rowsActual - 1) ? (count - r * colsActual) : colsActual;
    var thisRowWidth = countInThisRow * cardWidth + (countInThisRow - 1) * gap;
    var thisRowStartX = padding + Math.max(0, Math.floor((availWidth - thisRowWidth) / 2));

    cards.push({
      index: i,
      row: r,
      col: c,
      x: thisRowStartX + c * (cardWidth + gap),
      y: startY + r * (cardHeight + gap),
      width: cardWidth,
      height: cardHeight
    });
  }

  return {
    cols: colsActual,
    rows: rowsActual,
    cardWidth: cardWidth,
    cardHeight: cardHeight,
    gridWidth: totalGridWidth,
    gridHeight: totalGridHeight,
    cards: cards
  };
}

/**
 * 将窗口在屏幕上的绝对坐标 (x, y, w, h) 按显示器有效分辨率比例缩放至 16:9 工作区微缩卡片内
 * 自动扣除顶部 28px 标题栏避免遮挡工作区标头
 */
function scaleWindowGeometry(windowBox, monitorBox, cardWidth, cardHeight) {
  var wb = windowBox || { x: 0, y: 0, width: 800, height: 600 };
  var mb = monitorBox || { x: 0, y: 0, width: 1920, height: 1080 };
  var cw = Math.max(10, typeof cardWidth === "number" ? cardWidth : 320);
  var ch = Math.max(10, typeof cardHeight === "number" ? cardHeight : 180);

  var monW = Math.max(1, mb.width || 1920);
  var monH = Math.max(1, mb.height || 1080);
  var monX = mb.x || 0;
  var monY = mb.y || 0;

  var relX = (wb.x - monX) / monW;
  var relY = (wb.y - monY) / monH;
  var relW = wb.width / monW;
  var relH = wb.height / monH;

  // 防御性边界约束
  relX = Math.max(0.0, Math.min(0.96, relX));
  relY = Math.max(0.0, Math.min(0.96, relY));
  relW = Math.max(0.05, Math.min(1.0 - relX, relW));
  relH = Math.max(0.05, Math.min(1.0 - relY, relH));

  var topPad = 30;
  var sidePad = 6;
  var bottomPad = 6;
  var usableW = Math.max(20, cw - sidePad * 2);
  var usableH = Math.max(20, ch - topPad - bottomPad);

  var scaledX = sidePad + Math.round(relX * usableW);
  var scaledY = topPad + Math.round(relY * usableH);
  var scaledW = Math.max(28, Math.round(relW * usableW));
  var scaledH = Math.max(22, Math.round(relH * usableH));

  return {
    x: scaledX,
    y: scaledY,
    width: scaledW,
    height: scaledH
  };
}

/**
 * 索引循环导航计算
 */
function navigateIndex(currentIndex, delta, totalCount) {
  var count = typeof totalCount === "number" ? totalCount : 0;
  if (count <= 0) return 0;
  var cur = typeof currentIndex === "number" ? currentIndex : 0;
  var d = typeof delta === "number" ? delta : 0;
  var next = (cur + d) % count;
  if (next < 0) next += count;
  return next;
}

/**
 * 应用详情字标与色彩映射
 */
function resolveAppDetails(cls) {
  if (!cls) return { icon: "🗔", color: "#88c0d0", category: "App" };
  var c = String(cls).toLowerCase();
  if (c.indexOf("antigravity") !== -1) {
    return { icon: "⚡", color: "#81a1c1", category: "AI Assistant" };
  }
  if (c.indexOf("kitty") !== -1 || c.indexOf("alacritty") !== -1 || c.indexOf("term") !== -1 || c.indexOf("foot") !== -1 || c.indexOf("ghostty") !== -1 || c.indexOf("wezterm") !== -1 || c.indexOf("warp") !== -1) {
    return { icon: "", color: "#a3be8c", category: "Terminal" };
  }
  if (c.indexOf("chrome") !== -1 || c.indexOf("firefox") !== -1 || c.indexOf("chromium") !== -1 || c.indexOf("zen") !== -1 || c.indexOf("edge") !== -1 || c.indexOf("brave") !== -1 || c.indexOf("opera") !== -1 || c.indexOf("vivaldi") !== -1) {
    return { icon: "🌐", color: "#88c0d0", category: "Browser" };
  }
  if (c.indexOf("thunar") !== -1 || c.indexOf("nautilus") !== -1 || c.indexOf("dolphin") !== -1 || c.indexOf("file") !== -1 || c.indexOf("nemo") !== -1 || c.indexOf("pcmanfm") !== -1) {
    return { icon: "📁", color: "#ebcb8b", category: "Files" };
  }
  if (c.indexOf("code") !== -1 || c.indexOf("cursor") !== -1 || c.indexOf("vscodium") !== -1 || c.indexOf("sublime") !== -1 || c.indexOf("neovim") !== -1 || c.indexOf("nvim") !== -1 || c.indexOf("zed") !== -1 || c.indexOf("idea") !== -1 || c.indexOf("pycharm") !== -1) {
    return { icon: "", color: "#b48ead", category: "Editor" };
  }
  if (c.indexOf("obsidian") !== -1 || c.indexOf("notion") !== -1 || c.indexOf("logseq") !== -1 || c.indexOf("notes") !== -1) {
    return { icon: "📝", color: "#d08770", category: "Notes" };
  }
  if (c.indexOf("settings") !== -1 || c.indexOf("control") !== -1 || c.indexOf("pavucontrol") !== -1 || c.indexOf("blueman") !== -1 || c.indexOf("nm-connection") !== -1) {
    return { icon: "⚙", color: "#d08770", category: "System" };
  }
  if (c.indexOf("spotify") !== -1 || c.indexOf("music") !== -1 || c.indexOf("sound") !== -1 || c.indexOf("vlc") !== -1 || c.indexOf("mpv") !== -1) {
    return { icon: "🎵", color: "#bf616a", category: "Media" };
  }
  if (c.indexOf("discord") !== -1 || c.indexOf("telegram") !== -1 || c.indexOf("wechat") !== -1 || c.indexOf("slack") !== -1 || c.indexOf("qq") !== -1 || c.indexOf("signal") !== -1) {
    return { icon: "💬", color: "#5e81ac", category: "Chat" };
  }
  if (c.indexOf("image") !== -1 || c.indexOf("gimp") !== -1 || c.indexOf("photo") !== -1 || c.indexOf("inkscape") !== -1 || c.indexOf("krita") !== -1 || c.indexOf("figma") !== -1) {
    return { icon: "🖼", color: "#8fbcbb", category: "Graphics" };
  }
  return { icon: cls.charAt(0).toUpperCase(), color: "#d8dee9", category: "App" };
}

function resolveAppGlyph(cls) {
  return resolveAppDetails(cls).icon;
}
