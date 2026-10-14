// OmniPal Overview 数据模型与工具方法
// 负责 Hyprland 窗口元数据解析、物理空间几何坐标计算、矢量线框装配与 Compositor 调度

.pragma library

function detectAppType(cls, title) {
  var c = (cls || "").toLowerCase()
  var t = (title || "").toLowerCase()

  if (c.indexOf("code") !== -1 || c.indexOf("vsc") !== -1 || c.indexOf("zed") !== -1 ||
      c.indexOf("sublime") !== -1 || c.indexOf("nvim") !== -1 || c.indexOf("idea") !== -1 ||
      c.indexOf("pycharm") !== -1 || c.indexOf("webstorm") !== -1 || c.indexOf("emacs") !== -1 ||
      c.indexOf("antigravity") !== -1 || c.indexOf("cursor") !== -1) {
    return "code"
  }
  if (c.indexOf("chrome") !== -1 || c.indexOf("firefox") !== -1 || c.indexOf("browser") !== -1 ||
      c.indexOf("brave") !== -1 || c.indexOf("chromium") !== -1 || c.indexOf("edge") !== -1 ||
      c.indexOf("vivaldi") !== -1 || c.indexOf("zen") !== -1 || c.indexOf("epiphany") !== -1) {
    return "browser"
  }
  if (c.indexOf("foot") !== -1 || c.indexOf("kitty") !== -1 || c.indexOf("alacritty") !== -1 ||
      c.indexOf("ghostty") !== -1 || c.indexOf("terminal") !== -1 || c.indexOf("wezterm") !== -1 ||
      c.indexOf("konsole") !== -1 || c.indexOf("xterm") !== -1 || c.indexOf("agent") !== -1) {
    return "terminal"
  }
  if (c.indexOf("thunar") !== -1 || c.indexOf("nautilus") !== -1 || c.indexOf("dolphin") !== -1 ||
      c.indexOf("nemo") !== -1 || c.indexOf("pcmanfm") !== -1 || c.indexOf("file") !== -1) {
    return "files"
  }
  if (c.indexOf("spotify") !== -1 || c.indexOf("music") !== -1 || c.indexOf("audacious") !== -1 ||
      c.indexOf("vlc") !== -1 || c.indexOf("mpv") !== -1) {
    return "media"
  }
  if (c.indexOf("discord") !== -1 || c.indexOf("telegram") !== -1 || c.indexOf("slack") !== -1 ||
      c.indexOf("element") !== -1 || c.indexOf("qq") !== -1 || c.indexOf("wechat") !== -1) {
    return "chat"
  }
  if (c.indexOf("pen") !== -1 || c.indexOf("gimp") !== -1 || c.indexOf("inkscape") !== -1 ||
      c.indexOf("blender") !== -1 || c.indexOf("figma") !== -1) {
    return "graphics"
  }
  return "generic"
}

function formatAppName(cls, title) {
  var c = (cls || "").trim()
  if (!c) {
    return (title && title.trim()) ? title.trim() : "Application"
  }
  var lower = c.toLowerCase()
  var appMap = {
    "code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "vscodium": "VSCodium",
    "google-chrome": "Google Chrome",
    "chromium": "Chromium",
    "firefox": "Firefox",
    "zen-browser": "Zen Browser",
    "brave-browser": "Brave Browser",
    "foot": "Foot Terminal",
    "kitty": "Kitty Terminal",
    "alacritty": "Alacritty",
    "ghostty": "Ghostty",
    "wezterm": "WezTerm",
    "thunar": "Thunar File Manager",
    "org.gnome.nautilus": "Files",
    "nautilus": "Files",
    "org.kde.dolphin": "Dolphin",
    "dolphin": "Dolphin",
    "spotify": "Spotify",
    "discord": "Discord",
    "telegram-desktop": "Telegram",
    "org.telegram.desktop": "Telegram",
    "obsidian": "Obsidian",
    "gimp": "GIMP",
    "inkscape": "Inkscape",
    "blender": "Blender",
    "pen": "Pen Design",
    "antigravity": "Antigravity IDE",
    "org.omarchy.agent": "Omarchy Agent"
  }
  if (appMap[lower]) {
    return appMap[lower]
  }
  var parts = c.split(".")
  var last = parts[parts.length - 1]
  if (last.length > 0) {
    return last.charAt(0).toUpperCase() + last.slice(1)
  }
  return c
}

