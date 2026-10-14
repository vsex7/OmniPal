pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Icons.js" as Icons
import "Model.js" as Model
import "Safety.js" as Safety

// OmniPal 托盘模式指示器与右键快捷控制面板（omni.mode-indicator）
//
// 遵循 Omarchy Quickshell 规范：
// 1. 与 Omarchy 第一方 bar-widget（panels/power、panels/network）同构：
//    根为 qs.Ui Panel（PanelController 管理开合 + 与其它 bar 面板互斥），
//    按钮为 BarIconButton，面板为 KeyboardPanel + PanelKeyCatcher（j/k/h/l/Enter/Esc/Tab）
// 2. 通过 FileView 监听 /run/user/1000/omnipal/state.json，毫秒级响应，零轮询开销
// 3. 左键：快速轮转切换模式 (omni-profile cycle)
//    右键：呼出/收起快捷控制面板 (原生 KeyboardPanel)
//    中键：呼出设置面板 (omarchy-shell shell toggle omni.settings)
// 4. 面板全部使用原生组件：PanelHero / PanelSectionHeader / PanelSeparator /
//    Button（列表行，selected + hasCursor）/ ButtonGroup（窗口策略），无 ✕ 关闭（Esc / 点击外部收起），包含肌肉记忆模式与窗口策略（平铺/浮动/跟随模式）控制
// 5. 外部点击收起、bar 弹窗互斥均由 KeyboardPanel/bar 协调器负责
// 6. 模式与策略数据 100% 来源单一事实源 (omni-profile / state.json)
Panel {
  id: root

  // ---- Theme ----------------------------------------------------------------
  // All chrome comes from qs.Commons (Color / Style) and qs.Ui components, exactly
  // like first-party panels. Only the native colour roles are used; mode identity
  // is the Nerd Font glyph + name (Icons.js), never a per-mode colour.
  moduleName: "omni.mode-indicator"
  ipcTarget: "omni.mode-indicator"
  // We own the single IpcHandler for this target (extra methods below), like omarchy.power.
  manageIpc: false

  property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/state.json"
  property string currentMode: "omarchy"
  property string currentName: "Omarchy 原生模式"
  readonly property string currentIcon: Icons.mode(root.currentMode)
  property string currentBrief: "OMA"
  property int activeBindingsCount: 0
  property bool engineRunning: false
  property string engineStatus: "native"
  // Mirrors Panel.opened (PanelController); kept as a name for IPC/tests.
  readonly property bool panelOpen: root.opened
  // Keyboard cursor over the panel rows: profiles, then the policy group, then actions.
  property bool cursorActive: false
  property int cursorIndex: 0
  property int policyCursor: -1
  property string windowPolicy: "tiled"
  property string effectiveWindowMode: "tiled"
  property bool compositorConnected: false
  property var actionHints: ({})

  property var profiles: Model.fallbackProfiles()
  property var policyOptions: Model.windowPolicies()

  function loadActionHints(rawText) {
    try {
      var rows = JSON.parse(rawText)
      var hints = {}
      if (Array.isArray(rows)) {
        for (var i = 0; i < rows.length; i++) {
          if (rows[i] && rows[i].action) hints[rows[i].action] = rows[i].key || ""
        }
      }
      root.actionHints = hints
    } catch (e) {
      root.actionHints = ({})
    }
  }

  function loadState(rawText) {
    if (!rawText || rawText.trim() === "") {
      root.engineRunning = false
      return
    }
    try {
      var data = JSON.parse(rawText)
      root.currentMode = data.mode || "omarchy"
      root.currentName = data.name || Model.resolveName(data)
      root.activeBindingsCount = data.active_bindings_count || 0
      root.engineStatus = data.status || (root.currentMode !== "omarchy" ? "active" : "native")
      root.currentBrief = (data.display && data.display.brief) || Model.defaultBrief(root.currentMode)
      root.windowPolicy = Model.normalizePolicy(data.window_policy) || "tiled"
      root.effectiveWindowMode = data.effective_window_mode || Model.computeEffectiveMode(root.windowPolicy, root.currentMode)
      root.compositorConnected = (data.compositor_connected !== undefined)
        ? Boolean(data.compositor_connected)
        : (Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") !== "" && Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") !== undefined)
      root.engineRunning = true
      if (!hintsProcess.running) hintsProcess.running = true
    } catch (e) {
      root.engineRunning = false
    }
  }

  Timer {
    id: stateRetryTimer
    interval: 1000
    repeat: false
    onTriggered: stateFile.reload()
  }

  // 守护进程重启或状态文件重建时自愈恢复；连接成功后自动暂停，零CPU开销
  Timer {
    id: autoHealTimer
    interval: 2000
    running: !root.engineRunning
    repeat: true
    onTriggered: stateFile.reload()
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
    id: listProcess
    command: ["omni-profile", "list", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        var raw = text  // streamFinished() carries no args; read StdioCollector.text
        if (!raw || raw.trim() === "") return
        try {
          var parsed = JSON.parse(raw)
          if (Array.isArray(parsed) && parsed.length > 0) {
            root.profiles = parsed
          }
        } catch (e) {}
      }
    }
  }

  Process {
    id: hintsProcess
    command: ["omni-profile", "cheatsheet", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        var raw = text  // streamFinished() carries no args; read StdioCollector.text
        if (raw && raw.trim() !== "") root.loadActionHints(raw)
      }
    }
  }

  Component.onCompleted: {
    listProcess.running = true
    hintsProcess.running = true
  }

  function runCmd(cmd) {
    if (root.bar && typeof root.bar.run === "function") {
      root.bar.run(cmd)
    } else {
      Quickshell.execDetached(["sh", "-c", cmd])
    }
  }

  // Panel.open()/close()/toggle() drive PanelController; the bar's popout coordinator
  // (requestPopout/releasePopout on older shells) is handled by KeyboardPanel itself.
  function openPanel() { root.open() }
  function closePanel() { root.close() }
  function togglePanel() { root.toggle() }

  onOpenedChanged: {
    if (opened) {
      if (!listProcess.running) listProcess.running = true
      if (!hintsProcess.running) hintsProcess.running = true
      root.cursorActive = false
      root.cursorIndex = 0
      root.policyCursor = -1
    }
  }

  // ---- keyboard cursor (PanelKeyCatcher) ------------------------------------
  readonly property var actionRows: [
    { icon: Icons.glyph.cheat, label: "快捷键速查表", hintKey: "cheat_sheet", run: "cheat", closes: true },
    { icon: Icons.glyph.settings, label: "控制中心", hintKey: "omni_settings", run: "settings", closes: true },
    { icon: Icons.glyph.snap, label: "布局吸附", hintKey: "snap_layouts", run: "snap", closes: true },
    { icon: Icons.glyph.overview, label: "多任务概览", hintKey: "task_view", run: "overview", closes: true }
  ]
  readonly property var systemRows: [
    { icon: Icons.glyph.cycle, label: "切换下一模式", hint: "", run: "cycle", closes: false },
    { icon: Icons.glyph.restore, label: "还原原生快捷键", hint: "", run: "restore", closes: true },
    { icon: Icons.glyph.doctor, label: "健康诊断", hint: "", run: "doctor", closes: true }
  ]
  readonly property int policyRowIndex: root.profiles.length
  readonly property int actionBase: root.profiles.length + 1
  readonly property int systemBase: root.actionBase + root.actionRows.length
  readonly property int cursorCount: root.systemBase + root.systemRows.length

  function runAction(row) {
    if (!row) return
    if (row.run === "cheat") root.openCheatSheet()
    else if (row.run === "settings") root.openSettings()
    else if (row.run === "snap") root.triggerSnap()
    else if (row.run === "overview") root.openOverview()
    else if (row.run === "cycle") root.cycleMode(false)
    else if (row.run === "restore") root.restoreBaseline()
    else if (row.run === "doctor") root.runDoctor()
    if (row.closes) root.closePanel()
  }

  function moveCursor(dx, dy) {
    if (!root.cursorActive) { root.cursorActive = true; return }
    if (dy !== 0) {
      root.cursorIndex = Math.max(0, Math.min(root.cursorCount - 1, root.cursorIndex + dy))
      root.policyCursor = -1
    } else if (dx !== 0 && root.cursorIndex === root.policyRowIndex) {
      var n = root.policyOptions.length
      var cur = root.policyCursor >= 0 ? root.policyCursor : Math.max(0, root.policySelectedIndex())
      root.policyCursor = Math.max(0, Math.min(n - 1, cur + dx))
    }
  }

  function policySelectedIndex() {
    for (var i = 0; i < root.policyOptions.length; i++)
      if (root.policyOptions[i].id === Model.normalizePolicy(root.windowPolicy)) return i
    return -1
  }

  function activateCursor() {
    if (!root.cursorActive) return
    var i = root.cursorIndex
    if (i < root.profiles.length) root.switchModeWithUndo(root.profiles[i].id)
    else if (i === root.policyRowIndex) {
      if (root.policyCursor >= 0) root.setPolicy(root.policyOptions[root.policyCursor].id)
    } else if (i < root.systemBase) root.runAction(root.actionRows[i - root.actionBase])
    else root.runAction(root.systemRows[i - root.systemBase])
  }

  function hoverRow(i, on) {
    if (!on) return
    root.cursorActive = true
    root.cursorIndex = i
  }

  function cycleMode(reverse) {
    var cmd = reverse ? "omni-profile cycle --reverse" : "omni-profile cycle"
    runCmd(cmd)
  }

  // ---- undoable mode switch (same behaviour/texts as SettingsPanel via Safety.js)
  property string undoMode: ""
  property string toastText: ""

  function modeNameOf(id) {
    for (var i = 0; i < root.profiles.length; i++)
      if (root.profiles[i].id === id) return Model.resolveName(root.profiles[i])
    return id
  }

  function switchModeWithUndo(modeId) {
    if (!modeId || modeId === root.currentMode) return
    root.undoMode = root.currentMode
    root.toastText = Safety.switchedText(root.modeNameOf(modeId))
    toastTimer.restart()
    root.switchMode(modeId)
  }

  function undoSwitch() {
    if (!root.undoMode) return
    var m = root.undoMode
    root.undoMode = ""
    root.toastText = Safety.undoneText(root.modeNameOf(m))
    toastTimer.restart()
    root.switchMode(m)
  }

  Timer {
    id: toastTimer
    interval: Safety.UNDO_MS
    onTriggered: { root.undoMode = ""; root.toastText = "" }
  }

  function switchMode(modeId) {
    if (!modeId) return
    var safePattern = /^[a-zA-Z0-9_.-]+$/
    var cleanMode = String(modeId).trim()
    if (!safePattern.test(cleanMode)) return
    root.currentMode = cleanMode
    root.effectiveWindowMode = Model.computeEffectiveMode(root.windowPolicy, cleanMode)
    for (var i = 0; i < root.profiles.length; i++) {
      if (root.profiles[i].id === cleanMode) {
        var p = root.profiles[i]
        root.currentName = Model.resolveName(p)
        root.currentBrief = Model.resolveBrief(p)
        root.activeBindingsCount = p.bindings_count || 0
        break
      }
    }
    runCmd("omni-profile switch " + cleanMode)
  }

  function setPolicy(policyId) {
    if (!policyId) return
    var norm = Model.normalizePolicy(policyId)
    root.windowPolicy = norm
    root.effectiveWindowMode = Model.computeEffectiveMode(norm, root.currentMode)
    runCmd("omni-profile window-policy set " + norm)
  }

  function restoreBaseline() {
    root.currentMode = "omarchy"
    root.currentName = "Omarchy 原生模式"
    root.currentBrief = "OMA"
    root.activeBindingsCount = 0
    root.effectiveWindowMode = Model.computeEffectiveMode(root.windowPolicy, "omarchy")
    runCmd("omni-profile restore")
  }

  function openCheatSheet() {
    runCmd("omarchy-shell shell toggle omni.cheat-sheet")
  }

  function openSettings() {
    runCmd("omarchy-shell shell toggle omni.settings")
  }

  function triggerSnap() {
    runCmd("omni-profile snap layouts")
  }

  function openOverview() {
    runCmd("omarchy-shell shell toggle omni.overview")
  }

  function runDoctor() {
    runCmd("which omarchy-launch-floating-terminal-with-presentation >/dev/null 2>&1 && omarchy-launch-floating-terminal-with-presentation 'omni-profile doctor' || (which xdg-terminal-exec >/dev/null 2>&1 && xdg-terminal-exec -e omni-profile doctor || omni-profile doctor)")
  }

  IpcHandler {
    target: "omni.mode-indicator"
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function cycle(): void { root.cycleMode(false) }
    function cycleReverse(): void { root.cycleMode(true) }
    function refresh(): void {
      stateFile.reload()
      listProcess.running = true
      hintsProcess.running = true
    }
    function openPanel(): void { root.openPanel() }
    function closePanel(): void { root.closePanel() }
    function togglePanel(): void { root.togglePanel() }
    function getMode(): string { return root.currentMode }
    function switchMode(mode: string): void { root.switchMode(mode) }
    function getWindowPolicy(): string { return root.windowPolicy }
    function getEffectiveWindowMode(): string { return root.effectiveWindowMode }
    function setWindowPolicy(policy: string): void { root.setPolicy(policy) }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.engineRunning ? root.currentIcon : Icons.glyph.pause
    tooltipText: root.engineRunning
      ? ("OmniPal: " + root.currentName + "\n生效快捷键: " + root.activeBindingsCount + "\n窗口策略: " + Model.resolvePolicyName(root.windowPolicy) + " (" + root.effectiveWindowMode + ")\n左键: 轮转模式 | 右键: 快捷控制面板 | 中键: 设置")
      : "OmniPal Engine 未运行\n左键: 启动/切换 | 右键: 快捷控制面板"

    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.togglePanel()
      } else if (b === Qt.MiddleButton) {
        root.openSettings()
      } else {
        root.cycleMode(false)
      }
    }
  }

  // 快捷控制面板 — native KeyboardPanel (same chrome/positioning/dismissal as omarchy.power).
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(keyCatcher.implicitHeight)

    // Direct child (default contentItem) works on 4.0.4 and main.
    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      implicitHeight: panelLayout.implicitHeight
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.closePanel()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) { if ((t === "u" || t === "U") && root.undoMode !== "") root.undoSwitch() }

      Column {
        id: panelLayout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.spacing.md

        // 1. Hero 概览区
        PanelHero {
          id: hero
          foreground: Commons.Color.popups.text
          title: root.engineRunning ? root.currentName : "OmniPal Engine 未运行"
          detail: root.engineRunning ? root.currentBrief : ""
          meta: root.engineRunning
            ? ((root.activeBindingsCount > 0 ? (root.activeBindingsCount + " 项快捷键已覆盖") : "原生零覆盖")
               + "  •  " + (root.compositorConnected ? "Hyprland 连通" : "未连接 Compositor"))
            : "引擎已停止"
          iconComponent: Text {
            textFormat: Text.PlainText
            text: root.engineRunning ? root.currentIcon : Icons.glyph.pause
            color: Commons.Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.display
          }
        }

        // Status line: foreground text, urgent only when something is wrong.
        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: (root.engineRunning ? "engine " + (root.engineStatus || "running") : "engine stopped")
            + "  ·  " + (root.compositorConnected ? "hyprland connected" : "hyprland disconnected")
          color: (!root.engineRunning || !root.compositorConnected) ? Commons.Color.urgent : Qt.darker(Commons.Color.popups.text, 1.4)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        // 模式切换撤销提示（~5s，点击或按 U 撤销）
        Text {
          width: parent.width
          visible: root.toastText !== ""
          textFormat: Text.PlainText
          text: root.toastText
          color: Commons.Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          leftPadding: Style.spacing.controlPaddingX
          MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.undoSwitch() }
        }

        PanelSeparator { foreground: Commons.Color.popups.text }

        // 2. 肌肉记忆模式选择区 (PROFILES)
        PanelSectionHeader {
          text: "模式"
          foreground: Commons.Color.popups.text
        }

        Column {
          width: parent.width
          spacing: Style.spacing.xxs

          Repeater {
            model: root.profiles

            delegate: Button {
              id: profileRow
              required property var modelData
              required property int index
              readonly property bool isActive: root.engineRunning && root.currentMode === modelData.id

              width: parent.width
              leftAlign: true
              iconText: Icons.mode(modelData.id)
              text: Model.resolveName(modelData)
              selected: isActive
              hasCursor: root.cursorActive && root.cursorIndex === index
              foreground: Commons.Color.popups.text
              onHovered: function(on) { root.hoverRow(profileRow.index, on) }
              onClicked: root.switchModeWithUndo(profileRow.modelData.id)

              RowHint {
                text: profileRow.isActive ? "active" : String(profileRow.modelData.bindings_count)
                color: profileRow.isActive ? Commons.Color.accent : Qt.darker(Commons.Color.popups.text, 1.4)
              }
            }
          }
        }

        PanelSeparator { foreground: Commons.Color.popups.text }

        // 3. 窗口策略控制区 (WINDOW POLICY)
        Item {
          width: parent.width
          implicitHeight: Math.max(wpHeader.implicitHeight, effPolicyBadge.implicitHeight)

          PanelSectionHeader {
            id: wpHeader
            text: "窗口策略"
            foreground: Commons.Color.popups.text
            anchors.left: parent.left
            anchors.right: effPolicyBadge.left
            anchors.rightMargin: Style.spacing.sm
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
          }

          Text {
            id: effPolicyBadge
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "生效: " + (root.effectiveWindowMode === "floating" ? "浮动" : "平铺")
            color: Qt.darker(Commons.Color.popups.text, 1.4)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        ButtonGroup {
          id: policyGroup
          width: parent.width
          focusable: false
          options: root.policyOptions.map(function(p) { return { value: p.id, label: p.name, icon: p.icon } })
          value: Model.normalizePolicy(root.windowPolicy)
          cursorIndex: (root.cursorActive && root.cursorIndex === root.policyRowIndex)
            ? (root.policyCursor >= 0 ? root.policyCursor : Math.max(0, root.policySelectedIndex())) : -1
          foreground: Commons.Color.popups.text
          background: "transparent"
          fontSize: Style.font.caption
          onChanged: function(v) { root.setPolicy(v) }
          onHovered: function(i, on) {
            if (!on) return
            root.hoverRow(root.policyRowIndex, true)
            root.policyCursor = i
          }
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: Model.resolvePolicyDesc(root.windowPolicy, root.currentMode)
          color: Qt.darker(Commons.Color.popups.text, 1.4)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        PanelSeparator { foreground: Commons.Color.popups.text }

        // 4. 快捷功能入口 (ACTIONS)
        PanelSectionHeader {
          text: "快捷入口"
          foreground: Commons.Color.popups.text
        }

        Repeater {
          model: root.actionRows
          delegate: ActionRow {
            required property var modelData
            required property int index
            row: modelData
            rowIndex: root.actionBase + index
            hint: root.actionHints[modelData.hintKey] || ""
          }
        }

        PanelSeparator { foreground: Commons.Color.popups.text }

        // 5. 系统与控制 (SYSTEM)
        PanelSectionHeader {
          text: "系统"
          foreground: Commons.Color.popups.text
        }

        Repeater {
          model: root.systemRows
          delegate: ActionRow {
            required property var modelData
            required property int index
            row: modelData
            rowIndex: root.systemBase + index
            hint: modelData.hint || ""
          }
        }
      }
    }
  }

  // List row = native Button (hover/cursor/selected fills come from Style state tokens).
  component ActionRow: Button {
    id: rowItem
    property var row: ({})
    property int rowIndex: -1
    property string hint: ""

    width: parent ? parent.width : implicitWidth
    leftAlign: true
    iconText: row.icon || ""
    text: row.label || ""
    foreground: Commons.Color.popups.text
    hasCursor: root.cursorActive && root.cursorIndex === rowIndex
    onHovered: function(on) { root.hoverRow(rowItem.rowIndex, on) }
    onClicked: root.runAction(rowItem.row)

    RowHint {
      visible: rowItem.hint !== ""
      text: rowItem.hint
    }
  }

  // Right-aligned caption inside a Button row (e.g. the bound key / count).
  component RowHint: Text {
    textFormat: Text.PlainText
    anchors.right: parent.right
    anchors.rightMargin: Style.spacing.controlPaddingX
    anchors.verticalCenter: parent.verticalCenter
    color: Qt.darker(Commons.Color.popups.text, 1.4)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

}
