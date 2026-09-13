import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// OmniPal 状态栏模式指示器（omni.mode-indicator）
//
// 遵循 Omarchy Quickshell 规范：
// 1. 继承 BarWidget，嵌入 Omarchy Top Bar
// 2. 通过 FileView 监听 /run/user/1000/omnipal/state.json，毫秒级响应，零轮询开销
// 3. 左键：循环切换模式 (omni-profile cycle)
//    右键：呼出快捷键速查表 (omarchy-shell shell toggle omni.cheat-sheet)
//    中键：呼出设置面板 (omarchy-shell shell toggle omni.settings)
// 4. 状态异常或 Engine 未启动时优雅降级显示 ⊘ OFF
BarWidget {
  id: root
  moduleName: "omni.mode-indicator"

  property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/state.json"
  property string currentMode: "omarchy"
  property string currentName: "Omarchy 原生模式"
  property int activeBindingsCount: 0
  property bool engineRunning: false

  readonly property var modeIcons: ({
    "windows": "⊞",
    "mac":     "◆",
    "omarchy": "⊡"
  })

  readonly property var modeLabels: ({
    "windows": "WIN",
    "mac":     "MAC",
    "omarchy": "OMA"
  })

  readonly property var modeNames: ({
    "windows": "Windows 11 习惯模式",
    "mac":     "macOS 习惯模式",
    "omarchy": "Omarchy 原生模式"
  })

  readonly property var modeColors: ({
    "windows": "#3892d6",
    "mac":     "#d8dee9",
    "omarchy": "#a3be8c"
  })

  function loadState(rawText) {
    if (!rawText || rawText.trim() === "") {
      root.engineRunning = false
      return
    }
    try {
      var data = JSON.parse(rawText)
      root.currentMode = data.mode || "omarchy"
      root.currentName = data.name || root.modeNames[root.currentMode] || root.currentMode
      root.activeBindingsCount = data.active_bindings_count || 0
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

  IpcHandler {
    target: "omni.mode-indicator"
    function cycle(): void { root.cycleMode() }
    function refresh(): void { stateFile.reload() }
  }

  function cycleMode() {
    if (root.bar && typeof root.bar.run === "function") {
      root.bar.run("omni-profile cycle")
    } else {
      Quickshell.execDetached(["omni-profile", "cycle"])
    }
  }

  function openCheatSheet() {
    if (root.bar && typeof root.bar.run === "function") {
      root.bar.run("omarchy-shell shell toggle omni.cheat-sheet")
    } else {
      Quickshell.execDetached(["omarchy-shell", "shell", "toggle", "omni.cheat-sheet"])
    }
  }

  function openSettings() {
    if (root.bar && typeof root.bar.run === "function") {
      root.bar.run("omarchy-shell shell toggle omni.settings")
    } else {
      Quickshell.execDetached(["omarchy-shell", "shell", "toggle", "omni.settings"])
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.engineRunning
      ? (root.modeIcons[root.currentMode] || "◇") + " " + (root.modeLabels[root.currentMode] || (root.currentMode.length > 3 ? root.currentMode.substring(0, 3).toUpperCase() : root.currentMode.toUpperCase()))
      : "⊘ OFF"
    fontFamily: Style.font.family
    horizontalMargin: 8
    foreground: root.engineRunning ? (root.modeColors[root.currentMode] || Color.foreground) : Color.dimmed
    tooltipText: root.engineRunning
      ? ("OmniPal: " + root.currentName + "\n生效快捷键: " + root.activeBindingsCount + "\n左键: 循环切换模式\n右键: 快捷键速查表\n中键: 打开设置")
      : "OmniPal Engine 未运行\n点击以尝试切换或启动"

    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.openCheatSheet()
      } else if (b === Qt.MiddleButton) {
        root.openSettings()
      } else {
        root.cycleMode()
      }
    }
  }
}
