import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// OmniPal 托盘模式指示器与右键快捷面板（omni.mode-indicator）
//
// 遵循 Omarchy Quickshell 规范：
// 1. 继承 BarWidget，嵌入 Omarchy Top Bar
// 2. 通过 FileView 监听 /run/user/1000/omnipal/state.json，毫秒级响应，零轮询开销
// 3. 左键：快速轮转切换模式 (omni-profile cycle)
//    右键：呼出/收起右键快捷控制面板 (PopupCard)
//    中键：呼出设置面板 (omarchy-shell shell toggle omni.settings)
// 4. 右键面板集成 PopupCard，支持外部点击自动收起，与 Omarchy 状态栏弹窗互斥协调
// 5. 模式数据 100% 来源单一事实源 (omni-profile list --json)
BarWidget {
  id: root
  moduleName: "omni.mode-indicator"

  property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/state.json"
  property string currentMode: "omarchy"
  property string currentName: "Omarchy 原生模式"
  property string currentIcon: "⊡"
  property string currentBrief: "OMA"
  property color currentColor: "#a3be8c"
  property int activeBindingsCount: 0
  property bool engineRunning: false
  property string engineStatus: "native"
  property bool panelOpen: false

  property var profiles: Model.fallbackProfiles()

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
      root.engineRunning = true
    } catch (e) {
      root.engineRunning = false
    }
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadState(text())
    onLoadFailed: root.engineRunning = false
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

  Component.onCompleted: {
    listProcess.running = true
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
    runCmd("omni-profile switch " + modeId)
  }

  function restoreBaseline() {
    runCmd("omni-profile restore")
  }

  function openCheatSheet() {
    runCmd("omarchy-shell shell toggle omni.cheat-sheet")
  }

  function openSettings() {
    runCmd("omarchy-shell shell toggle omni.settings")
  }

  function openOverview() {
    runCmd("omarchy-shell shell toggle omni.overview")
  }

  function triggerSnap() {
    runCmd("omarchy-shell shell toggle omni.snap-feedback")
  }

  function runDoctor() {
    runCmd("omni-profile doctor")
  }

  IpcHandler {
    target: "omni.mode-indicator"
    function cycle(): void { root.cycleMode(false) }
    function cycleReverse(): void { root.cycleMode(true) }
    function refresh(): void {
      stateFile.reload()
      listProcess.running = true
    }
    function openPanel(): void { root.openPanel() }
    function closePanel(): void { root.closePanel() }
    function togglePanel(): void { root.togglePanel() }
    function getMode(): string { return root.currentMode }
    function switchMode(mode: string): void { root.switchMode(mode) }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.engineRunning
      ? (root.currentIcon + " " + root.currentBrief)
      : "⊘ OFF"
    fontFamily: Style.font.family
    horizontalMargin: 8
    foreground: root.engineRunning ? root.currentColor : Color.dimmed
    tooltipText: root.engineRunning
      ? ("OmniPal: " + root.currentName + "\n生效快捷键: " + root.activeBindingsCount + "\n左键: 轮转模式 | 右键: 快捷菜单 | 中键: 设置")
      : "OmniPal Engine 未运行\n左键: 启动/切换 | 右键: 快捷菜单"

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
    borderColor: Qt.rgba(root.currentColor.r, root.currentColor.g, root.currentColor.b, 0.45)
    contentWidth: contextPopup.fittedContentWidth(Style.space(310))
    contentHeight: contextPopup.fittedContentHeight(panelLayout.implicitHeight)

    Column {
      id: panelLayout
      width: parent.width
      spacing: Style.space(6)

      // 1. Hero 概览区
      Item {
        width: parent.width
        implicitHeight: Math.max(heroIcon.implicitHeight, heroTextCol.implicitHeight) + Style.space(4)

        Text {
          id: heroIcon
          text: root.engineRunning ? root.currentIcon : "⊘"
          font.pixelSize: Style.font.title + Style.space(4)
          color: root.engineRunning ? root.currentColor : Color.dimmed
          anchors.left: parent.left
          anchors.leftMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
        }

        Column {
          id: heroTextCol
          anchors.left: heroIcon.right
          anchors.leftMargin: Style.space(8)
          anchors.right: closeBtn.left
          anchors.rightMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)

          Text {
            text: root.engineRunning ? root.currentName : "OmniPal Engine 未运行"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            elide: Text.ElideRight
            width: parent.width
          }

          Row {
            spacing: Style.space(4)

            Rectangle {
              width: Style.space(6)
              height: Style.space(6)
              radius: Style.space(3)
              color: root.engineRunning
                ? (root.engineStatus === "active" ? "#a3be8c" : "#88c0d0")
                : Color.dimmed
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              text: root.engineRunning
                ? (root.activeBindingsCount > 0 ? (root.activeBindingsCount + " 项快捷键已覆盖生效") : "原生快捷键已生效（零残留）")
                : "点击下方按钮尝试启动/切换"
              color: Qt.darker(Color.foreground, 1.4)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
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
          radius: Math.max(2, Style.cornerRadius)
          color: closeMouse.containsMouse ? Style.hoverFillFor(Color.foreground, Color.foreground) : "transparent"

          Text {
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

      // 2. 模式快速切换区 (PROFILES)
      PanelSectionHeader {
        text: "模式选择 (PROFILES)"
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
              radius: Math.max(2, Style.cornerRadius)
              color: rowMouse.containsMouse
                ? Style.hoverFillFor(Color.foreground, Color.accent)
                : (profileRow.isActive ? Qt.rgba(profileRow.itemColor.r, profileRow.itemColor.g, profileRow.itemColor.b, 0.12) : "transparent")
            }

            Text {
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
              text: profileRow.isActive ? "✓" : (profileRow.modelData.bindings_count + "项")
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
                root.closePanel()
              }
            }
          }
        }
      }

      PanelSeparator {
        foreground: Color.foreground
      }

      // 3. 快捷功能入口 (ACTIONS)
      PanelSectionHeader {
        text: "快捷入口 (ACTIONS)"
        foreground: Color.foreground
        fontFamily: Style.font.family
      }

      ActionRow {
        iconText: "📖"
        label: "快捷键速查表 (Cheat Sheet)"
        hint: "Super + /"
        onTriggered: {
          root.openCheatSheet()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "⚙️"
        label: "OmniPal 控制中心 (Settings)"
        hint: "Super + ,"
        onTriggered: {
          root.openSettings()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "🗂️"
        label: "任务视图 (Task View)"
        hint: "Super + Tab"
        onTriggered: {
          root.openOverview()
          root.closePanel()
        }
      }

      ActionRow {
        iconText: "🪟"
        label: "触发布局吸附 (Snap Layout)"
        hint: "Super + Z"
        onTriggered: {
          root.triggerSnap()
          root.closePanel()
        }
      }

      PanelSeparator {
        foreground: Color.foreground
      }

      // 4. 系统与控制 (SYSTEM)
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
      radius: Math.max(2, Style.cornerRadius)
      color: actionMouse.containsMouse ? Style.hoverFillFor(Color.foreground, Color.accent) : "transparent"
    }

    Text {
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