// Native colour discipline: no per-app hues. Kept for API compatibility; the UI
// colours items with Color.accent (selected) / Color.foreground (otherwise).
function getAppCyberColor(cls, appType) {
  return ""
}

function resolveIconName(cls, appType) {
  var c = (cls || "").toLowerCase()
  if (c.indexOf("code") !== -1) return "visual-studio-code"
  if (c.indexOf("chrome") !== -1) return "google-chrome"
  if (c.indexOf("firefox") !== -1) return "firefox"
  if (c.indexOf("foot") !== -1) return "foot"
  if (c.indexOf("kitty") !== -1) return "kitty"
  if (c.indexOf("ghostty") !== -1) return "ghostty"
  if (c.indexOf("alacritty") !== -1) return "Alacritty"
  if (c.indexOf("thunar") !== -1) return "system-file-manager"
  if (c.indexOf("spotify") !== -1) return "spotify"
  if (c.indexOf("discord") !== -1) return "discord"
  if (c.indexOf("telegram") !== -1) return "telegram"
  if (c.indexOf("pen") !== -1) return "pen"
  if (c.indexOf("agent") !== -1 || c.indexOf("omarchy") !== -1) return "omarchy"
  if (c.indexOf("antigravity") !== -1) return "applications-development"
  if (appType === "code") return "text-editor"
  if (appType === "browser") return "web-browser"
  if (appType === "terminal") return "utilities-terminal"
  if (appType === "files") return "system-file-manager"
  if (appType === "graphics") return "applications-graphics"
  return "application-x-executable"
}

