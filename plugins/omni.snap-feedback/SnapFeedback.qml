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

  function open(payloadJson) {
    var p = ({})
    try { p = JSON.parse(payloadJson || "{}") } catch(e) { p = ({}) }

    if (p.interactive === true || p.zone === "layouts" || p.zone === "picker") {
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
  }

  function dismiss() {
    root.opened = false
    root.interactive = false
    root.hoveredZone = ""
    root.focusedTemplateIndex = -1
    root.focusedSlotIndex = 0
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function executeSnap(targetZone) {
    if (!targetZone) return
    root.dismiss()
    dispatchProc.command = ["omni-profile", "snap", targetZone, "--no-hud"]
    dispatchProc.running = true
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

    // 交互模式：Windows 11 风格 Snap Layouts 飞出选择器卡片
    Item {
      id: flyoutWrapper
      visible: root.interactive
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.top: parent.top
      anchors.topMargin: root.reservedTop + Style.space(16)
      width: Style.space(540)
      height: Style.space(360)

      scale: root.interactive ? 1.0 : 0.96
      opacity: root.interactive ? 1.0 : 0.0
      Behavior on scale { NumberAnimation { duration: 130; easing.type: Easing.OutQuad } }
      Behavior on opacity { NumberAnimation { duration: 130; easing.type: Easing.OutQuad } }

      // 卡片外层悬浮投影
      Rectangle {
        anchors.fill: parent
        anchors.margins: -6
        radius: (Style.cornerRadius ? Style.cornerRadius * 1.5 : 12) + 6
        color: "transparent"
        border.color: Qt.rgba(0, 0, 0, 0.45)
        border.width: 6
      }

      // 卡片主体
      Rectangle {
        id: flyoutCard
        anchors.fill: parent
        radius: Style.cornerRadius ? Style.cornerRadius * 1.5 : 12
        color: Qt.rgba(0.09, 0.11, 0.15, 0.95)
        border.color: Qt.rgba(1, 1, 1, 0.16)
        border.width: 1
        clip: true

        // 顶部标题栏
        Item {
          id: flyoutHeader
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.margins: Style.space(14)
          height: Style.space(28)

          Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)

            Text {
              text: "⊞"
              font.pixelSize: Style.font.body
              color: root.snapColor
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              text: "窗口吸附布局 (Snap Layouts)"
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              color: "#ffffff"
              anchors.verticalCenter: parent.verticalCenter
            }

            Rectangle {
              height: Style.space(18)
              implicitWidth: keyHintText.implicitWidth + Style.space(10)
              radius: 3
              color: Qt.rgba(0, 0, 0, 0.45)
              border.color: Qt.rgba(1, 1, 1, 0.12)
              border.width: 1
              anchors.verticalCenter: parent.verticalCenter

              Text {
                id: keyHintText
                anchors.centerIn: parent
                text: "Super + Z"
                font.family: Style.font.family
                font.pixelSize: 9
                font.bold: true
                color: Util.alpha(Color.foreground, 0.7)
              }
            }
          }

          // 右侧关闭按钮
          Rectangle {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(22)
            height: Style.space(22)
            radius: 4
            color: closeMouse.containsMouse ? "#bf616a" : "transparent"

            Text {
              anchors.centerIn: parent
              text: "✕"
              font.pixelSize: 10
              font.bold: true
              color: closeMouse.containsMouse ? "#ffffff" : Util.alpha(Color.foreground, 0.6)
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

        // 中间 2 行 3 列模板网格
        Grid {
          id: templatesGrid
          anchors.top: flyoutHeader.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: flyoutFooter.top
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

              width: (templatesGrid.width - templatesGrid.spacing * 2) / 3
              height: (templatesGrid.height - templatesGrid.spacing) / 2
              radius: 8
              color: isSelectedTpl ? Qt.rgba(0.14, 0.18, 0.25, 0.88) : Qt.rgba(0.12, 0.15, 0.20, 0.65)
              border.color: isSelectedTpl ? root.snapColor : Qt.rgba(1, 1, 1, 0.12)
              border.width: isSelectedTpl ? 2 : 1
              opacity: isDimmed ? 0.55 : 1.0

              Behavior on color { ColorAnimation { duration: 90 } }
              Behavior on border.color { ColorAnimation { duration: 90 } }
              Behavior on border.width { NumberAnimation { duration: 90 } }
              Behavior on opacity { NumberAnimation { duration: 90 } }

              // 选中模板高光外环
              Rectangle {
                anchors.fill: parent
                anchors.margins: -2
                radius: parent.radius + 2
                color: "transparent"
                border.width: 1
                border.color: Util.alpha(root.snapColor, 0.4)
                visible: tplCard.isSelectedTpl
              }

              Column {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                // 模板标题与快捷键序号
                Item {
                  width: parent.width
                  height: 16

                  Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: tplCard.modelData.title
                    font.family: Style.font.family
                    font.pixelSize: 10
                    font.bold: true
                    color: tplCard.isSelectedTpl ? "#ffffff" : Util.alpha(Color.foreground, 0.9)
                  }

                  Rectangle {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 16
                    height: 16
                    radius: 3
                    color: tplCard.isSelectedTpl ? root.snapColor : Qt.rgba(0, 0, 0, 0.45)
                    border.color: tplCard.isSelectedTpl ? "#ffffff" : Qt.rgba(1, 1, 1, 0.15)
                    border.width: 1

                    Text {
                      anchors.centerIn: parent
                      text: tplCard.modelData.key || String(tplCard.index + 1)
                      font.pixelSize: 9
                      font.bold: true
                      color: tplCard.isSelectedTpl ? "#000000" : Util.alpha(Color.foreground, 0.7)
                    }
                  }
                }

                // 交互式微缩分区容器
                Item {
                  id: miniCanvas
                  width: parent.width
                  height: parent.height - 22

                  Repeater {
                    model: tplCard.modelData.slots

                    delegate: Rectangle {
                      id: slotRect
                      required property var modelData
                      required property int index

                      readonly property real slotX: modelData.xr * miniCanvas.width
                      readonly property real slotY: modelData.yr * miniCanvas.height
                      readonly property real slotW: modelData.wr * miniCanvas.width
                      readonly property real slotH: modelData.hr * miniCanvas.height

                      readonly property bool isSlotFocused: tplCard.isSelectedTpl && root.focusedSlotIndex === slotRect.index
                      readonly property bool isHovered: slotMouse.containsMouse || root.hoveredZone === modelData.id || isSlotFocused

                      x: slotX + 1
                      y: slotY + 1
                      width: slotW - 2
                      height: slotH - 2
                      radius: 4

                      color: isHovered ? Util.alpha(root.snapColor, 0.35) : Qt.rgba(1, 1, 1, 0.08)
                      border.color: isHovered ? root.snapColor : Qt.rgba(1, 1, 1, 0.20)
                      border.width: isHovered ? 2 : 1

                      Behavior on color { ColorAnimation { duration: 80 } }
                      Behavior on border.color { ColorAnimation { duration: 80 } }

                      // 当模板被选定时，展示显式阶梯按键角标 [1]、[2]...
                      Rectangle {
                        visible: tplCard.isSelectedTpl
                        anchors.centerIn: parent
                        width: 18
                        height: 18
                        radius: 3
                        color: slotRect.isSlotFocused ? root.snapColor : Qt.rgba(0, 0, 0, 0.65)
                        border.color: slotRect.isSlotFocused ? "#ffffff" : Util.alpha(root.snapColor, 0.5)
                        border.width: 1

                        Text {
                          anchors.centerIn: parent
                          text: String(slotRect.index + 1)
                          font.pixelSize: 10
                          font.bold: true
                          color: slotRect.isSlotFocused ? "#000000" : "#ffffff"
                        }
                      }

                      // 当模板未被选定时，显示常规分区中文简标
                      Text {
                        visible: !tplCard.isSelectedTpl
                        anchors.centerIn: parent
                        text: modelData.label
                        font.family: Style.font.family
                        font.pixelSize: 8
                        font.bold: slotRect.isHovered
                        color: slotRect.isHovered ? "#ffffff" : Util.alpha(Color.foreground, 0.65)
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

        // 底部操作快捷提示
        Item {
          id: flyoutFooter
          anchors.bottom: parent.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.margins: Style.space(10)
          height: Style.space(20)

          Text {
            anchors.centerIn: parent
            text: {
              if (root.focusedTemplateIndex === -1) {
                return "按 1–6 选择模板 · 鼠标悬停预览 · 点击或回车吸附 · Esc 退出"
              }
              var t = root.effectiveTemplates[root.focusedTemplateIndex]
              var numSlots = t && t.slots ? t.slots.length : 2
              return "模板 [" + (root.focusedTemplateIndex + 1) + "] " + (t ? t.title : "") + ": 按 1–" + numSlots + " 即刻吸附 · 方向键微调 · 回车确认 · Esc 返回"
            }
            font.family: Style.font.family
            font.pixelSize: 9
            color: Util.alpha(Color.foreground, 0.6)
          }
        }
      }
    }
  }
}
