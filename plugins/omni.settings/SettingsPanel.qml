pragma ComponentBehavior: Bound
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Icons.js" as Icons

// OmniPal 设置与控制中心面板（omni.settings）
//
// 三分类 Tab 导航的现代控制中心：
// 1. 🎯 模式方案：动态枚举 profiles，卡片网格一键热切换（活动模式高亮边框 + 悬停升起动效）
// 2. ⚙️ 高级选项：可选配置持久化（显式开关）、Snap 布局菜单呼出、系统原生还原、速查表
// 3. 📊 使用洞察：本地使用统计（概览摘要 / 模式切换排行 / 吸附区域 Top 榜 + 一键重置）
//
// 架构铁律：本插件只做展示与触发，全部绑定/持久化/统计操作均通过 omni-profile CLI
// 交由 Engine 唯一执行，插件自身从不写任何 Hyprland 配置（AGENTS.md §2 / H-1）。
Item {
  id: root

  // ---- Theme ----------------------------------------------------------------
  // Native first: qs.Commons Color/Style + qs.Ui widgets wherever Omarchy has one.
  // `theme` (OmniTheme.qml) resolves the remaining custom-surface roles straight from
  // qs.Commons; the colors.toml palette below only feeds the extended status hues.
  readonly property OmniTheme theme: OmniTheme {}

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.settings"

  // ---------- 分类导航状态 ----------
  // 0 = 模式方案 · 1 = 高级选项 · 2 = 使用洞察
  property int activeTab: 0

  // ---------- 应用规则（omni-profile rules ...，按应用自动切换模式） ----------
  property var appRules: []
  property bool appRulesEnabled: true
  property string appRulesDefault: "none"
  property var appRuleMatch: null
  property string newRuleClass: ""
  property string newRuleMode: ""
  property string newRuleMatch: "exact"
  property string rulesError: ""
  property string appRulePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/app_rule.json"

  function loadRules(text) {
    try {
      var d = JSON.parse(text)
      root.appRules = d.rules || []
      root.appRulesEnabled = d.enabled !== false
      root.appRulesDefault = d.default_mode || "none"
    } catch (e) {}
  }

  function runRules(args) {
    root.rulesError = ""
    rulesCmdProc.command = ["omni-profile", "rules"].concat(args)
    rulesCmdProc.running = true
  }

  // ---------- Engine 状态（tmpfs 单一事实源广播） ----------
  property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/state.json"
  property string currentMode: "omarchy"
  property string currentName: "Omarchy 原生模式"
  property int activeBindingsCount: 0
  property int enginePid: 0
  property string engineUpdatedAt: ""
  property string engineStatus: "native"
  property bool engineRunning: false

  // ---------- 可选配置持久化状态（omni-profile persist status --json） ----------
  property bool persistEnabled: false
  property string persistProfile: ""
  property string persistPolicy: ""
  property string persistUpdatedAt: ""
  property string persistPath: ""
  property bool persistBusy: false

  // ---------- 本地使用统计（omni-profile stats --json，纯本地零上传） ----------
  property var statsSwitchList: []
  property var statsSnapList: []
  property int statsSwitchMax: 0
  property int statsSnapMax: 0
  property int statsTotal: 0
  property int statsSwitchTotal: 0
  property int statsSnapTotal: 0
  property string statsLastUpdated: ""
  property string statsLastReset: ""
  property bool statsLoaded: false
  property bool statsBusy: false

  // 模式元数据（默认预置，开窗自动从 omni-profile list --json 动态刷新）
  property var modeItems: [
    {
      id: "windows",
      icon: Icons.mode("windows"),
      name: "Windows 11 习惯模式",
      desc: "Alt+F4 关闭窗口 · Win+方向键智能吸附 · Win+E 文件管理器 · Win+Tab 任务视图",
      count: 19,
      source: "project",
      override: false
    },
    {
      id: "mac",
      icon: Icons.mode("mac"),
      name: "macOS 习惯模式",
      desc: "Super+Q 退出程序 · Super+Space 聚焦搜索 · Super+Shift+3/4 截图 · Super+H 最小化",
      count: 42,
      source: "project",
      override: false
    },
    {
      id: "kde",
      icon: Icons.mode("kde"),
      name: "KDE Plasma 习惯模式",
      desc: "Meta+方向键贴边 · Alt+Space 搜索 · Ctrl+Alt+L 锁屏 · Meta+W 概览",
      count: 19,
      source: "project",
      override: false
    },
    {
      id: "omarchy",
      icon: Icons.mode("omarchy"),
      name: "Omarchy 原生模式",
      desc: "",
      count: 0,
      source: "project",
      override: false
    }
  ]

  // 主题样式令牌：直接取 Omarchy Shell 的 qs.Commons（[menu] 表面，与 omarchy.menu /
  // omarchy.emojis 一致）。卡片/芯片用 Style 的 normal 控件 fill/border 令牌（见 Card 组件）。
  property color background: Commons.Color.menu.background
  property color foreground: Commons.Color.menu.text
  property color border: Commons.Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Commons.Color.menu.scrim
  property color selectedBackground: Commons.Color.menu.selectedBackground
  property color selectedText: Commons.Color.menu.selectedText
  readonly property color glassColor: root.background
  readonly property int cornerRadius: Style.cornerRadius

  readonly property color accent: Commons.Color.accent
  readonly property color okColor: root.accent
  readonly property color dangerColor: Commons.Color.urgent
  readonly property color chipColor: Style.normalFillFor(root.foreground, root.accent)

  readonly property int cardWidth: Math.min(Style.space(680), panel.width - Style.space(48))
  readonly property int cardHeight: Math.min(Style.space(640), panel.height - Style.space(48))

  // ---------- 行为函数 ----------
  function open(payloadJson) {
    root.opened = true
    stateFile.reload()
    listProc.running = true
    persistProc.running = true
    if (root.activeTab === 2) root.refreshStats()
    if (root.activeTab === 3) rulesListProc.running = true
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  // ---------- 确认 / 撤销状态 ----------
  // confirmAction: "" | "restore" | "reset" — 破坏性操作先经 Ui.ConfirmDialog 确认
  property string confirmAction: ""
  // 模式切换后 ~5s 内可按 U 撤销（回到 undoMode；omarchy 由 engine 走 restore 路径）
  property string undoMode: ""
  property string toastText: ""

  function askRestore() { root.confirmAction = "restore" }
  function askResetStats() { if (!root.statsBusy) root.confirmAction = "reset" }
  function cancelConfirm() { root.confirmAction = ""; Qt.callLater(function() { keyCatcher.forceActiveFocus() }) }
  function acceptConfirm() {
    var a = root.confirmAction
    root.confirmAction = ""
    if (a === "restore") root.restoreNative()
    else if (a === "reset") root.resetStats()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function switchModeWithUndo(targetMode) {
    if (!targetMode || targetMode === root.currentMode) return
    root.undoMode = root.currentMode
    root.toastText = "已切换至 " + root.modeNameOf(targetMode) + " · U 撤销"
    toastTimer.restart()
    root.switchMode(targetMode)
  }

  function undoSwitch() {
    if (!root.undoMode) return
    var m = root.undoMode
    root.undoMode = ""
    root.toastText = "已撤销 · 回到 " + root.modeNameOf(m)
    toastTimer.restart()
    root.switchMode(m)
  }

  Timer {
    id: toastTimer
    interval: 5000
    onTriggered: { root.undoMode = ""; root.toastText = "" }
  }

  function switchMode(targetMode) {
    if (!targetMode) return
    switchProc.command = ["omni-profile", "switch", targetMode]
    switchProc.running = true
  }

  function restoreNative() {
    switchProc.command = ["omni-profile", "restore"]
    switchProc.running = true
  }

  function openCheatSheet() {
    root.dismiss()
    if (root.shell && typeof root.shell.summon === "function") {
      root.shell.summon("omni.cheat-sheet", "{}")
    } else {
      Quickshell.execDetached(["omarchy-shell", "shell", "summon", "omni.cheat-sheet", "{}"])
    }
  }

  // 呼出 Snap 布局选择器：以 {"zone":"layouts"} 载荷召唤 omni.snap-feedback（双通道之一）
  function openSnapLayouts() {
    root.dismiss()
    var payload = '{"zone":"layouts"}'
    if (root.shell && typeof root.shell.summon === "function") {
      root.shell.summon("omni.snap-feedback", payload)
    } else {
      Quickshell.execDetached(["omarchy-shell", "shell", "summon", "omni.snap-feedback", payload])
    }
  }

  // iOS / macOS 风格滑动开关：显式触发持久化开/关，完成后刷新状态
  function togglePersist() {
    if (root.persistBusy) return
    root.persistBusy = true
    persistToggleProc.command = root.persistEnabled
      ? ["omni-profile", "persist", "disable"]
      : ["omni-profile", "persist", "enable"]
    persistToggleProc.running = true
  }

  function refreshStats() {
    statsProc.running = true
  }

  function resetStats() {
    if (root.statsBusy) return
    root.statsBusy = true
    statsResetProc.running = true
  }

  function modeNameOf(id) {
    for (var i = 0; i < root.modeItems.length; i++) {
      if (root.modeItems[i].id === id) return root.modeItems[i].name
    }
    return id
  }

  // Native colour discipline: every mode renders in accent; identity = glyph + name.
  function modeColorOf(id) { return root.accent }

  function fmtTs(s) {
    if (!s) return ""
    var t = String(s)
    var i = t.indexOf("T")
    if (i < 0) return t
    var z = t.indexOf("+")
    if (z < 0) z = t.lastIndexOf("Z")
    if (z < 0) z = t.length
    return t.slice(0, i) + " " + t.slice(i + 1, Math.min(z, i + 9))
  }

  // 计数对象 → 按次数降序的排行数组（并列时按名称字典序，取前 8）
  function rankArray(obj) {
    var arr = []
    for (var k in obj) {
      var v = obj[k]
      if (typeof v === "number" && v > 0) arr.push({ name: String(k), count: v })
    }
    arr.sort(function(a, b) {
      if (b.count !== a.count) return b.count - a.count
      return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0)
    })
    return arr.slice(0, 8)
  }

  function sumCounts(obj) {
    var t = 0
    for (var k in obj) {
      if (typeof obj[k] === "number") t += obj[k]
    }
    return t
  }

  function loadState(rawText) {
    if (!rawText || rawText.trim() === "") {
      root.engineRunning = false
      return
    }
    try {
      var d = JSON.parse(rawText)
      root.currentMode = d.mode || "omarchy"
      root.currentName = d.name || "Omarchy 原生模式"
      root.activeBindingsCount = d.active_bindings_count || 0
      root.enginePid = d.pid || 0
      root.engineUpdatedAt = d.updated_at || ""
      root.engineStatus = d.status || "native"
      root.engineRunning = true
    } catch (e) {
      root.engineRunning = false
    }
  }

  function loadPersist(rawText) {
    if (!rawText || rawText.trim() === "") return
    try {
      var d = JSON.parse(rawText)
      root.persistEnabled = d.enabled === true
      root.persistProfile = d.profile || ""
      root.persistPolicy = d.window_policy || ""
      root.persistUpdatedAt = d.updated_at || ""
      root.persistPath = d.path || ""
    } catch (e) {}
  }

  function loadStats(rawText) {
    root.statsLoaded = true
    if (!rawText || rawText.trim() === "") return
    try {
      var d = JSON.parse(rawText)
      var sw = (d && d.switches) || {}
      var sn = (d && d.snaps) || {}
      var ac = (d && d.actions) || {}
      var swList = root.rankArray(sw)
      var snList = root.rankArray(sn)
      root.statsSwitchList = swList
      root.statsSnapList = snList
      root.statsSwitchMax = swList.length > 0 ? swList[0].count : 0
      root.statsSnapMax = snList.length > 0 ? snList[0].count : 0
      root.statsSwitchTotal = root.sumCounts(sw)
      root.statsSnapTotal = root.sumCounts(sn)
      root.statsTotal = root.statsSwitchTotal + root.statsSnapTotal + root.sumCounts(ac)
      root.statsLastUpdated = d.last_updated || ""
      root.statsLastReset = d.last_reset || ""
    } catch (e) {}
  }

  onOpenedChanged: {
    if (root.opened) {
      stateFile.reload()
      listProc.running = true
      persistProc.running = true
    }
  }

  onActiveTabChanged: {
    if (root.activeTab === 2 && !root.statsLoaded) root.refreshStats()
    if (root.activeTab === 3) rulesListProc.running = true
  }

  Timer {
    id: stateRetryTimer
    interval: 1000
    repeat: false
    onTriggered: stateFile.reload()
  }

  // ---------- 数据源进程 ----------
  FileView {
    id: appRuleFile
    path: root.appRulePath
    watchChanges: true
    printErrors: false
    onLoaded: { try { root.appRuleMatch = JSON.parse(text()) } catch (e) {} }
    onFileChanged: reload()
  }

  Process {
    id: rulesListProc
    command: ["omni-profile", "rules", "list", "--json"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() { if (text && text.trim() !== "") root.loadRules(text) }
    }
  }

  Process {
    id: rulesCmdProc
    command: ["omni-profile", "rules", "list"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        var t = (text || "").trim()
        if (t.indexOf("\u274C") === 0) root.rulesError = t.replace("\u274C", "").trim()
      }
    }
    onExited: rulesListProc.running = true
  }

  Process {
    id: activeWinProc
    command: ["hyprctl", "activewindow", "-j"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        try { var w = JSON.parse(text); if (w && w["class"]) root.newRuleClass = w["class"] } catch (e) {}
      }
    }
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadState(text())
    onLoadFailed: {
      root.engineRunning = false
      stateRetryTimer.restart()
    }
    onFileChanged: reload()
  }

  Process {
    id: switchProc
    command: ["omni-profile", "switch", "omarchy"]
    running: false
    onExited: {
      stateFile.reload()
      listProc.running = true
      persistProc.running = true
      if (root.activeTab === 2) root.refreshStats()
    }
  }

  Process {
    id: listProc
    command: ["omni-profile", "list", "--json"]
    running: false
    stdout: SplitParser {
      onRead: function(data) {
        try {
          var parsed = JSON.parse(data)
          if (Array.isArray(parsed) && parsed.length > 0) {
            var items = []
            for (var i = 0; i < parsed.length; i++) {
              var p = parsed[i]
              // 名称/计数来自 profile（单一事实源）
              // display.icon / display.color stay in the schema but are not rendered.
              var icon = Icons.mode(p.id)
              var desc = p.description || (p.source === "user" ? "用户自定义配置模式" : "")
              items.push({
                id: p.id,
                icon: icon,
                name: p.name || p.id,
                desc: desc,
                count: p.bindings_count || 0,
                source: p.source || "project",
                override: p.override || false
              })
            }
            root.modeItems = items
          }
        } catch(e) {}
      }
    }
  }

  Process {
    id: persistProc
    command: ["omni-profile", "persist", "status", "--json"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        if (text && text.trim() !== "") root.loadPersist(text)
      }
    }
  }

  Process {
    id: persistToggleProc
    command: ["omni-profile", "persist", "enable"]
    running: false
    onExited: {
      root.persistBusy = false
      persistProc.running = true
      stateFile.reload()
    }
  }

  Process {
    id: statsProc
    command: ["omni-profile", "stats", "--json"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        root.loadStats(text)
      }
    }
  }

  Process {
    id: statsResetProc
    command: ["omni-profile", "stats", "--reset"]
    running: false
    onExited: {
      root.statsBusy = false
      root.refreshStats()
    }
  }

  // ---------- 内联组件：统计排行行（进度条 + 名称 + 次数） ----------
  component RankRow: Rectangle {
    id: rankRow
    required property var entry
    required property int rank
    required property int maxCount
    required property color barColor
    property string displayName: ""

    width: parent ? parent.width : 0
    implicitHeight: Style.space(32)
    radius: Style.cornerRadius
    color: "transparent"

    Rectangle {
      anchors.fill: parent
      radius: parent.radius
      color: Util.alpha(root.foreground, 0.03)
    }

    Rectangle {
      id: rankBar
      anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
      width: rankRow.maxCount > 0
        ? rankRow.width * Math.max(0.05, rankRow.entry.count / rankRow.maxCount)
        : 0
      radius: parent.radius
      color: Util.alpha(rankRow.barColor, 0.22)
      Behavior on width { NumberAnimation { duration: root.theme.duration(200); easing.type: Easing.OutCubic } }
    }

    Rectangle {
      anchors { left: parent.left; leftMargin: Style.space(4); verticalCenter: parent.verticalCenter }
      width: Style.space(4); height: parent.height - Style.space(8); radius: Style.cornerRadius
      color: rankRow.barColor
    }

    Text {
      id: rankCount
      anchors { right: parent.right; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
      text: rankRow.entry.count + " 次"
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      color: rankRow.barColor
    }

    Text {
      anchors {
        left: parent.left; leftMargin: Style.space(14)
        right: rankCount.left; rightMargin: Style.space(8)
        verticalCenter: parent.verticalCenter
      }
      text: (rankRow.rank > 0 ? rankRow.rank + ". " : "") + (rankRow.displayName || rankRow.entry.name)
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      color: Util.alpha(root.foreground, 0.9)
      elide: Text.ElideRight
    }
  }

  // ---------- 内联组件：设置卡片 / 芯片 ----------
  // Omarchy has no "card" widget; first-party panels paint grouped content with the
  // shared control tokens, so a Card is a BorderSurface with Style normal fill/border.
  component Card: BorderSurface {
    radius: Style.cornerRadius
    color: Style.normalFillFor(root.foreground, root.accent)
    borderSpec: Border.none() // single border = the outer surface (designer gap list)
  }

  // Bordered native Button used for every chip / action in this panel.
  component Chip: Button {
    bordered: true
    foreground: root.foreground
    accent: root.accent
    fontSize: Style.font.bodySmall
    verticalPadding: Style.spacing.xs
  }

  // (Toggle switches use the native qs.Ui ToggleSwitch.)

  // Native qs.Ui OverlayWindow (focused monitor, Overlay layer, exclusive focus).
  OverlayWindow {
    id: panel
    shown: root.opened
    WlrLayershell.namespace: "omni-settings"

    Rectangle {
      anchors.fill: parent
      color: root.scrim

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      color: root.glassColor
      borderSpec: root.borderSpec
      padding: Style.space(20)
      opacity: root.opened ? 1.0 : 0.0
      Behavior on opacity { NumberAnimation { duration: root.theme.duration(140) } }

      MouseArea {
        anchors.fill: parent
        onClicked: {} // 拦截点击穿透
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.onEscapePressed: root.dismiss()
        Keys.onPressed: function(event) {
          if (confirmDialog.opened) {
            if (confirmDialog.handleKey(event)) event.accepted = true
            return
          }
          var num = event.key - Qt.Key_1
          if (num >= 0 && num < 9 && num < root.modeItems.length) {
            root.activeTab = 0
            root.switchModeWithUndo(root.modeItems[num].id)
            event.accepted = true
          } else if (event.key === Qt.Key_R && (event.modifiers & Qt.ShiftModifier)) {
            root.askRestore()
            event.accepted = true
          } else if (event.key === Qt.Key_U && root.undoMode !== "") {
            root.undoSwitch()
            event.accepted = true
          } else if (event.key === Qt.Key_S) {
            root.openCheatSheet()
            event.accepted = true
          } else if (event.key === Qt.Key_Backtab || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))) {
            root.activeTab = (root.activeTab + 3) % 4
            event.accepted = true
          } else if (event.key === Qt.Key_Tab) {
            root.activeTab = (root.activeTab + 1) % 4
            event.accepted = true
          }
        }

        // 模式切换提示条（可撤销 ~5s）
        Text {
          id: modeToast
          z: 5
          anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
          text: root.toastText
          visible: opacity > 0.0
          opacity: root.toastText !== "" ? 1.0 : 0.0
          Behavior on opacity { NumberAnimation { duration: root.theme.duration(140) } }
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          color: root.accent
          textFormat: Text.PlainText
          MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.undoSwitch() }
        }

        ConfirmDialog {
          id: confirmDialog
          anchors.fill: parent
          z: 10
          opened: root.confirmAction !== ""
          message: root.confirmAction === "restore"
            ? "撤销全部绑定覆盖并恢复 Omarchy 原生快捷键？"
            : "清空全部本地使用统计？此操作不可撤销。"
          cancelText: "取消"
          confirmText: root.confirmAction === "restore" ? "还原" : "重置"
          onCanceled: root.cancelConfirm()
          onConfirmed: root.acceptConfirm()
        }

        // ---------- 顶部固定区：标题 + Tab 栏 + 引擎状态 ----------
        Column {
          id: topZone
          anchors { top: parent.top; left: parent.left; right: parent.right }
          width: parent.width
          spacing: Style.space(12)

          Item {
            width: parent.width
            height: Style.space(32)

            Text {
              text: "OmniPal 控制中心"
              font.family: Style.font.family
              font.pixelSize: Style.font.heading
              color: root.foreground
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              text: root.engineRunning ? "运行时内存热切换引擎在线" : "引擎未运行"
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              color: Util.alpha(root.foreground, 0.55)
              anchors.right: parent.right
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          // ---------- Tab 分类切换栏（平滑滑动指示器） ----------
          // Native ButtonGroup ("pick one of N"), same control the shell's own settings use.
          ButtonGroup {
            id: tabBar
            readonly property var tabs: ["模式", "选项", "统计", "规则"]
            options: tabs.map(function(t, i) { return { value: String(i), label: t } })
            value: String(root.activeTab)
            focusable: false
            foreground: root.foreground
            background: "transparent"
            accent: root.accent
            onChanged: function(v) { root.activeTab = parseInt(v, 10) }
          }

          // ---------- 引擎状态广播条 ----------
          Card {
            width: parent.width
            height: Style.space(40)

            Item {
              anchors.fill: parent
              anchors.margins: Style.space(12)

              Text {
                anchors {
                  left: parent.left
                  right: parent.right
                  verticalCenter: parent.verticalCenter
                }
                text: root.engineRunning
                  ? ("Engine PID " + root.enginePid + " · 当前覆盖 " + root.activeBindingsCount + " 组快捷键 · " + root.currentName)
                  : "Engine 未检测到运行 · 执行 omni-profile daemon 启动常驻"
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                color: root.engineRunning ? Qt.darker(root.foreground, 1.4) : root.dangerColor
                elide: Text.ElideRight
              }
            }
          }
        }

        // ---------- Tab 内容区（淡入淡出切换） ----------
        Item {
          id: contentZone
          anchors {
            top: topZone.bottom; topMargin: Style.space(14)
            left: parent.left; right: parent.right
            bottom: parent.bottom
          }
          width: parent.width
          height: parent.height

          // ===== Tab 0：模式方案 =====
          Item {
            id: profilesTab
            anchors.fill: parent
            opacity: root.activeTab === 0 ? 1.0 : 0.0
            visible: root.activeTab === 0 || opacity > 0.0
            Behavior on opacity { NumberAnimation { duration: root.theme.duration(200); easing.type: Easing.OutQuad } }

            Flickable {
              anchors.fill: parent
              contentWidth: width
              contentHeight: profilesCol.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds

              Column {
                id: profilesCol
                width: parent.width
                spacing: Style.space(12)

                Text {
                  text: "选择习惯按键模式 · 点击卡片或按数字键 1 ~ " + root.modeItems.length + " 一键热切换"
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  color: Util.alpha(root.foreground, 0.7)
                }

                // Single-column selectable rows (plugins/menu/Menu.qml style):
                // no row border, selected = fg@0.08 fill + accent text, glyph in fg.
                Column {
                  width: parent.width
                  spacing: Style.space(3)

                  Repeater {
                    model: root.modeItems

                    delegate: Rectangle {
                      id: modeCard
                      required property var modelData
                      required property int index

                      readonly property bool isActive: root.currentMode === modelData.id
                      readonly property bool hot: modeCardHover.containsMouse
                      readonly property color rowText: isActive ? root.accent : root.foreground
                      width: parent.width
                      height: Math.max(Style.space(50), modeCol.implicitHeight + Style.spacing.lg * 2)
                      radius: Style.cornerRadius
                      color: (isActive || hot) ? Util.alpha(root.foreground, 0.08) : "transparent"

                      MouseArea {
                        id: modeCardHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.switchMode(modeCard.modelData.id)
                      }

                      Text {
                        id: modeBadge
                        anchors { left: parent.left; leftMargin: Style.spacing.rowPaddingX; verticalCenter: parent.verticalCenter }
                        width: Style.space(28)
                        text: Icons.mode(modeCard.modelData.id)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.iconLarge
                        color: modeCard.rowText
                      }

                      Column {
                        id: modeCol
                        anchors {
                          left: modeBadge.right; leftMargin: Style.spacing.lg
                          right: modeKeycap.left; rightMargin: Style.spacing.lg
                          verticalCenter: parent.verticalCenter
                        }
                        spacing: Style.spacing.xxs

                        Text {
                          id: modeNameText
                          width: parent.width
                          text: modeCard.modelData.name
                          font.family: Style.font.menuFamily
                          font.pixelSize: Style.font.body
                          font.weight: Font.Medium
                          color: modeCard.rowText
                          elide: Text.ElideRight
                        }

                        Text {
                          width: parent.width
                          text: modeCard.modelData.count + " 组按键 · "
                            + (modeCard.modelData.source === "user"
                                ? (modeCard.modelData.override ? "用户自定义（覆盖内置）" : "用户自定义")
                                : "内置")
                            + (modeCard.modelData.desc ? " · " + modeCard.modelData.desc : "")
                          font.family: Style.font.family
                          font.pixelSize: Style.font.caption
                          color: Qt.darker(root.foreground, 1.4)
                          elide: Text.ElideRight
                        }
                      }

                      // Number hint (1..N) or plain "active" in accent; no pill.
                      Text {
                        id: modeKeycap
                        anchors { right: parent.right; rightMargin: Style.spacing.rowPaddingX; verticalCenter: parent.verticalCenter }
                        text: modeCard.isActive ? "active" : String(modeCard.index + 1)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        color: modeCard.isActive ? root.accent : Qt.darker(root.foreground, 1.4)
                      }
                    }
                  }
                }
              }
            }
          }

          // ===== Tab 1：高级选项 =====
          Item {
            id: prefsTab
            anchors.fill: parent
            opacity: root.activeTab === 1 ? 1.0 : 0.0
            visible: root.activeTab === 1 || opacity > 0.0
            Behavior on opacity { NumberAnimation { duration: root.theme.duration(200); easing.type: Easing.OutQuad } }

            Flickable {
              anchors.fill: parent
              contentWidth: width
              contentHeight: prefsCol.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds

              Column {
                id: prefsCol
                width: parent.width
                spacing: Style.space(10)

                // --- 可选配置持久化控制卡片 ---
                Card {
                  id: persistCard
                  width: parent.width
                  height: persistCardBody.implicitHeight + Style.space(28)
                  borderSpec: Border.controlSpec(root.persistEnabled ? "selected" : "normal", root.foreground, root.okColor)

                  Column {
                    id: persistCardBody
                    anchors {
                      top: parent.top; topMargin: Style.space(14)
                      left: parent.left; leftMargin: Style.space(14)
                      right: parent.right; rightMargin: Style.space(14)
                    }
                    spacing: Style.space(8)

                    Item {
                      width: parent.width
                      height: Style.space(34)

                      Row {
                        spacing: Style.space(8)
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                          font.family: Style.font.family
                          anchors.verticalCenter: parent.verticalCenter
                          text: Icons.glyph.save
                          font.pixelSize: Style.font.body
                        }
                        Text {
                          anchors.verticalCenter: parent.verticalCenter
                          text: "配置持久化（关机/重启记忆）"
                          font.family: Style.font.family
                          font.pixelSize: Style.font.body
                          color: root.foreground
                        }
                      }

                      ToggleSwitch {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        checked: root.persistEnabled
                        busy: root.persistBusy
                        interactive: !root.persistBusy
                        foreground: root.foreground
                        accent: root.okColor
                        onToggled: root.togglePersist()
                      }
                    }

                    Text {
                      width: parent.width
                      text: "默认开启，关机或重启后自动恢复上次使用的模式与窗口策略；关闭时重启恢复默认。"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.7)
                      wrapMode: Text.Wrap
                    }

                    Card {
                      width: parent.width
                      height: persistStatusText.implicitHeight + Style.space(12)
                      borderSpec: Border.none()

                      Text {
                        id: persistStatusText
                        anchors { fill: parent; leftMargin: Style.space(10); rightMargin: Style.space(10); topMargin: Style.space(6); bottomMargin: Style.space(6) }
                        text: root.persistBusy
                          ? "正在同步持久化状态…"
                          : (root.persistEnabled
                              ? ("已启用 · 自动记忆关机前配置：" + root.modeNameOf(root.persistProfile) + "（" + root.persistProfile + "）" + (root.persistPolicy ? " · " + (root.persistPolicy === "floating" ? "浮动" : "平铺") : "") + (root.persistUpdatedAt ? " · 更新于 " + root.fmtTs(root.persistUpdatedAt) : ""))
                              : "已禁用 · 关机/重启恢复默认，磁盘零残留")
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        color: root.persistEnabled ? root.okColor : Util.alpha(root.foreground, 0.65)
                        wrapMode: Text.Wrap
                        elide: Text.ElideRight
                        maximumLineCount: 2
                      }
                    }
                  }
                }

                // --- 窗口吸附快捷操作卡片 ---
                Card {
                  width: parent.width
                  height: snapCardBody.implicitHeight + Style.space(28)

                  Column {
                    id: snapCardBody
                    anchors {
                      top: parent.top; topMargin: Style.space(14)
                      left: parent.left; leftMargin: Style.space(14)
                      right: parent.right; rightMargin: Style.space(14)
                    }
                    spacing: Style.space(8)

                    Row {
                      spacing: Style.space(8)
                      Text {
                        font.family: Style.font.family
                        anchors.verticalCenter: parent.verticalCenter
                        text: Icons.glyph.magnet
                        font.pixelSize: Style.font.body
                      }
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "窗口吸附快捷操作"
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        color: root.foreground
                      }
                    }

                    Text {
                      width: parent.width
                      text: "无需记忆键位，随时呼出可视化 Snap 布局选择器，纯键盘完成分屏吸附。"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.7)
                      wrapMode: Text.Wrap
                    }

                    Button {
                      width: parent.width
                      iconText: Icons.glyph.snap
                      text: "呼出 Snap 布局菜单"
                      bordered: true
                      active: true
                      foreground: root.foreground
                      accent: root.accent
                      verticalPadding: Style.space(10)
                      onClicked: root.openSnapLayouts()
                    }
                  }
                }

                // --- 系统原生还原卡片 ---
                Card {
                  width: parent.width
                  height: restoreCardBody.implicitHeight + Style.space(28)
                  borderSpec: Border.controlSpec(restoreCardHover.containsMouse ? "hover-cursor" : "normal", root.foreground, root.dangerColor)

                  MouseArea {
                    id: restoreCardHover
                    anchors.fill: parent
                    hoverEnabled: true
                  }

                  Column {
                    id: restoreCardBody
                    anchors {
                      top: parent.top; topMargin: Style.space(14)
                      left: parent.left; leftMargin: Style.space(14)
                      right: parent.right; rightMargin: Style.space(14)
                    }
                    spacing: Style.space(8)

                    Row {
                      spacing: Style.space(8)
                      Text {
                        font.family: Style.font.family
                        anchors.verticalCenter: parent.verticalCenter
                        text: Icons.glyph.restore
                        font.pixelSize: Style.font.body
                        color: root.dangerColor
                      }
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "恢复 Omarchy 原生"
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        color: root.foreground
                      }
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "R"
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        color: Util.alpha(root.foreground, 0.55)
                        padding: 3
                        Card {
                          anchors.fill: parent
                        }
                      }
                    }

                    Text {
                      width: parent.width
                      text: "撤销全部内存绑定覆盖，把快捷键完整恢复到启动前状态，退出零残留。"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.7)
                      wrapMode: Text.Wrap
                    }

                    // Destructive action: native Button tinted with Color.urgent
                    // (same pattern as network's captive-portal button).
                    Button {
                      width: parent.width
                      text: "执行系统原生还原 (Shift+R)"
                      bordered: true
                      foreground: root.dangerColor
                      accent: root.dangerColor
                      verticalPadding: Style.space(10)
                      onClicked: root.askRestore()
                    }
                  }
                }

                // --- 快捷键速查表入口 ---
                Button {
                  width: parent.width
                  iconText: Icons.glyph.cheat
                  text: "快捷键速查表 (S)"
                  bordered: true
                  foreground: root.foreground
                  accent: root.accent
                  verticalPadding: Style.space(10)
                  onClicked: root.openCheatSheet()
                }
              }
            }
          }

          // ===== Tab 2：使用洞察 =====
          Item {
            id: analyticsTab
            anchors.fill: parent
            opacity: root.activeTab === 2 ? 1.0 : 0.0
            visible: root.activeTab === 2 || opacity > 0.0
            Behavior on opacity { NumberAnimation { duration: root.theme.duration(200); easing.type: Easing.OutQuad } }

            Flickable {
              anchors.fill: parent
              contentWidth: width
              contentHeight: analyticsCol.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds

              Column {
                id: analyticsCol
                width: parent.width
                spacing: Style.space(10)

                // --- 概览摘要卡片 ---
                Card {
                  width: parent.width
                  height: statsSummaryBody.implicitHeight + Style.space(28)

                  Column {
                    id: statsSummaryBody
                    anchors {
                      top: parent.top; topMargin: Style.space(14)
                      left: parent.left; leftMargin: Style.space(14)
                      right: parent.right; rightMargin: Style.space(14)
                    }
                    spacing: Style.space(10)

                    Row {
                      spacing: Style.space(8)
                      Text {
                        font.family: Style.font.family
                        anchors.verticalCenter: parent.verticalCenter
                        text: Icons.glyph.stats
                        font.pixelSize: Style.font.body
                      }
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "概览摘要"
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        color: root.foreground
                      }
                    }

                    Row {
                      width: parent.width
                      spacing: Style.space(8)

                      Repeater {
                        model: [
                          {
                            label: "累计总操作数",
                            value: root.statsLoaded ? String(root.statsTotal) : "…",
                            tint: root.accent
                          },
                          {
                            label: "上次更新",
                            value: root.statsLoaded
                              ? (root.statsLastUpdated ? root.fmtTs(root.statsLastUpdated) : "无记录")
                              : "…",
                            tint: root.okColor
                          },
                          {
                            label: "上次重置",
                            value: root.statsLoaded
                              ? (root.statsLastReset ? root.fmtTs(root.statsLastReset) : "从未")
                              : "…",
                            tint: root.persistEnabled ? root.accent : Util.alpha(root.foreground, 0.6)
                          }
                        ]
                        delegate: Card {
                          id: statCard
                          required property var modelData
                          width: (analyticsCol.width - Style.space(28) - Style.space(16)) / 3
                          height: Style.space(72)

                          Column {
                            anchors.centerIn: parent
                            spacing: Style.space(4)

                            Text {
                              anchors.horizontalCenter: parent.horizontalCenter
                              text: statCard.modelData.value
                              font.family: Style.font.family
                              font.pixelSize: statCard.modelData.label === "累计总操作数" ? Style.font.heading : Style.font.bodySmall
                              color: statCard.modelData.tint
                            }
                            Text {
                              anchors.horizontalCenter: parent.horizontalCenter
                              text: statCard.modelData.label
                              font.family: Style.font.family
                              font.pixelSize: Style.font.caption
                              color: Util.alpha(root.foreground, 0.6)
                            }
                          }
                        }
                      }
                    }
                  }
                }

                // --- 模式切换排行卡片 ---
                Card {
                  width: parent.width
                  height: switchRankBody.implicitHeight + Style.space(28)

                  Column {
                    id: switchRankBody
                    anchors {
                      top: parent.top; topMargin: Style.space(14)
                      left: parent.left; leftMargin: Style.space(14)
                      right: parent.right; rightMargin: Style.space(14)
                    }
                    spacing: Style.space(8)

                    Item {
                      width: parent.width
                      height: Style.space(22)

                      Row {
                        spacing: Style.space(8)
                        anchors.left: parent.left
                        Text {
                          font.family: Style.font.family
                          anchors.verticalCenter: parent.verticalCenter
                          text: Icons.glyph.cycle
                          font.pixelSize: Style.font.bodySmall
                        }
                        Text {
                          anchors.verticalCenter: parent.verticalCenter
                          text: "模式切换排行"
                          font.family: Style.font.family
                          font.pixelSize: Style.font.bodySmall
                          color: root.foreground
                        }
                      }

                      Text {
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: root.statsLoaded ? ("共 " + root.statsSwitchTotal + " 次") : ""
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        color: Util.alpha(root.foreground, 0.55)
                      }
                    }

                    Repeater {
                      model: root.statsSwitchList
                      delegate: RankRow {
                        required property var modelData
                        required property int index
                        entry: modelData
                        rank: index + 1
                        maxCount: root.statsSwitchMax
                        barColor: root.modeColorOf(modelData.name)
                        displayName: root.modeNameOf(modelData.name)
                      }
                    }

                    Text {
                      visible: root.statsLoaded && root.statsSwitchList.length === 0
                      width: parent.width
                      text: "暂无切换记录 · 切换习惯模式后自动累积"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.5)
                    }

                    Text {
                      visible: !root.statsLoaded
                      width: parent.width
                      text: "正在读取本地统计…"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.5)
                    }
                  }
                }

                // --- 常用吸附区域 Top 榜卡片 ---
                Card {
                  width: parent.width
                  height: snapRankBody.implicitHeight + Style.space(28)

                  Column {
                    id: snapRankBody
                    anchors {
                      top: parent.top; topMargin: Style.space(14)
                      left: parent.left; leftMargin: Style.space(14)
                      right: parent.right; rightMargin: Style.space(14)
                    }
                    spacing: Style.space(8)

                    Item {
                      width: parent.width
                      height: Style.space(22)

                      Row {
                        spacing: Style.space(8)
                        anchors.left: parent.left
                        Text {
                          font.family: Style.font.family
                          anchors.verticalCenter: parent.verticalCenter
                          text: Icons.glyph.compass
                          font.pixelSize: Style.font.bodySmall
                        }
                        Text {
                          anchors.verticalCenter: parent.verticalCenter
                          text: "常用吸附区域 Top 榜"
                          font.family: Style.font.family
                          font.pixelSize: Style.font.bodySmall
                          color: root.foreground
                        }
                      }

                      Text {
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: root.statsLoaded ? ("共 " + root.statsSnapTotal + " 次") : ""
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        color: Util.alpha(root.foreground, 0.55)
                      }
                    }

                    Repeater {
                      model: root.statsSnapList
                      delegate: RankRow {
                        required property var modelData
                        required property int index
                        entry: modelData
                        rank: index + 1
                        maxCount: root.statsSnapMax
                        barColor: root.accent
                      }
                    }

                    Text {
                      visible: root.statsLoaded && root.statsSnapList.length === 0
                      width: parent.width
                      text: "暂无吸附记录 · 通过吸附布局菜单或吸附快捷键自动累积"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.5)
                    }

                    Text {
                      visible: !root.statsLoaded
                      width: parent.width
                      text: "正在读取本地统计…"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      color: Util.alpha(root.foreground, 0.5)
                    }
                  }
                }

                // --- 重置统计数据操作 ---
                Button {
                  width: parent.width
                  text: root.statsBusy ? "正在重置统计…" : "重置统计数据"
                  bordered: true
                  enabled: !root.statsBusy
                  foreground: root.dangerColor
                  accent: root.dangerColor
                  verticalPadding: Style.space(10)
                  onClicked: root.askResetStats()
                }

                Text {
                  width: parent.width
                  text: "统计仅为本机聚合计数（~/.config/omnipal/stats.json）· 零按键内容记录 · 零网络上传"
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  color: Util.alpha(root.foreground, 0.45)
                  wrapMode: Text.Wrap
                  horizontalAlignment: Text.AlignHCenter
                }
              }
            }
          }

          // ===== Tab 3：应用规则（按应用自动切换模式） =====
          Item {
            id: rulesTab
            anchors.fill: parent
            opacity: root.activeTab === 3 ? 1.0 : 0.0
            visible: root.activeTab === 3 || opacity > 0.0
            Behavior on opacity { NumberAnimation { duration: root.theme.duration(140); easing.type: Easing.OutQuad } }

            Flickable {
              anchors.fill: parent
              contentWidth: width
              contentHeight: rulesCol.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds

              Column {
                id: rulesCol
                width: parent.width
                spacing: Style.space(10)

                // --- 总开关与默认模式 ---
                Card {
                  width: parent.width
                  height: Style.space(84)

                  Column {
                    anchors { fill: parent; margins: Style.space(12) }
                    spacing: Style.space(8)

                    Row {
                      spacing: Style.space(8)
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "按应用自动切换"
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        color: root.foreground
                      }
                      ToggleSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: root.appRulesEnabled
                        foreground: root.foreground
                        accent: root.okColor
                        onToggled: root.runRules([root.appRulesEnabled ? "disable" : "enable"])
                      }
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.appRulesEnabled ? "已启用" : "已停用"
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        color: Qt.darker(root.foreground, 1.4)
                      }
                    }

                    Row {
                      spacing: Style.space(6)
                      Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "没有匹配时："
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        color: Util.alpha(root.foreground, 0.7)
                      }
                      Repeater {
                        model: [{ id: "none", label: "手动选择的模式" }].concat(root.modeItems.map(function(m) { return { id: m.id, icon: Icons.mode(m.id), label: m.id } }))
                        delegate: Chip {
                          id: defChip
                          required property var modelData
                          text: modelData.label
                          selected: (root.appRulesDefault || "none") === modelData.id
                          onClicked: root.runRules(["default", defChip.modelData.id])
                        }
                      }
                    }
                  }
                }

                // --- 规则列表 ---
                Repeater {
                  model: root.appRules
                  delegate: BorderSurface {
                    id: ruleRow
                    required property var modelData
                    required property int index
                    readonly property bool active: root.appRuleMatch && root.appRuleMatch.rule
                      && root.appRuleMatch.rule["class"] === modelData["class"]
                    width: rulesCol.width
                    height: Style.space(40)
                    radius: Style.cornerRadius
                    color: active ? Style.selectedFillFor(root.foreground, root.accent) : Style.normalFillFor(root.foreground, root.accent)
                    borderSpec: Border.controlSpec(active ? "focus" : "normal", root.foreground, root.accent)
                    opacity: modelData.enabled === false ? 0.5 : 1.0

                    Row {
                      anchors { left: parent.left; leftMargin: Style.space(12); verticalCenter: parent.verticalCenter }
                      spacing: Style.space(10)
                      Text {
                        text: (ruleRow.index + 1) + "."
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        color: Util.alpha(root.foreground, 0.5)
                      }
                      Text {
                        text: ruleRow.modelData["class"]
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        color: root.foreground
                      }
                      Text {
                        text: ({ exact: "精确", prefix: "前缀", regex: "正则" })[ruleRow.modelData.match || "exact"]
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        color: Util.alpha(root.foreground, 0.55)
                      }
                      Text {
                        text: "→ " + ruleRow.modelData.mode
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        color: root.accent
                      }
                    }

                    Row {
                      anchors { right: parent.right; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
                      spacing: Style.space(6)
                      Repeater {
                        model: [
                          { label: ruleRow.modelData.enabled === false ? "启用" : "停用", args: ["toggle", ruleRow.modelData["class"]], danger: false },
                          { label: "删除", args: ["remove", ruleRow.modelData["class"]], danger: true }
                        ]
                        delegate: Chip {
                          id: ruleBtn
                          required property var modelData
                          text: modelData.label
                          foreground: modelData.danger ? root.dangerColor : root.foreground
                          accent: modelData.danger ? root.dangerColor : root.accent
                          onClicked: root.runRules(ruleBtn.modelData.args)
                        }
                      }
                    }
                  }
                }

                Text {
                  visible: root.appRules.length === 0
                  width: parent.width
                  horizontalAlignment: Text.AlignHCenter
                  text: "还没有规则。下面填好窗口类名和模式就能添加，比如 code 对应 mac。"
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  color: Util.alpha(root.foreground, 0.55)
                }

                // --- 添加规则 ---
                Card {
                  width: parent.width
                  height: Style.space(84)

                  Column {
                    anchors { fill: parent; margins: Style.space(12) }
                    spacing: Style.space(8)

                    Row {
                      spacing: Style.space(8)
                      // Native qs.Ui TextField
                      TextField {
                        id: classInput
                        width: Style.space(180)
                        text: root.newRuleClass
                        onTextEdited: root.newRuleClass = text
                        placeholderText: "窗口类名"
                        foreground: root.foreground
                        accent: root.accent
                      }
                      Chip {
                        text: "填入当前应用"
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: activeWinProc.running = true
                      }
                      ButtonGroup {
                        anchors.verticalCenter: parent.verticalCenter
                        options: [{ value: "exact", label: "精确" }, { value: "prefix", label: "前缀" }, { value: "regex", label: "正则" }]
                        value: root.newRuleMatch
                        foreground: root.foreground
                        background: "transparent"
                        accent: root.accent
                        fontSize: Style.font.bodySmall
                        onChanged: function(v) { root.newRuleMatch = v }
                      }
                    }

                    Row {
                      spacing: Style.space(6)
                      Repeater {
                        model: root.modeItems
                        delegate: Chip {
                          id: modeChip
                          required property var modelData
                          required property int index
                          iconText: Icons.mode(modelData.id)
                          text: modelData.id
                          selected: root.newRuleMode === modelData.id
                          onClicked: root.newRuleMode = modeChip.modelData.id
                        }
                      }
                      Chip {
                        readonly property bool ready: root.newRuleClass.trim() !== "" && root.newRuleMode !== ""
                        text: "添加"
                        iconText: Icons.glyph.plus
                        active: ready
                        enabled: ready
                        opacity: ready ? 1.0 : 0.5
                        onClicked: {
                          root.runRules(["add", root.newRuleClass.trim(), root.newRuleMode, "--match", root.newRuleMatch])
                          root.newRuleClass = ""
                        }
                      }
                    }
                  }
                }

                // --- 当前匹配 ---
                Text {
                  width: parent.width
                  text: root.rulesError !== "" ? root.rulesError
                    : (root.appRuleMatch && root.appRuleMatch.window_class
                      ? ("当前应用 " + root.appRuleMatch.window_class + "：" + (root.appRuleMatch.rule
                          ? ("命中规则，切到 " + root.appRuleMatch.rule.mode) : "没有命中规则"))
                      : "守护进程运行后，这里会显示当前应用匹配到的规则")
                  wrapMode: Text.WordWrap
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  color: root.rulesError !== "" ? root.dangerColor : Util.alpha(root.foreground, 0.65)
                }
              }
            }
          }
        }
      }
    }
  }
}