function parseFetchOutput(rawText) {
  var text = String(rawText || "")
  var activeAddress = ""
  var activeWsId = 1
  var clientsList = []
  var workspacesList = []
  var monitorWidth = 2560
  var monitorHeight = 1440

  var actMatch = text.match(/<<<ACTIVE>>>([\s\S]*?)<<<CLIENTS>>>/)
  var cliMatch = text.match(/<<<CLIENTS>>>([\s\S]*?)<<<WORKSPACES>>>/)
  var wsMatch = text.match(/<<<WORKSPACES>>>([\s\S]*?)<<<MONITORS>>>/)
  var monMatch = text.match(/<<<MONITORS>>>([\s\S]*)/)

  var rawActive = actMatch ? actMatch[1].trim() : ""
  var rawClients = cliMatch ? cliMatch[1].trim() : (text.indexOf("<<<CLIENTS>>>") !== -1 ? text.substring(text.indexOf("<<<CLIENTS>>>") + 13).trim() : text)
  var rawWorkspaces = wsMatch ? wsMatch[1].trim() : ""
  var rawMonitors = monMatch ? monMatch[1].trim() : ""

  try {
    var actObj = JSON.parse(rawActive || "{}")
    activeAddress = actObj.address || ""
    if (actObj.workspace && actObj.workspace.id !== undefined) {
      activeWsId = actObj.workspace.id
    }
  } catch(e) {}

  try {
    var monList = JSON.parse(rawMonitors || "[]")
    if (Array.isArray(monList) && monList.length > 0) {
      if (monList[0].width && monList[0].height) {
        monitorWidth = monList[0].width
        monitorHeight = monList[0].height
      }
      for (var m = 0; m < monList.length; m++) {
        if (monList[m].focused && monList[m].activeWorkspace && monList[m].activeWorkspace.id !== undefined) {
          activeWsId = monList[m].activeWorkspace.id
          break
        }
      }
    }
  } catch(e) {}

  try {
    var rawList = JSON.parse(rawClients || "[]")
    if (Array.isArray(rawList)) {
      for (var i = 0; i < rawList.length; i++) {
        var item = rawList[i]
        if (!item || !item.address) continue
        if (item.mapped === false || item.hidden === true) continue
        if (item.class === "Quickshell" || item.class === "omarchy-shell") continue

        var appType = detectAppType(item.class, item.title)
        var appName = formatAppName(item.class, item.title)
        var icon = resolveIconName(item.class, appType)
        var wsId = (item.workspace && item.workspace.id !== undefined) ? item.workspace.id : 1
        var wsName = (item.workspace && item.workspace.name) ? item.workspace.name : String(wsId)

        var posX = (item.at && item.at[0] !== undefined) ? item.at[0] : 0
        var posY = (item.at && item.at[1] !== undefined) ? item.at[1] : 0
        var winW = (item.size && item.size[0] !== undefined) ? item.size[0] : 800
        var winH = (item.size && item.size[1] !== undefined) ? item.size[1] : 600

        var mW = monitorWidth > 0 ? monitorWidth : 2560
        var mH = monitorHeight > 0 ? monitorHeight : 1440
        var normX = Math.max(0, Math.min(1, posX / mW))
        var normY = Math.max(0, Math.min(1, posY / mH))
        var normW = Math.max(0.05, Math.min(1, winW / mW))
        var normH = Math.max(0.05, Math.min(1, winH / mH))

        var layoutMode = "TILED"
        if (item.fullscreen) layoutMode = "FULL"
        else if (item.floating) layoutMode = "FLOAT"

        clientsList.push({
          address: item.address,
          title: item.title || appName,
          initialTitle: item.initialTitle || item.title || "",
          class: item.class || "",
          appName: appName,
          appType: appType,
          iconName: icon,
          pid: item.pid || 0,
          workspaceId: wsId,
          workspaceName: wsName,
          floating: Boolean(item.floating),
          fullscreen: Boolean(item.fullscreen),
          layoutMode: layoutMode,
          resolutionStr: winW + "×" + winH,
          focusHistoryID: (item.focusHistoryID !== undefined) ? item.focusHistoryID : i,
          isFocused: (item.address === activeAddress),
          rawX: posX,
          rawY: posY,
          rawWidth: winW,
          rawHeight: winH,
          normX: normX,
          normY: normY,
          normW: normW,
          normH: normH
        })
      }
    }
  } catch(e) {}

  // 提取各工作区概览
  var wsMap = {}
  for (var k = 0; k < clientsList.length; k++) {
    var c = clientsList[k]
    if (!wsMap[c.workspaceId]) {
      wsMap[c.workspaceId] = {
        id: c.workspaceId,
        name: c.workspaceName,
        count: 0,
        active: (c.workspaceId === activeWsId)
      }
    }
    wsMap[c.workspaceId].count++
  }

  var sortedWs = []
  for (var wId in wsMap) {
    sortedWs.push(wsMap[wId])
  }
  sortedWs.sort(function(a, b) { return a.id - b.id })

  return {
    clients: clientsList,
    activeAddress: activeAddress,
    activeWorkspaceId: activeWsId,
    workspaces: sortedWs,
    monitorWidth: monitorWidth,
    monitorHeight: monitorHeight
  }
}

// 窗口模糊搜索过滤（支持应用名、窗口标题、Class）
function filterWindows(windows, query) {
  if (!windows || !Array.isArray(windows)) return []
  var q = (query || "").trim().toLowerCase()
  if (!q) return windows

  return windows.filter(function(w) {
    var title = (w.title || "").toLowerCase()
    var app = (w.appName || "").toLowerCase()
    var cls = (w.class || "").toLowerCase()
    var initTitle = (w.initialTitle || "").toLowerCase()

    return title.indexOf(q) !== -1 ||
           app.indexOf(q) !== -1 ||
           cls.indexOf(q) !== -1 ||
           initTitle.indexOf(q) !== -1
  })
}

