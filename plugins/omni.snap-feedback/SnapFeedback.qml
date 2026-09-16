import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// OmniPal 窗口吸附反馈与 Snap Layouts 布局选择器 (omni.snap-feedback)
//
// 双模架构：
// 1. 被动 HUD 模式 (interactive: false)：
//    快捷键直接触发（如 Super + 左右上下），无焦点、毫秒级浮现半透明几何轮廓与物理像素徽标，400ms 自动淡出。
// 2. 交互布局选择器模式 (interactive: true)：
//    通过 Super + Z 呼出，提供类似 Windows 11 的 6 大分屏模板：
//    • 阶梯 1（模板选择）：按 1–6 选定模板并显示各分区数字微标 [1]、[2]...
//    • 阶梯 2（分区选择）：直接按数字键盲操即刻吸附（如 Super+Z -> 2 -> 1）！
//    • 键盘全流：支持方向键在 2x3 网格及分区中穿梭、Tab 循环、回车吸附、Esc 优雅回退与关闭。
//    • 鼠标悬停实时全屏几何投影并展示物理像素分辨率。
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property bool interactive: false
  property string zone: "left"
  property string hoveredZone: ""

  readonly property color snapColor: (Color && Color.accent) ? Color.accent : "#3b82f6"

  // 键盘与焦点导航状态
  property int focusedTemplateIndex: -1  // -1 表示未选模板，0~5 表示当前选中的模板
  property int focusedSlotIndex: 0       // 当前模板内选中的分区索引

  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.snap-feedback"

  property var templates: Model.TEMPLATES
  readonly property var effectiveTemplates: (root.templates && root.templates.length > 0) ? root.templates : Model.TEMPLATES

  readonly property var currentReserved: {
    var pos = (Style.bar && Style.bar.position) || "top"
    var sz = (Style.bar && Style.bar.sizeHorizontal > 0) ? Style.bar.sizeHorizontal : 34
    return {
      top: pos === "top" ? sz : 0,
      bottom: pos === "bottom" ? sz : 0,
      left: pos === "left" ? sz : 0,
      right: pos === "right" ? sz : 0
    }
  }
  readonly property int reservedTop: root.currentReserved.top

  property string targetWindowAddress: ""
  property string targetWindowTitle: ""
  property string targetWindowClass: ""

  function open(payloadJson) {
    var p = ({})
    try { p = JSON.parse(payloadJson || "{}") } catch(e) { p = ({}) }
    root.targetWindowAddress = (p.target_window ? String(p.target_window).trim() : "")
    root.targetWindowTitle = (p.target_title ? String(p.target_title).trim() : "")
    root.targetWindowClass = (p.target_class ? String(p.target_class).trim() : "")

    if (p.interactive === true || p.zone === "layouts" || p.zone === "picker" || (!p.zone && p.interactive !== false)) {
      root.interactive = true
      root.hoveredZone = ""
      root.focusedTemplateIndex = -1
      root.focusedSlotIndex = 0
      root.opened = true
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    } else {
      root.interactive = false
      root.hoveredZone = ""
      root.focusedTemplateIndex = -1
      root.focusedSlotIndex = 0
      root.zone = (p.zone ? String(p.zone).toLowerCase() : "left")
      root.opened = true
      fadeAnim.restart()
      dismissTimer.restart()
    }
  }

  function close() {
    root.opened = false
    root.interactive = false
    root.hoveredZone = ""
    root.focusedTemplateIndex = -1
    root.focusedSlotIndex = 0
    root.targetWindowAddress = ""
    root.targetWindowTitle = ""
    root.targetWindowClass = ""
  }

  function dismiss() {
    root.opened = false
    root.interactive = false
    root.hoveredZone = ""
    root.focusedTemplateIndex = -1
    root.focusedSlotIndex = 0
    root.targetWindowAddress = ""
    root.targetWindowTitle = ""
    root.targetWindowClass = ""
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function executeSnap(targetZone) {
    if (!targetZone) return
    var addrArg = root.targetWindowAddress ? (" " + root.targetWindowAddress) : ""
    var cmd = "which omni-profile >/dev/null 2>&1 && omni-profile snap " + targetZone + addrArg + " --no-hud || \"$HOME/.local/bin/omni-profile\" snap " + targetZone + addrArg + " --no-hud"
    if (typeof Quickshell.execDetached === "function") {
      Quickshell.execDetached(["sh", "-c", cmd])
    } else {
      dispatchProc.command = ["sh", "-c", cmd]
      dispatchProc.running = true
    }
    root.dismiss()
  }

  // IPC 接口 (唯一的外部唤出与状态指令通道，杜绝双重监听)
  IpcHandler {
    target: "omni.snap-feedback"
    function snap(z: string): void {
      root.open(JSON.stringify({ zone: z, interactive: false }))
    }
    function layouts(): void {
      root.open(JSON.stringify({ interactive: true }))
    }
    function open(payloadJson: string): void {
      root.open(payloadJson)
    }
    function close(): void {
      root.dismiss()
    }
  }

  // 动态加载单一事实源规范布局缓存 (由 Engine 在 tmpfs 维护)
  property string snapLayoutsPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/omnipal/snap_layouts.json"
  FileView {
    id: layoutsFile
    path: root.snapLayoutsPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: {
      Model.loadSchemaJson(text())
      root.templates = Model.TEMPLATES
    }
    onFileChanged: {
      reload()
      Model.loadSchemaJson(text())
      root.templates = Model.TEMPLATES
    }
  }

  Process {
    id: initSchemaProc
    command: ["omni-profile", "snap-layouts", "--json"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        if (text && text.trim() !== "") {
          Model.loadSchemaJson(text)
          root.templates = Model.TEMPLATES
        }
      }
    }
  }

  Component.onCompleted: {
    if (!root.templates || root.templates.length === 0) {
      initSchemaProc.running = true
    }
  }

  Timer {
    id: dismissTimer
    interval: 420
    repeat: false
    onTriggered: {
      if (!root.interactive) root.dismiss()
    }
  }

  Process {
    id: dispatchProc
    command: ["true"]
    running: false
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omni-snap-feedback"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: (root.opened && root.interactive) ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    Item {
      id: inputLayer
      anchors.fill: parent
    }
    mask: Region { item: root.interactive ? inputLayer : null }

    // 交互模式暗色全屏遮罩
    Rectangle {
      anchors.fill: parent
      visible: root.interactive
      color: Util.alpha(Color.menu.scrim || "#000000", 0.55)
      opacity: root.interactive ? 1.0 : 0.0
      Behavior on opacity { NumberAnimation { duration: 120 } }

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    // 全局键盘捕获器（交互模式专用）
    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: root.interactive

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        // Esc 键：阶梯回退或退出
        if (event.key === Qt.Key_Escape) {
          if (root.focusedTemplateIndex >= 0) {
            root.focusedTemplateIndex = -1
            root.focusedSlotIndex = 0
            root.hoveredZone = ""
          } else {
            root.dismiss()
          }
          event.accepted = true
          return
        }

        // BackSpace 键：回退至模板选择
        if (event.key === Qt.Key_BackSpace) {
          if (root.focusedTemplateIndex >= 0) {
            root.focusedTemplateIndex = -1
            root.focusedSlotIndex = 0
            root.hoveredZone = ""
            event.accepted = true
            return
          }
        }

        // 数字键 1-6 处理 (Windows 11 Snap Layouts 核心两阶逻辑)
        if (event.key >= Qt.Key_1 && event.key <= Qt.Key_6) {
          var num = event.key - Qt.Key_1 + 1 // 1 ~ 6

          if (root.focusedTemplateIndex === -1) {
            // 阶段 1：未选模板时，按 1-6 选中对应模板，并默认聚焦到第 1 个分区
            var tIndex = num - 1
            if (tIndex >= 0 && tIndex < root.effectiveTemplates.length) {
              root.focusedTemplateIndex = tIndex
              root.focusedSlotIndex = 0
              root.hoveredZone = ""
              event.accepted = true
              return
            }
          } else {
            // 阶段 2：已选模板时
            var curTpl = root.effectiveTemplates[root.focusedTemplateIndex]
            if (curTpl && curTpl.slots) {
              var slotIdx = num - 1
              if (slotIdx >= 0 && slotIdx < curTpl.slots.length) {
                // 按下有效分区编号，立即吸附！
                root.executeSnap(curTpl.slots[slotIdx].id)
                event.accepted = true
                return
              } else {
                // 若输入的数字超出了当前模板的分区数，但属于 1-6，则快捷跳选至目标模板！
                var jumpIndex = num - 1
                if (jumpIndex >= 0 && jumpIndex < root.effectiveTemplates.length) {
                  root.focusedTemplateIndex = jumpIndex
                  root.focusedSlotIndex = 0
                  root.hoveredZone = ""
                  event.accepted = true
                  return
                }
              }
            }
          }
        }

        // 方向键左
        if (event.key === Qt.Key_Left) {
          if (root.focusedTemplateIndex === -1) {
            root.focusedTemplateIndex = 0
            root.focusedSlotIndex = 0
          } else {
            var tplLeft = root.effectiveTemplates[root.focusedTemplateIndex]
            if (tplLeft && tplLeft.slots && tplLeft.slots.length > 0) {
              root.focusedSlotIndex = (root.focusedSlotIndex - 1 + tplLeft.slots.length) % tplLeft.slots.length
            }
          }
          root.hoveredZone = ""
          event.accepted = true
          return
        }

        // 方向键右
        if (event.key === Qt.Key_Right) {
          if (root.focusedTemplateIndex === -1) {
            root.focusedTemplateIndex = 0
            root.focusedSlotIndex = 0
          } else {
            var tplRight = root.effectiveTemplates[root.focusedTemplateIndex]
            if (tplRight && tplRight.slots && tplRight.slots.length > 0) {
              root.focusedSlotIndex = (root.focusedSlotIndex + 1) % tplRight.slots.length
            }
          }
          root.hoveredZone = ""
          event.accepted = true
          return
        }

        // 方向键上
        if (event.key === Qt.Key_Up) {
          if (root.focusedTemplateIndex >= 3) {
            root.focusedTemplateIndex -= 3
            root.focusedSlotIndex = 0
          } else if (root.focusedTemplateIndex === -1) {
            root.focusedTemplateIndex = 0
            root.focusedSlotIndex = 0
          }
          root.hoveredZone = ""
          event.accepted = true
          return
        }

        // 方向键下
        if (event.key === Qt.Key_Down) {
          if (root.focusedTemplateIndex >= 0 && root.focusedTemplateIndex < 3) {
            root.focusedTemplateIndex += 3
            root.focusedSlotIndex = 0
          } else if (root.focusedTemplateIndex === -1) {
            root.focusedTemplateIndex = 0
            root.focusedSlotIndex = 0
          }
          root.hoveredZone = ""
          event.accepted = true
          return
        }

        // Tab 键
        if (event.key === Qt.Key_Tab) {
          if (root.focusedTemplateIndex === -1) {
            root.focusedTemplateIndex = 0
            root.focusedSlotIndex = 0
          } else {
            var tplTab = root.effectiveTemplates[root.focusedTemplateIndex]
            if (root.focusedSlotIndex + 1 < tplTab.slots.length) {
              root.focusedSlotIndex += 1
            } else {
              root.focusedTemplateIndex = (root.focusedTemplateIndex + 1) % root.effectiveTemplates.length
              root.focusedSlotIndex = 0
            }
          }
          root.hoveredZone = ""
          event.accepted = true
          return
        }

        // Enter / Space 键吸附当前聚焦项
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
          if (root.focusedTemplateIndex >= 0 && root.focusedTemplateIndex < root.effectiveTemplates.length) {
            var tplEnter = root.effectiveTemplates[root.focusedTemplateIndex]
            if (tplEnter && tplEnter.slots && tplEnter.slots.length > 0) {
              var sIdx = Math.max(0, Math.min(tplEnter.slots.length - 1, root.focusedSlotIndex))
              root.executeSnap(tplEnter.slots[sIdx].id)
              event.accepted = true
              return
            }
          } else {
            root.focusedTemplateIndex = 0
            root.focusedSlotIndex = 0
            root.hoveredZone = ""
            event.accepted = true
            return
          }
        }
      }
    }

    // 屏幕大背景几何落区投影（被动 HUD 模式 或 交互模式下悬停/键盘选中预览）
    Item {
      id: previewContainer
      anchors.fill: parent

      readonly property var activeTemplateSlots: {
        if (!root.interactive) return []
        var tIdx = root.focusedTemplateIndex
        if (tIdx === -1 && root.hoveredZone !== "") {
          for (var i = 0; i < root.effectiveTemplates.length; i++) {
            var tpl = root.effectiveTemplates[i]
            if (tpl && tpl.slots) {
              for (var j = 0; j < tpl.slots.length; j++) {
                if (tpl.slots[j].id === root.hoveredZone) {
                  return tpl.slots
                }
              }
            }
          }
        }
        if (tIdx >= 0 && tIdx < root.effectiveTemplates.length) {
          var curT = root.effectiveTemplates[tIdx]
          return (curT && curT.slots) ? curT.slots : []
        }
        return []
      }

      readonly property string activeTargetZone: {
        if (!root.interactive) return root.zone
        if (root.hoveredZone !== "") return root.hoveredZone
        if (root.focusedTemplateIndex >= 0 && root.focusedTemplateIndex < root.effectiveTemplates.length) {
          var t = root.effectiveTemplates[root.focusedTemplateIndex]
          if (t && t.slots && t.slots.length > 0) {
            var sIdx = Math.max(0, Math.min(t.slots.length - 1, root.focusedSlotIndex))
            return t.slots[sIdx].id
          }
        }
        return ""
      }

      visible: !root.interactive || (root.interactive && previewContainer.activeTargetZone !== "")

      // 复合分屏全局辅助线框 (Compound Silhouette)
      Repeater {
        model: previewContainer.activeTemplateSlots

        delegate: Rectangle {
          id: compBox
          required property var modelData
          readonly property var slotGeom: Model.calculateBox(modelData.id, panel.width, panel.height, 10, root.currentReserved)
          readonly property bool isCurrentActive: modelData.id === previewContainer.activeTargetZone

          visible: !compBox.isCurrentActive
          x: slotGeom.x
          y: slotGeom.y
          width: slotGeom.width
          height: slotGeom.height
          radius: Style.cornerRadius ? Style.cornerRadius * 1.5 : 12

          color: Qt.rgba(1, 1, 1, 0.03)
          border.width: 1
          border.color: Util.alpha(root.snapColor, 0.22)

          Behavior on x { NumberAnimation { duration: 80 } }
          Behavior on y { NumberAnimation { duration: 80 } }
          Behavior on width { NumberAnimation { duration: 80 } }
          Behavior on height { NumberAnimation { duration: 80 } }
        }
      }

      readonly property var boxGeom: Model.calculateBox(activeTargetZone, panel.width, panel.height, 10, root.currentReserved)

      Rectangle {
        id: highlightBox
        x: previewContainer.boxGeom.x
        y: previewContainer.boxGeom.y
        width: previewContainer.boxGeom.width
        height: previewContainer.boxGeom.height
        radius: Style.cornerRadius ? Style.cornerRadius * 1.5 : 12

        color: Util.alpha(root.snapColor, root.interactive ? 0.14 : 0.18)
        border.width: 2
        border.color: Util.alpha(root.snapColor, root.interactive ? 0.75 : 0.85)

        Behavior on x { NumberAnimation { duration: 80 } }
        Behavior on y { NumberAnimation { duration: 80 } }
        Behavior on width { NumberAnimation { duration: 80 } }
        Behavior on height { NumberAnimation { duration: 80 } }

        // 柔和外发光边框
        Rectangle {
          anchors.fill: parent
          anchors.margins: -2
          radius: parent.radius + 2
          color: "transparent"
          border.width: 1
          border.color: Util.alpha(root.snapColor, 0.35)
        }

        // 浮动指示徽章（展示区域图标、中文说明与物理像素分辨率）
        Rectangle {
          id: infoPill
          anchors.centerIn: parent
          implicitWidth: pillRow.implicitWidth + Style.space(24)
          implicitHeight: pillRow.implicitHeight + Style.space(16)
          radius: height / 2
          color: Qt.rgba(0.06, 0.08, 0.12, 0.90)
          border.color: Util.alpha(root.snapColor, 0.65)
          border.width: 1

          // 徽章外发光
          Rectangle {
            anchors.fill: parent
            anchors.margins: -1
            radius: parent.radius + 1
            color: "transparent"
            border.width: 1
            border.color: Util.alpha(root.snapColor, 0.30)
          }

          Row {
            id: pillRow
            anchors.centerIn: parent
            spacing: Style.space(10)

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: previewContainer.boxGeom.icon || "◧"
              font.pixelSize: 18
              color: root.snapColor
            }

            Column {
              anchors.verticalCenter: parent.verticalCenter
              spacing: 2

              Row {
                spacing: Style.space(6)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: previewContainer.boxGeom.label || ""
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                  color: "#ffffff"
                }

                // 物理像素分辨率胶囊
                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  implicitWidth: dimLabel.implicitWidth + 8
                  height: 16
                  radius: 3
                  color: Qt.rgba(1, 1, 1, 0.14)

                  Text {
                    id: dimLabel
                    anchors.centerIn: parent
                    text: previewContainer.boxGeom.dim || ""
                    font.family: Style.font.family
                    font.pixelSize: 9
                    font.bold: true
                    color: Util.alpha(Color.foreground, 0.85)
                  }
                }
              }

              Text {
                visible: root.interactive
                text: "按回车、点击或按对应数字直接吸附"
                font.family: Style.font.family
                font.pixelSize: 8
                color: Util.alpha(Color.foreground, 0.6)
              }
            }
          }
        }
      }
    }

    // 被动 HUD 淡入淡出动画
    SequentialAnimation {
      id: fadeAnim
      running: false
      NumberAnimation {
        target: previewContainer
        property: "opacity"
        from: 0.0
        to: 1.0
        duration: 100
        easing.type: Easing.OutCubic
      }
      PauseAnimation { duration: 180 }
      NumberAnimation {
        target: previewContainer
        property: "opacity"
        from: 1.0
        to: 0.0
        duration: 140
        easing.type: Easing.InQuad
      }
    }

    // 交互模式：OmniPal 空间架构师级 Snap Layouts 居中选择器卡片
    Item {
      id: flyoutWrapper
      visible: root.interactive
      anchors.centerIn: parent
      width: Math.min(Style.space(560), parent.width - Style.space(32))
      height: Math.min(Style.space(370), parent.height - Style.space(32))

      scale: root.interactive ? 1.0 : 0.95
      opacity: root.interactive ? 1.0 : 0.0
      Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutBack; easing.overshoot: 1.08 } }
      Behavior on opacity { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }

      readonly property real cardRadius: Math.max(14, Style.cornerRadius ? Style.cornerRadius * 1.5 : 14)

      // 1. 深邃环境微光与漫反射阴影
      Rectangle {
        anchors.fill: parent
        anchors.margins: -10
        radius: flyoutWrapper.cardRadius + 10
        color: "transparent"
        border.color: Qt.rgba(0, 0, 0, 0.45)
        border.width: 10
      }

      // 2. 交互激活微光光环
      Rectangle {
        anchors.fill: parent
        anchors.margins: -1
        radius: flyoutWrapper.cardRadius + 1
        color: "transparent"
        border.color: root.focusedTemplateIndex !== -1 ? Util.alpha(root.snapColor, 0.42) : Qt.rgba(1, 1, 1, 0.08)
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: 120 } }
      }

      // 3. 卡片主体 (Obsidian Acrylic Glass)
      Rectangle {
        id: flyoutCard
        anchors.fill: parent
        radius: flyoutWrapper.cardRadius
        color: Qt.rgba(0.07, 0.09, 0.13, 0.96)
        border.color: root.focusedTemplateIndex !== -1 ? Util.alpha(root.snapColor, 0.48) : Qt.rgba(1, 1, 1, 0.14)
        border.width: 1
        clip: true
        Behavior on border.color { ColorAnimation { duration: 120 } }

        // 顶端极光微反光线 (Specular Hairline)
        Rectangle {
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: 1
          color: Qt.rgba(1, 1, 1, 0.14)
        }

        // ============================================================
        // 头部极简上下文栏 (Hero Header: ~36px)
        // ============================================================
        Item {
          id: flyoutHeader
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.margins: Style.space(14)
          anchors.bottomMargin: 0
          height: Style.space(32)

          Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)

            // 标志性视觉微徽标
            Rectangle {
              width: Style.space(24)
              height: Style.space(24)
              radius: 6
              color: Util.alpha(root.snapColor, 0.16)
              border.color: Util.alpha(root.snapColor, 0.40)
              border.width: 1
              anchors.verticalCenter: parent.verticalCenter

              Text {
                anchors.centerIn: parent
                text: "⊞"
                font.pixelSize: 13
                font.bold: true
                color: root.snapColor
              }
            }

            Text {
              text: "Snap Layouts"
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              color: "#ffffff"
              anchors.verticalCenter: parent.verticalCenter
            }

            // 目标窗口芯片 (如有捕获)
            Rectangle {
              visible: (root.targetWindowTitle !== "" || root.targetWindowClass !== "" || root.targetWindowAddress !== "")
              height: Style.space(18)
              radius: 4
              color: Qt.rgba(1, 1, 1, 0.08)
              border.color: Qt.rgba(1, 1, 1, 0.14)
              border.width: 1
              anchors.verticalCenter: parent.verticalCenter
              implicitWidth: targetWinRow.implicitWidth + Style.space(10)

              Row {
                id: targetWinRow
                anchors.centerIn: parent
                spacing: 4

                Rectangle {
                  width: 5
                  height: 5
                  radius: 3
                  color: "#a3be8c"
                  anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                  text: root.targetWindowTitle || root.targetWindowClass || root.targetWindowAddress
                  font.family: Style.font.family
                  font.pixelSize: 9
                  font.bold: true
                  color: Util.alpha(Color.foreground, 0.85)
                  elide: Text.ElideRight
                  maximumLineCount: 1
                  width: Math.min(implicitWidth, Style.space(170))
                  anchors.verticalCenter: parent.verticalCenter
                }
              }
            }
          }

          // 右侧快捷提示与关闭按钮
          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)

            // 阶段提示药丸
            Rectangle {
              height: Style.space(20)
              radius: 4
              color: root.focusedTemplateIndex !== -1 ? Util.alpha(root.snapColor, 0.18) : Qt.rgba(0, 0, 0, 0.45)
              border.color: root.focusedTemplateIndex !== -1 ? root.snapColor : Qt.rgba(1, 1, 1, 0.12)
              border.width: 1
              anchors.verticalCenter: parent.verticalCenter
              implicitWidth: stepBadgeRow.implicitWidth + Style.space(8)

              Row {
                id: stepBadgeRow
                anchors.centerIn: parent
                spacing: 4

                Text {
                  text: root.focusedTemplateIndex === -1 ? "1~6 模板" : ("模板 [" + (root.focusedTemplateIndex + 1) + "] 就绪")
                  font.family: Style.font.family
                  font.pixelSize: 8
                  font.bold: true
                  color: root.focusedTemplateIndex !== -1 ? root.snapColor : Util.alpha(Color.foreground, 0.70)
                  anchors.verticalCenter: parent.verticalCenter
                }
              }
            }

            // 关闭按钮
            Rectangle {
              width: Style.space(22)
              height: Style.space(22)
              radius: 5
              color: closeMouse.containsMouse ? "#bf616a" : Qt.rgba(1, 1, 1, 0.06)
              border.color: closeMouse.containsMouse ? "transparent" : Qt.rgba(1, 1, 1, 0.10)
              border.width: 1
              anchors.verticalCenter: parent.verticalCenter
              Behavior on color { ColorAnimation { duration: 90 } }

              Text {
                anchors.centerIn: parent
                text: "✕"
                font.pixelSize: 10
                font.bold: true
                color: closeMouse.containsMouse ? "#ffffff" : Util.alpha(Color.foreground, 0.60)
              }

              MouseArea {
                id: closeMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.dismiss()
              }
            }
          }
        }

        // ============================================================
        // 核心 2×3 微型高精显示器网格 (The 6 Layout Monitors)
        // ============================================================
        Grid {
          id: templatesGrid
          anchors.top: flyoutHeader.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: footerSep.top
          anchors.margins: Style.space(14)
          columns: 3
          spacing: Style.space(12)

          Repeater {
            model: root.effectiveTemplates

            delegate: Rectangle {
              id: tplCard
              required property var modelData
              required property int index

              readonly property bool isSelectedTpl: root.focusedTemplateIndex === tplCard.index
              readonly property bool isDimmed: root.focusedTemplateIndex !== -1 && !isSelectedTpl
              readonly property bool isCardHovered: cardMouse.containsMouse

              width: (templatesGrid.width - templatesGrid.spacing * 2) / 3
              height: (templatesGrid.height - templatesGrid.spacing) / 2
              radius: 8
              color: isSelectedTpl
                ? Qt.rgba(0.14, 0.19, 0.28, 0.92)
                : (isCardHovered ? Qt.rgba(0.12, 0.15, 0.22, 0.82) : Qt.rgba(0.09, 0.11, 0.16, 0.65))
              border.color: isSelectedTpl ? root.snapColor : (isCardHovered ? Qt.rgba(1, 1, 1, 0.30) : Qt.rgba(1, 1, 1, 0.10))
              border.width: isSelectedTpl ? 2 : 1
              opacity: isDimmed ? 0.45 : 1.0

              Behavior on color { ColorAnimation { duration: 80 } }
              Behavior on border.color { ColorAnimation { duration: 80 } }
              Behavior on border.width { NumberAnimation { duration: 80 } }
              Behavior on opacity { NumberAnimation { duration: 80 } }

              // 选中外圈光晕
              Rectangle {
                anchors.fill: parent
                anchors.margins: -2
                radius: parent.radius + 2
                color: "transparent"
                border.width: 1
                border.color: Util.alpha(root.snapColor, 0.45)
                visible: tplCard.isSelectedTpl
              }

              MouseArea {
                id: cardMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  root.focusedTemplateIndex = tplCard.index
                  root.focusedSlotIndex = 0
                  root.hoveredZone = ""
                }
              }

              Column {
                anchors.fill: parent
                anchors.margins: 7
                spacing: 5

                // 模板标题与编号胶囊
                Item {
                  id: tplHeaderItem
                  width: parent.width
                  height: 16

                  Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Text {
                      text: tplCard.modelData.title
                      font.family: Style.font.family
                      font.pixelSize: 9
                      font.bold: true
                      color: tplCard.isSelectedTpl ? "#ffffff" : (tplCard.isCardHovered ? "#ffffff" : Util.alpha(Color.foreground, 0.85))
                      anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                      text: tplCard.modelData.hint ? ("· " + tplCard.modelData.hint) : ""
                      font.family: Style.font.family
                      font.pixelSize: 8
                      color: Util.alpha(Color.foreground, 0.40)
                      anchors.verticalCenter: parent.verticalCenter
                      elide: Text.ElideRight
                      width: Math.min(implicitWidth, tplHeaderItem.width - 50)
                    }
                  }

                  // 模板编号药丸 [1] ~ [6]
                  Rectangle {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 16
                    height: 14
                    radius: 3
                    color: tplCard.isSelectedTpl ? root.snapColor : Qt.rgba(0, 0, 0, 0.45)
                    border.color: tplCard.isSelectedTpl ? "#ffffff" : Qt.rgba(1, 1, 1, 0.15)
                    border.width: 1

                    Text {
                      anchors.centerIn: parent
                      text: tplCard.modelData.key || String(tplCard.index + 1)
                      font.pixelSize: 8
                      font.bold: true
                      color: tplCard.isSelectedTpl ? "#000000" : Util.alpha(Color.foreground, 0.75)
                    }
                  }
                }

                // 微缩屏幕画框 (Monitor Display Bezel)
                Rectangle {
                  id: miniCanvas
                  width: parent.width
                  height: parent.height - 21
                  radius: 5
                  color: Qt.rgba(0, 0, 0, 0.30)
                  border.color: Qt.rgba(1, 1, 1, 0.06)
                  border.width: 1
                  clip: true

                  Repeater {
                    model: tplCard.modelData.slots

                    delegate: Rectangle {
                      id: slotRect
                      required property var modelData
                      required property int index

                      readonly property real usableW: miniCanvas.width - 4
                      readonly property real usableH: miniCanvas.height - 4
                      readonly property real slotX: 2 + modelData.xr * usableW
                      readonly property real slotY: 2 + modelData.yr * usableH
                      readonly property real slotW: modelData.wr * usableW
                      readonly property real slotH: modelData.hr * usableH

                      readonly property bool isSlotFocused: tplCard.isSelectedTpl && root.focusedSlotIndex === slotRect.index
                      readonly property bool isHovered: slotMouse.containsMouse || root.hoveredZone === modelData.id || isSlotFocused

                      x: slotX + 1
                      y: slotY + 1
                      width: Math.max(10, slotW - 2)
                      height: Math.max(10, slotH - 2)
                      radius: 3

                      color: isHovered ? Util.alpha(root.snapColor, 0.40) : Qt.rgba(1, 1, 1, 0.08)
                      border.color: isHovered ? root.snapColor : Qt.rgba(1, 1, 1, 0.16)
                      border.width: isHovered ? 1.5 : 1

                      Behavior on color { ColorAnimation { duration: 80 } }
                      Behavior on border.color { ColorAnimation { duration: 80 } }

                      // 选中模板时的数字按键角标 [1]、[2]...
                      Rectangle {
                        visible: tplCard.isSelectedTpl
                        anchors.centerIn: parent
                        width: 16
                        height: 16
                        radius: 3
                        color: slotRect.isSlotFocused ? root.snapColor : Qt.rgba(0, 0, 0, 0.7)
                        border.color: slotRect.isSlotFocused ? "#ffffff" : Util.alpha(root.snapColor, 0.5)
                        border.width: 1

                        Text {
                          anchors.centerIn: parent
                          text: String(slotRect.index + 1)
                          font.pixelSize: 9
                          font.bold: true
                          color: slotRect.isSlotFocused ? "#000000" : "#ffffff"
                        }
                      }

                      // 未选中模板时的区域名称微标 (悬停时显现)
                      Text {
                        visible: !tplCard.isSelectedTpl && slotRect.isHovered
                        anchors.centerIn: parent
                        text: modelData.label
                        font.family: Style.font.family
                        font.pixelSize: 8
                        font.bold: true
                        color: "#ffffff"
                      }

                      MouseArea {
                        id: slotMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor

                        onEntered: {
                          root.hoveredZone = modelData.id
                          root.focusedTemplateIndex = tplCard.index
                          root.focusedSlotIndex = slotRect.index
                        }
                        onExited: {
                          if (root.hoveredZone === modelData.id) {
                            root.hoveredZone = ""
                          }
                        }
                        onClicked: {
                          root.executeSnap(modelData.id)
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }

        // 底部细线
        Rectangle {
          id: footerSep
          anchors.bottom: flyoutFooter.top
          anchors.bottomMargin: Style.space(6)
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.leftMargin: Style.space(14)
          anchors.rightMargin: Style.space(14)
          height: 1
          color: Qt.rgba(1, 1, 1, 0.08)
        }

        // ============================================================
        // 底部状态与操作指引栏 (Hero Footer: ~24px)
        // ============================================================
        Item {
          id: flyoutFooter
          anchors.bottom: parent.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.margins: Style.space(14)
          anchors.topMargin: 0
          height: Style.space(24)

          // 左侧：实时悬停状态与操作指引
          Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5

            Rectangle {
              width: 5
              height: 5
              radius: 3
              color: root.hoveredZone !== "" ? root.snapColor : Util.alpha(Color.foreground, 0.4)
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              text: {
                if (root.hoveredZone !== "") {
                  var zInfo = Model.ZONES[root.hoveredZone]
                  return "落点: " + (zInfo ? zInfo.label : root.hoveredZone) + " · 点击或回车吸附"
                }
                if (root.focusedTemplateIndex !== -1) {
                  var curT = root.effectiveTemplates[root.focusedTemplateIndex]
                  var sc = (curT && curT.slots) ? curT.slots.length : 2
                  return "模板 [" + (root.focusedTemplateIndex + 1) + "]: 按 1–" + sc + " 吸附 · 方向键导航 · Esc 返回"
                }
                return "按 1–6 快捷跳选 · 悬停桌面高亮轮廓 · Esc 退出"
              }
              font.family: Style.font.family
              font.pixelSize: 8
              font.bold: root.hoveredZone !== ""
              color: root.hoveredZone !== "" ? root.snapColor : Util.alpha(Color.foreground, 0.60)
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          // 右侧：紧凑键位小标签组
          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)

            Repeater {
              model: [
                { key: "1~6", desc: "模板" },
                { key: "1~4", desc: "吸附" },
                { key: "Esc", desc: "退出" }
              ]

              delegate: Rectangle {
                required property var modelData
                height: 16
                radius: 3
                color: Qt.rgba(0, 0, 0, 0.45)
                border.color: Qt.rgba(1, 1, 1, 0.12)
                border.width: 1
                implicitWidth: kbdRow.implicitWidth + 6

                Row {
                  id: kbdRow
                  anchors.centerIn: parent
                  spacing: 3

                  Text {
                    text: modelData.key
                    font.family: Style.font.family
                    font.pixelSize: 8
                    font.bold: true
                    color: "#ffffff"
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    text: modelData.desc
                    font.family: Style.font.family
                    font.pixelSize: 7
                    color: Util.alpha(Color.foreground, 0.45)
                    anchors.verticalCenter: parent.verticalCenter
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
