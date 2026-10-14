import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.Commons
import qs.Ui
import "Model.js" as Model
import "Tokens.js" as Tokens

// OmniPal 托盘模式指示器与右键快捷控制面板（omni.mode-indicator）
//
// 遵循 Omarchy Quickshell 规范：
// 1. 继承 BarWidget，嵌入 Omarchy Top Bar
// 2. 通过 FileView 监听 /run/user/1000/omnipal/state.json，毫秒级响应，零轮询开销
// 3. 左键：快速轮转切换模式 (omni-profile cycle)
//    右键：呼出/收起右键快捷控制面板 (PopupCard)
//    中键：呼出设置面板 (omarchy-shell shell toggle omni.settings)
// 4. 右键面板集成 PopupCard，包含肌肉记忆模式与窗口策略（平铺/浮动/跟随模式）控制
// 5. 支持外部点击自动收起（HyprlandFocusGrab），与 Omarchy 状态栏弹窗互斥协调
// 6. 模式与策略数据 100% 来源单一事实源 (omni-profile / state.json)
BarWidget {
  id: root

  // ---- Omarchy theme: Tokens.js is the single source of truth -------------
  // Follows the current Omarchy theme at runtime (colors.toml), tokyo-night fallback.
  property var themePalette: Tokens.fallback
  readonly property var modeColors: Tokens.modeColors(themePalette)
  readonly property var theme: Tokens.build(Color, themePalette)
  FileView {
    id: omniThemeFile
    property bool legacy: false
    path: (Quickshell.env("HOME") || "") + (legacy ? Tokens.themeFiles.legacyRel : Tokens.themeFiles.stateRel)
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.themePalette = Tokens.mergePalette(Tokens.parseColorsToml(text()))
    onLoadFailed: if (!legacy) legacy = true
  }
  moduleName: "omni.mode-indicator"

  property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/state.json"
  property string currentMode: "omarchy"
  property string currentName: "Omarchy 原生模式"
  property string currentIcon: "⊡"
  property string currentBrief: "OMA"
  property color currentColor: root.modeColors.omarchy
  property int activeBindingsCount: 0
  property bool engineRunning: false
  property string engineStatus: "native"
  property bool panelOpen: false
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
      root.currentIcon = (data.display && data.display.icon) || Model.defaultIcon(root.currentMode)
      root.currentBrief = (data.display && data.display.brief) || Model.defaultBrief(root.currentMode)
      root.currentColor = (data.display && data.display.color) || Model.defaultColor(root.currentMode)
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
      onStreamFinished: function(raw) {
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
      onStreamFinished: function(raw) {
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

  function openPanel() {
    root.panelOpen = true
    if (!listProcess.running) listProcess.running = true
    if (!hintsProcess.running) hintsProcess.running = true
    if (root.bar && typeof root.bar.requestPopout === "function") {
      root.bar.requestPopout(root)
    }
  }

  function closePanel() {
    root.panelOpen = false
    if (root.bar && typeof root.bar.releasePopout === "function") {
      root.bar.releasePopout(root)
    }
  }

  function togglePanel() {
    if (root.panelOpen) root.closePanel()
    else root.openPanel()
  }

  function close() {
    root.closePanel()
  }

  function cycleMode(reverse) {
    var cmd = reverse ? "omni-profile cycle --reverse" : "omni-profile cycle"
    runCmd(cmd)
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
        root.currentIcon = Model.resolveIcon(p)
        root.currentBrief = Model.resolveBrief(p)
        root.currentColor = Model.resolveColor(p)
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
    root.currentIcon = "⊡"
    root.currentBrief = "OMA"
    root.currentColor = root.modeColors.omarchy
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
    text: root.engineRunning ? root.currentIcon : "⊘"
    foreground: root.engineRunning ? root.currentColor : Color.muted
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

  // 右键快捷控制面板 (Omarchy PopupCard)
  PopupCard {
    id: contextPopup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.panelOpen
    triggerMode: "click"
    padding: Style.space(8)
    borderColor: Tokens.alpha(root.currentColor, 0.45)
    contentWidth: contextPopup.fittedContentWidth(Style.space(320))
    contentHeight: contextPopup.fittedContentHeight(panelLayout.implicitHeight)

    Column {
      id: panelLayout
      width: parent.width
      spacing: Style.space(6)

      // 1. Hero 概览区
      Item {
        width: parent.width
        implicitHeight: Math.max(heroBox.implicitHeight, heroTextCol.implicitHeight) + Style.space(2)

        Row {
          id: heroBox
          anchors.left: parent.left
          anchors.leftMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter

          Rectangle {
            width: Style.space(34)
            height: Style.space(34)
            implicitWidth: width
            implicitHeight: height
            radius: Tokens.corner(Style)
            color: root.engineRunning
              ? Tokens.alpha(root.currentColor, 0.15)
              : Tokens.alpha(Color.foreground, 0.08)
            border.width: 1
            border.color: root.engineRunning
              ? Tokens.alpha(root.currentColor, 0.4)
              : Tokens.alpha(Color.foreground, 0.15)

            Text {
              font.family: Style.font.family
              anchors.centerIn: parent
              text: root.engineRunning ? root.currentIcon : "⊘"
              font.pixelSize: Style.font.title
              color: root.engineRunning ? root.currentColor : Color.muted
            }
          }
        }

        Column {
          id: heroTextCol
          anchors.left: heroBox.right
          anchors.leftMargin: Style.space(8)
          anchors.right: closeBtn.left
          anchors.rightMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(3)

          Row {
            width: parent.width
            spacing: Style.space(6)

            Text {
              text: root.engineRunning ? root.currentName : "OmniPal Engine 未运行"
              color: Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              elide: Text.ElideRight
              anchors.verticalCenter: parent.verticalCenter
            }

            Rectangle {
              visible: root.engineRunning
              height: Style.space(16)
              width: heroBriefText.implicitWidth + Style.space(8)
              radius: Tokens.corner(Style)
              color: Tokens.alpha(root.currentColor, 0.18)
              anchors.verticalCenter: parent.verticalCenter

              Text {
                id: heroBriefText
                anchors.centerIn: parent
                text: root.currentBrief
                color: root.currentColor
                font.family: Style.font.family
                font.pixelSize: Style.font.caption - 1
                font.bold: true
              }
            }
          }

          Row {
            spacing: Style.space(6)

            // 快捷键覆盖状态
            Row {
              spacing: Style.space(3)
              anchors.verticalCenter: parent.verticalCenter

              Rectangle {
                width: Style.space(6)
                height: Style.space(6)
                radius: Tokens.corner(Style)
                color: root.engineRunning
                  ? (root.engineStatus === "active" ? root.theme.ok : root.theme.accent)
                  : Color.muted
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                text: root.engineRunning
                  ? (root.activeBindingsCount > 0 ? (root.activeBindingsCount + " 项快捷键已覆盖") : "原生零覆盖")
                  : "引擎已停止"
                color: Qt.darker(Color.foreground, 1.4)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }

            // 分隔圆点
            Text {
              font.family: Style.font.family
              text: "•"
              color: Qt.darker(Color.foreground, 1.8)
              font.pixelSize: Style.font.caption
              anchors.verticalCenter: parent.verticalCenter
            }

            // Compositor 连通状态
            Row {
              spacing: Style.space(3)
              anchors.verticalCenter: parent.verticalCenter

              Rectangle {
                width: Style.space(6)
                height: Style.space(6)
                radius: Tokens.corner(Style)
                color: root.compositorConnected ? root.theme.ok : root.theme.danger
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                text: root.compositorConnected ? "Hyprland 连通" : "未连接 Compositor"
                color: root.compositorConnected ? Qt.darker(Color.foreground, 1.4) : root.theme.danger
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }
          }
        }

        Rectangle {
          id: closeBtn
          anchors.right: parent.right
          anchors.rightMargin: Style.space(2)
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(22)
          height: Style.space(22)
          radius: Tokens.corner(Style)
          color: closeMouse.containsMouse ? Style.hoverFillFor(Color.foreground, Color.foreground) : "transparent"

          Text {
            font.family: Style.font.family
            text: "✕"
            color: closeMouse.containsMouse ? Color.accent : Qt.darker(Color.foreground, 1.3)
            font.pixelSize: Style.font.caption
            anchors.centerIn: parent
          }

          MouseArea {
            id: closeMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.closePanel()
          }
        }
      }

      PanelSeparator {
        foreground: Color.foreground
      }

      // 2. 肌肉记忆模式选择区 (PROFILES)
      PanelSectionHeader {
        text: "肌肉记忆模式 (PROFILES)"
        foreground: Color.foreground
        fontFamily: Style.font.family
      }

      Column {
        width: parent.width
        spacing: Style.space(2)

        Repeater {
          model: root.profiles

          delegate: Item {
            id: profileRow
            required property var modelData
            required property int index
            width: parent.width
            implicitHeight: Style.space(28)

            readonly property bool isActive: root.engineRunning && root.currentMode === modelData.id
            readonly property color itemColor: Model.resolveColor(modelData)

            Rectangle {
              anchors.fill: parent
              radius: Tokens.corner(Style)
              color: rowMouse.containsMouse
                ? Style.hoverFillFor(Color.foreground, Color.accent)
                : (profileRow.isActive ? Tokens.alpha(profileRow.itemColor, 0.12) : "transparent")
            }

            Rectangle {
              visible: profileRow.isActive
              width: Style.space(3)
              height: parent.height - Style.space(6)
              radius: Tokens.corner(Style)
              color: profileRow.itemColor
              anchors.left: parent.left
              anchors.leftMargin: Style.space(2)
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              font.family: Style.font.family
              id: pIcon
              text: Model.resolveIcon(profileRow.modelData)
              color: profileRow.itemColor
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              anchors.left: parent.left
              anchors.leftMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              text: Model.resolveName(profileRow.modelData)
              color: profileRow.isActive ? profileRow.itemColor : Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: profileRow.isActive
              anchors.left: pIcon.right
              anchors.leftMargin: Style.space(8)
              anchors.right: pRightBadge.left
              anchors.rightMargin: Style.space(6)
              anchors.verticalCenter: parent.verticalCenter
              elide: Text.ElideRight
            }

            Text {
              id: pRightBadge
              anchors.right: parent.right
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              text: profileRow.isActive ? "✓ 已启用" : (profileRow.modelData.bindings_count + "项")
              color: profileRow.isActive ? profileRow.itemColor : Qt.darker(Color.foreground, 1.4)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: profileRow.isActive
            }

            MouseArea {
              id: rowMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                root.switchMode(profileRow.modelData.id)
              }
            }
          }
        }
      }

      PanelSeparator {
        foreground: Color.foreground
      }

      // 3. 窗口策略控制区 (WINDOW POLICY)
      Item {
        width: parent.width
        implicitHeight: Math.max(wpHeader.implicitHeight, Style.space(16))

        PanelSectionHeader {
          id: wpHeader
          text: "窗口策略 (WINDOW POLICY)"
          foreground: Color.foreground
          fontFamily: Style.font.family
          anchors.left: parent.left
          anchors.right: effPolicyBadge.left
          anchors.rightMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
          elide: Text.ElideRight
        }

        Rectangle {
          id: effPolicyBadge
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          height: Style.space(16)
          width: effPolicyText.implicitWidth + Style.space(8)
          implicitWidth: width
          implicitHeight: height
          radius: Tokens.corner(Style)
          color: Tokens.alpha(root.currentColor, 0.18)

          Text {
            id: effPolicyText
            anchors.centerIn: parent
            text: "生效: " + (root.effectiveWindowMode === "floating" ? "浮动" : "平铺")
            color: root.currentColor
            font.family: Style.font.family
            font.pixelSize: Style.font.caption - 1
            font.bold: true
          }
        }
      }

      Column {
        width: parent.width
        spacing: Style.space(4)

        // 分段选择器 (Segmented Selector)
        Rectangle {
          width: parent.width
          height: Style.space(32)
          implicitHeight: height
          radius: Tokens.corner(Style)
          color: Tokens.alpha(Color.foreground, 0.06)
          border.width: 1
          border.color: Tokens.alpha(Color.foreground, 0.1)

          Row {
            anchors.fill: parent
            anchors.margins: Style.space(2)
            spacing: Style.space(2)

            Repeater {
              model: root.policyOptions

              delegate: Item {
                id: policySeg
                required property var modelData
                required property int index

                width: {
                  if (!root.policyOptions || root.policyOptions.length === 0) return 0
                  var count = root.policyOptions.length
                  var totalGap = Style.space(2) * (count - 1)
                  var segW = Math.floor((parent.width - totalGap) / count)
                  return (index === count - 1) ? Math.max(0, parent.width - totalGap - segW * (count - 1)) : segW
                }
                height: parent.height

                readonly property bool isSelected: Model.normalizePolicy(root.windowPolicy) === modelData.id

                Rectangle {
                  anchors.fill: parent
                  radius: Tokens.corner(Style)
                  color: policySeg.isSelected
                    ? root.theme.selectedFill
                    : (policyMouse.containsMouse ? Style.hoverFillFor(Color.foreground, Color.accent) : "transparent")
                  border.width: policySeg.isSelected ? Tokens.border.focus : 0
                  border.color: policySeg.isSelected
                    ? root.theme.selectedBorder
                    : "transparent"

                  Row {
                    anchors.centerIn: parent
                    spacing: Style.space(4)

                    Text {
                      font.family: Style.font.family
                      text: policySeg.modelData.icon
                      color: policySeg.isSelected ? root.theme.selectedText : (policyMouse.containsMouse ? Color.accent : Qt.darker(Color.foreground, 1.2))
                      font.pixelSize: Style.font.bodySmall
                    }

                    Text {
                      text: policySeg.modelData.name
                      color: policySeg.isSelected ? root.theme.selectedText : (policyMouse.containsMouse ? Color.accent : Color.foreground)
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      font.bold: policySeg.isSelected
                    }
                  }

                  MouseArea {
                    id: policyMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                      root.setPolicy(policySeg.modelData.id)
                    }
                  }
                }
              }
            }
          }
        }

        // 当前策略说明提示条
        Rectangle {
          width: parent.width
          implicitHeight: Style.space(22)
          radius: Tokens.corner(Style)
          color: Tokens.alpha(Color.foreground, 0.03)

          Item {
            anchors.fill: parent
            anchors.leftMargin: Style.space(6)
            anchors.rightMargin: Style.space(6)

            Text {
              font.family: Style.font.family
              id: infoIcon
              text: "ℹ"
              color: root.currentColor
              font.pixelSize: Style.font.caption
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              id: policyHintText
              anchors.left: infoIcon.right
              anchors.leftMargin: Style.space(6)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: Model.resolvePolicyDesc(root.windowPolicy, root.currentMode)
              color: Qt.darker(Color.foreground, 1.3)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption - 1
              elide: Text.ElideRight
            }
          }
        }
      }

      PanelSeparator {
        foreground: Color.foreground
      }

      // 4. 快捷功能入口 (ACTIONS)
      PanelSectionHeader {
        text: "快捷入口 (ACTIONS)"
        foreground: Color.foreground
        fontFamily: Style.font.family
      }

      ActionRow {
        iconText: "📖"
        label: "快捷键速查表 (Cheat Sheet)"
        hint: root.actionHints["cheat_sheet"] || ""
        onTriggered: {
          root.openCheatSheet()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "⚙️"
        label: "OmniPal 控制中心 (Settings)"
        hint: root.actionHints["omni_settings"] || ""
        onTriggered: {
          root.openSettings()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "🪟"
        label: "触发布局吸附 (Snap Layout)"
        hint: root.actionHints["snap_layouts"] || ""
        onTriggered: {
          root.triggerSnap()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "🗂️"
        label: "多任务空间概览 (Overview)"
        hint: root.actionHints["task_view"] || ""
        onTriggered: {
          root.openOverview()
          root.closePanel()
        }
      }

      PanelSeparator {
        foreground: Color.foreground
      }

      // 5. 系统与控制 (SYSTEM)
      PanelSectionHeader {
        text: "系统与控制 (SYSTEM)"
        foreground: Color.foreground
        fontFamily: Style.font.family
      }

      ActionRow {
        iconText: "↻"
        label: "轮转切换下一模式 (Cycle Next)"
        hint: "Cycle"
        onTriggered: {
          root.cycleMode(false)
        }
      }

      ActionRow {
        iconText: "↺"
        label: "还原原生快捷键 (Restore Baseline)"
        hint: "0 覆盖"
        onTriggered: {
          root.restoreBaseline()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "🩺"
        label: "运行系统健康诊断 (Doctor)"
        hint: "Doctor"
        onTriggered: {
          root.runDoctor()
          root.closePanel()
        }
      }
    }
  }

  // 行组件封装
  component ActionRow: Item {
    id: rowItem
    property string iconText: ""
    property string label: ""
    property string hint: ""
    signal triggered()

    width: parent.width
    implicitHeight: Style.space(28)

    Rectangle {
      anchors.fill: parent
      radius: Tokens.corner(Style)
      color: actionMouse.containsMouse ? Style.hoverFillFor(Color.foreground, Color.accent) : "transparent"
    }

    Text {
      font.family: Style.font.family
      id: rowIcon
      text: rowItem.iconText
      font.pixelSize: Style.font.bodySmall
      anchors.left: parent.left
      anchors.leftMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      text: rowItem.label
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      anchors.left: rowIcon.right
      anchors.leftMargin: Style.space(8)
      anchors.right: hintText.left
      anchors.rightMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      elide: Text.ElideRight
    }

    Text {
      id: hintText
      visible: rowItem.hint !== ""
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      text: rowItem.hint
      color: Qt.darker(Color.foreground, 1.4)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    MouseArea {
      id: actionMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: rowItem.triggered()
    }
  }
}