// Omni HUD Deck 自适应黄金构图排布算法
// 兼顾信息可读性、高密度极客质感与视觉对称平衡
function calculateHudDeckLayout(windows, availW, availH, gap) {
  if (!windows || windows.length === 0) return []
  var n = windows.length
  var g = (gap !== undefined) ? gap : 24
  var wW = Math.max(600, availW)
  var wH = Math.max(400, availH)

  var rowDist = [1]
  if (n === 1) {
    rowDist = [1]
  } else if (n === 2) {
    rowDist = [2]
  } else if (n === 3) {
    rowDist = [3]
  } else if (n === 4) {
    rowDist = [2, 2]
  } else if (n === 5 || n === 6) {
    rowDist = [3, n - 3]
  } else if (n === 7 || n === 8) {
    rowDist = [4, n - 4]
  } else {
    var numRows = Math.min(3, Math.ceil(n / 3))
    var base = Math.floor(n / numRows)
    var rem = n % numRows
    rowDist = []
    for (var r = 0; r < numRows; r++) {
      rowDist.push(base + (r < rem ? 1 : 0))
    }
  }

  var numRows = rowDist.length
  var maxCols = 1
  for (var i = 0; i < rowDist.length; i++) {
    if (rowDist[i] > maxCols) maxCols = rowDist[i]
  }

  var totalRowGaps = (numRows - 1) * g
  var cellH = (wH - totalRowGaps) / numRows
  var totalColGaps = (maxCols - 1) * g
  var maxColW = (wW - totalColGaps) / maxCols

  // Bento Box 黄金长宽比限制 (宽:高 ≈ 1.8:1)
  if (n === 1) {
    maxColW = Math.min(maxColW * 0.50, 560)
    cellH = Math.min(cellH * 0.50, Math.round(maxColW / 1.85))
  } else if (n === 2) {
    maxColW = Math.min(maxColW * 0.75, 480)
    cellH = Math.min(cellH * 0.65, Math.round(maxColW / 1.85))
  } else if (n <= 4) {
    maxColW = Math.min(maxColW * 0.88, 440)
    cellH = Math.min(cellH * 0.75, Math.round(maxColW / 1.85))
  } else {
    maxColW = Math.min(maxColW, 400)
    cellH = Math.min(cellH, Math.round(maxColW / 1.85))
  }

  var totalGridH = numRows * cellH + totalRowGaps
  var stageStartY = Math.max(0, (wH - totalGridH) / 2)

  var results = []
  var winIdx = 0

  for (var rIdx = 0; rIdx < numRows; rIdx++) {
    var colsInRow = rowDist[rIdx]
    var rowCards = []

    for (var cIdx = 0; cIdx < colsInRow; cIdx++) {
      if (winIdx >= n) break
      var win = windows[winIdx]
      winIdx++

      var cardW = maxColW
      var cardH = cellH

      rowCards.push({
        win: win,
        w: Math.round(cardW),
        h: Math.round(cardH)
      })
    }

    var totalRowWidth = 0
    for (var k = 0; k < rowCards.length; k++) {
      totalRowWidth += rowCards[k].w
    }
    totalRowWidth += (rowCards.length - 1) * g

    var currX = Math.max(0, (wW - totalRowWidth) / 2)
    var currY = stageStartY + rIdx * (cellH + g)

    for (var j = 0; j < rowCards.length; j++) {
      var item = rowCards[j]
      var cardY = currY + (cellH - item.h) / 2

      var copy = {}
      for (var prop in item.win) {
        copy[prop] = item.win[prop]
      }
      copy.targetX = Math.round(currX)
      copy.targetY = Math.round(cardY)
      copy.targetWidth = Math.round(item.w)
      copy.targetHeight = Math.round(item.h)

      results.push(copy)
      currX += item.w + g
    }
  }

  return results
}

// 兼容别名
function calculateNaturalExposeLayout(windows, availW, availH, gap) {
  return calculateHudDeckLayout(windows, availW, availH, gap)
}



// Radial Cyber Nexus 360° 极坐标全息扇区星盘几何算法
function calculateRadialNexusLayout(windows, availW, availH) {
  if (!windows || windows.length === 0) return []
  var n = windows.length
  var cx = availW / 2
  var cy = availH / 2

  var results = []
  if (n === 1) {
    var win = windows[0]
    var copy = {}
    for (var p in win) copy[p] = win[p]
    copy.targetWidth = 460
    copy.targetHeight = 240
    copy.targetX = Math.round(cx - copy.targetWidth / 2)
    copy.targetY = Math.round(cy - copy.targetHeight / 2)
    copy.startAngle = -Math.PI / 2 - Math.PI / 3
    copy.endAngle = -Math.PI / 2 + Math.PI / 3
    copy.midAngle = -Math.PI / 2
    copy.cyberColor = getAppCyberColor(win.class, win.appType)
    copy.shortcutKey = "1"
    results.push(copy)
    return results
  }

  // 计算屏幕自适应的内外环半径
  var minDim = Math.min(availW, availH)
  var rInner = Math.max(220, Math.min(minDim * 0.23, 290))
  var rOuter = Math.max(340, Math.min(minDim * 0.38, 470))
  var rOuterHover = rOuter + 36

  var gap = (n <= 3) ? 0.10 : (n <= 6 ? 0.08 : 0.05)
  var step = (2 * Math.PI) / n
  var bladeSpan = step - gap
  var startBase = -Math.PI / 2

  for (var i = 0; i < n; i++) {
    var item = windows[i]
    var startA = startBase + i * step + gap / 2
    var endA = startA + bladeSpan
    var midA = (startA + endA) / 2
    var midR = (rInner + rOuter) / 2

    var copy = {}
    for (var prop in item) copy[prop] = item[prop]

    copy.index = i
    copy.startAngle = startA
    copy.endAngle = endA
    copy.midAngle = midA
    copy.rInner = rInner
    copy.rOuter = rOuter
    copy.rOuterHover = rOuterHover
    copy.midRadius = midR
    copy.cx = cx
    copy.cy = cy

    // 扇区中心视觉锚点坐标 (用于放置图标与排版)
    copy.anchorX = Math.round(cx + midR * Math.cos(midA))
    copy.anchorY = Math.round(cy + midR * Math.sin(midA))
    copy.angleDeg = Math.round(midA * 180 / Math.PI)
    copy.cyberColor = getAppCyberColor(item.class, item.appType)
    copy.shortcutKey = (i < 9) ? String(i + 1) : ""

    results.push(copy)
  }

  return results
}
function calculateRadialNexusLayout_old(windows, availW, availH) {
  if (!windows || windows.length === 0) return []
  var n = windows.length
  var cx = availW / 2
  var cy = availH / 2

  var results = []
  if (n === 1) {
    var win = windows[0]
    var copy = {}
    for (var p in win) copy[p] = win[p]
    copy.targetWidth = 420
    copy.targetHeight = 220
    copy.targetX = Math.round(cx - copy.targetWidth / 2)
    copy.targetY = Math.round(cy - copy.targetHeight / 2)
    copy.angleDeg = 0
    copy.cyberColor = getAppCyberColor(win.class, win.appType)
    copy.shortcutKey = "1"
    results.push(copy)
    return results
  }

  // 环形星盘半径 (适中尺寸，留出中心全息核心与外部呼吸空间)
  var minDim = Math.min(availW, availH)
  var radius = Math.max(260, Math.min(minDim * 0.35, 420))
  var cardW = Math.min(340, Math.max(260, minDim * 0.26))
  var cardH = 140

  // 12 点钟方向作为起点 (-PI / 2)
  var startAngle = -Math.PI / 2

  for (var i = 0; i < n; i++) {
    var item = windows[i]
    var angle = startAngle + (i / n) * 2 * Math.PI
    var angleDeg = (angle * 180 / Math.PI)

    var cardCenterX = cx + radius * Math.cos(angle)
    var cardCenterY = cy + radius * Math.sin(angle)

    var copy = {}
    for (var prop in item) copy[prop] = item[prop]

    copy.targetX = Math.round(cardCenterX - cardW / 2)
    copy.targetY = Math.round(cardCenterY - cardH / 2)
    copy.targetWidth = Math.round(cardW)
    copy.targetHeight = Math.round(cardH)
    copy.angleRad = angle
    copy.angleDeg = Math.round(angleDeg)
    copy.cyberColor = getAppCyberColor(item.class, item.appType)
    copy.shortcutKey = (i < 9) ? String(i + 1) : ""
    copy.cardCenterX = cardCenterX
    copy.cardCenterY = cardCenterY

    results.push(copy)
  }

  return results
}




// GTA V 经典战术武器轮盘排布算法 (纯真实窗口动态等分，0 虚假占位符)
function calculateGtaWheelLayout(windows, availW, availH) {
  if (!windows || windows.length === 0) return []
  var n = windows.length
  var cx = availW / 2
  var cy = availH / 2

  var results = []
  if (n === 1) {
    var win = windows[0]
    var copy = {}
    for (var p in win) copy[p] = win[p]
    copy.index = 0
    copy.startAngle = 0
    copy.endAngle = 2 * Math.PI
    copy.midAngle = -Math.PI / 2
    copy.rInner = 220
    copy.rOuter = 440
    copy.rOuterHover = 465
    copy.midRadius = 330
    copy.cx = cx
    copy.cy = cy
    copy.anchorX = cx
    copy.anchorY = cy - 330
    copy.shortcutKey = "1"
    copy.activeName = (win.appName || "APP").toUpperCase()
    copy.hasWindow = true
    results.push(copy)
    return results
  }

  var minDim = Math.min(availW, availH)
  var rInner = Math.max(180, Math.min(minDim * 0.20, 240))
  var rOuter = Math.max(320, Math.min(minDim * 0.36, 440))
  if (availW < 1680) {
    rInner = Math.round(rInner * 0.88)
    rOuter = Math.round(rOuter * 0.88)
  }
  var rOuterHover = rOuter + 30

  var gap = (n <= 2) ? 0.06 : (n <= 4 ? 0.045 : 0.035)
  var step = (2 * Math.PI) / n
  var wedgeSpan = step - gap
  // 槽位 0 始终位于 12 点钟正上方
  var startBase = -Math.PI / 2 - (step / 2)
  var cardScale = (n > 8) ? Math.max(0.65, 8.0 / n) : 1.0

  for (var i = 0; i < n; i++) {
    var item = windows[i]
    var startA = startBase + i * step + gap / 2
    var endA = startA + wedgeSpan
    var midA = (startA + endA) / 2
    var midR = (rInner + rOuter) / 2

    var copy = {}
    for (var prop in item) copy[prop] = item[prop]

    copy.index = i
    copy.hasWindow = true
    copy.startAngle = startA
    copy.endAngle = endA
    copy.midAngle = midA
    copy.rInner = rInner
    copy.rOuter = rOuter
    copy.rOuterHover = rOuterHover
    copy.midRadius = midR
    copy.cx = cx
    copy.cy = cy

    copy.anchorX = Math.round(cx + midR * Math.cos(midA))
    copy.anchorY = Math.round(cy + midR * Math.sin(midA))
    copy.angleDeg = Math.round(midA * 180 / Math.PI)
    copy.shortcutKey = (i < 9) ? String(i + 1) : ""
    copy.activeName = (item.appName || "WINDOW").toUpperCase()
    copy.cardScale = cardScale

    results.push(copy)
  }

  return results
}

// 鼠标极坐标角度转换为选中的武器轮盘扇区索引 (0 到 n-1)
function getWedgeIndexFromAngle(angleRad, n) {
  if (n <= 0) return 0
  var step = (2 * Math.PI) / n
  var startBase = -Math.PI / 2 - (step / 2)
  var diff = angleRad - startBase
  while (diff < 0) diff += 2 * Math.PI
  while (diff >= 2 * Math.PI) diff -= 2 * Math.PI
  var idx = Math.floor(diff / step) % n
  return idx
}
