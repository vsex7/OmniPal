pragma ComponentBehavior: Bound
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "Tokens.js" as Tokens

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

  // ---- Theme ----------------------------------------------------------------
  // Native first: qs.Commons Color/Style + qs.Ui widgets wherever Omarchy has one.
  // `theme` (OmniTheme.qml) resolves the remaining custom-surface roles straight from
  // qs.Commons; the colors.toml palette below only feeds the extended status hues.
  property var themePalette: Tokens.fallback
  readonly property OmniTheme theme: OmniTheme { palette: root.themePalette }
  FileView {
    id: omniThemeFile
    property bool legacy: false
    path: (Quickshell.env("HOME") || "") + (legacy ? Tokens.themeFiles.legacyRel : Tokens.themeFiles.stateRel)
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.themePalette = Tokens.mergePalette(Tokens.parseColorsToml(text()))
    onLoadFailed: if (!legacy) legacy = true
  }

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property bool interactive: false
  property string zone: "left"
  property string hoveredZone: ""

  // Native chrome straight from qs.Commons (no null-guards: the Omarchy shell is the only host).
  //   flyout card  = [menu] surface (like omarchy.emojis / menu overlays)
  //   snap HUD pill = [popups] surface (like bar panels / OSD)
  readonly property color snapColor: Commons.Color.accent
  readonly property int hudRadius: Style.cornerRadius
  readonly property int hudBorder: Math.max(1, Style.space(2))
  readonly property color hudBg: Commons.Color.popups.background
  readonly property color hudBorderColor: Commons.Color.popups.border
  readonly property var hudBorderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, root.hudBorder)
  readonly property var flyoutBorderSpec: Border.surfaceSpec("menu", "border", Commons.Color.menu.border, root.hudBorder)

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
      if (root.opened && root.interactive) {
        root.dismiss()
        return
      }
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
    var safePattern = /^[a-zA-Z0-9_.-]+$/
    var cleanZone = String(targetZone).trim()
    if (!safePattern.test(cleanZone)) return

    var cmd = ["omni-profile", "snap", cleanZone]
    if (root.targetWindowAddress) {
      var cleanAddr = String(root.targetWindowAddress).trim()
      if (safePattern.test(cleanAddr)) {
        cmd.push(cleanAddr)
      }
    }
    cmd.push("--no-hud")

    if (typeof Quickshell.execDetached === "function") {
      Quickshell.execDetached(cmd)
    } else {
      dispatchProc.command = cmd
      dispatchProc.running = true
    }
    root.dismiss()
  }

  // IPC 接口 (唯一的外部唤出与状态指令通道，杜绝双重监听)
  ShellIpc {
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
      id: schemaCollector
      waitForEnd: true
      onStreamFinished: function() {
        var raw = text  // streamFinished() carries no args; read StdioCollector.text
        var str = (raw && raw.trim() !== "") ? raw : (schemaCollector.text ? schemaCollector.text : "")
        if (str && str.trim() !== "") {
          Model.loadSchemaJson(str)
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

  // Native qs.Ui OverlayWindow. The passive snap HUD must not steal focus, so keyboard
  // focus is only Exclusive in interactive (Snap Layouts picker) mode.
  OverlayWindow {
    id: panel
    shown: root.opened
    shownKeyboardFocus: root.interactive ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    WlrLayershell.namespace: "omni-snap-feedback"

    Item {
      id: inputLayer
      anchors.fill: parent
    }
    mask: Region { item: root.interactive ? inputLayer : null }

    // 交互模式暗色全屏遮罩
    Rectangle {
      anchors.fill: parent
      visible: root.interactive
      color: Commons.Color.menu.scrim
      opacity: root.interactive ? 1.0 : 0.0
      Behavior on opacity { NumberAnimation { duration: Style.duration(90) } }

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
        if (event.key === Qt.Key_Backspace) {
          if (root.focusedTemplateIndex >= 0) {
            root.focusedTemplateIndex = -1
            root.focusedSlotIndex = 0
            root.hoveredZone = ""
            event.accepted = true
            return
          }
        }

        // 数字键 1-6 处理 (Windows 11 Snap Layouts 核心两阶逻辑：支持主键盘与小键盘)
        // Qt has no Key_NumpadN: keypad digits arrive as Key_1..Key_6 + KeypadModifier,
        // so this one range covers both rows.
        var isNumKey = (event.key >= Qt.Key_1 && event.key <= Qt.Key_6)
        if (isNumKey) {
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
          radius: root.hudRadius

          color: "transparent"
          border.width: Math.max(1, Style.normalBorderWidth)
          border.color: root.theme.line

          Behavior on x { NumberAnimation { duration: Style.duration(90) } }
          Behavior on y { NumberAnimation { duration: Style.duration(90) } }
          Behavior on width { NumberAnimation { duration: Style.duration(90) } }
          Behavior on height { NumberAnimation { duration: Style.duration(90) } }
        }
      }

      readonly property var boxGeom: Model.calculateBox(activeTargetZone, panel.width, panel.height, 10, root.currentReserved)

      Rectangle {
        id: highlightBox
        x: previewContainer.boxGeom.x
        y: previewContainer.boxGeom.y
        width: previewContainer.boxGeom.width
        height: previewContainer.boxGeom.height
        radius: root.hudRadius

        color: Util.alpha(root.snapColor, 0.12)
        border.width: root.hudBorder
        border.color: root.snapColor

        Behavior on x { NumberAnimation { duration: Style.duration(90) } }
        Behavior on y { NumberAnimation { duration: Style.duration(90) } }
        Behavior on width { NumberAnimation { duration: Style.duration(90) } }
        Behavior on height { NumberAnimation { duration: Style.duration(90) } }


        // 浮动指示徽章（展示区域图标、中文说明与物理像素分辨率）
        BorderSurface {
          id: infoPill
          anchors.centerIn: parent
          width: implicitWidth
          height: implicitHeight
          implicitWidth: pillRow.implicitWidth + Style.spacing.popupPadding * 2 + Border.left(root.hudBorderSpec) + Border.right(root.hudBorderSpec)
          implicitHeight: pillRow.implicitHeight + Style.spacing.popupPadding + Border.top(root.hudBorderSpec) + Border.bottom(root.hudBorderSpec)
          radius: root.hudRadius
          color: root.hudBg
          borderSpec: root.hudBorderSpec


          Row {
            id: pillRow
            anchors.centerIn: parent
            spacing: Style.space(10)

            Text {
              font.family: Style.font.family
              anchors.verticalCenter: parent.verticalCenter
              text: previewContainer.boxGeom.icon || "◧"
              font.pixelSize: Style.font.iconLarge || 18
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
                  color: root.theme.textStrong
                }

                // 物理像素分辨率胶囊
                BorderSurface {
                  anchors.verticalCenter: parent.verticalCenter
                  implicitWidth: dimLabel.implicitWidth + Style.space(10)
                  width: implicitWidth
                  height: dimLabel.implicitHeight + Style.space(4)
                  radius: Style.cornerRadius
                  color: "transparent"
                  borderSpec: Border.controlSpec("normal", root.theme.text, root.snapColor)

                  Text {
                    id: dimLabel
                    anchors.centerIn: parent
                    text: previewContainer.boxGeom.dim || ""
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    color: Util.alpha(Color.foreground, 0.85)
                  }
                }
              }

              Text {
                visible: root.interactive
                text: "按回车、点击或按对应数字直接吸附"
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
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
        duration: Style.duration(90)
        easing.type: Easing.OutCubic
      }
      PauseAnimation { duration: Style.duration(200) }
      NumberAnimation {
        target: previewContainer
        property: "opacity"
        from: 1.0
        to: 0.0
        duration: Style.duration(140)
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

      scale: 1.0
      opacity: root.interactive ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: Style.duration(140); easing.type: Easing.OutCubic } }

      readonly property real cardRadius: root.hudRadius



      // 卡片主体：Omarchy popup（实色主题背景 + 2px active-border，无阴影/玻璃）
      BorderSurface {
        id: flyoutCard
        anchors.fill: parent
        radius: flyoutWrapper.cardRadius
        color: Commons.Color.menu.background
        borderSpec: root.flyoutBorderSpec
        clip: true

        // 吸收卡片空白区点击，防止点击空白处透传穿透导致面板被全屏遮罩误关闭
        MouseArea {
          anchors.fill: parent
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
              radius: Style.cornerRadius
              color: Util.alpha(root.snapColor, 0.16)
              border.color: Util.alpha(root.snapColor, 0.40)
              border.width: 1
              anchors.verticalCenter: parent.verticalCenter

              Text {
                font.family: Style.font.family
                anchors.centerIn: parent
                text: "⊞"
                font.pixelSize: Style.font.body
                font.bold: true
                color: root.snapColor
              }
            }

            Text {
              text: "Snap Layouts"
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              color: root.theme.textStrong
              anchors.verticalCenter: parent.verticalCenter
            }

            // 目标窗口芯片 (如有捕获) — PanelHero-style detail pill
            BorderSurface {
              visible: (root.targetWindowTitle !== "" || root.targetWindowClass !== "" || root.targetWindowAddress !== "")
              height: Style.space(18)
              radius: Style.cornerRadius
              color: "transparent"
              borderSpec: Border.controlSpec("normal", root.theme.text, root.snapColor)
              anchors.verticalCenter: parent.verticalCenter
              implicitWidth: targetWinRow.implicitWidth + Style.space(10)

              Row {
                id: targetWinRow
                anchors.centerIn: parent
                spacing: 4

                Rectangle {
                  width: 5
                  height: 5
                  radius: Style.cornerRadius
                  color: root.theme.ok
                  anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                  text: root.targetWindowTitle || root.targetWindowClass || root.targetWindowAddress
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
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
            BorderSurface {
              height: Style.space(20)
              radius: Style.cornerRadius
              color: root.focusedTemplateIndex !== -1 ? Style.selectedFillFor(root.theme.text, root.snapColor) : Style.normalFillFor(root.theme.text, root.snapColor)
              borderSpec: Border.controlSpec(root.focusedTemplateIndex !== -1 ? "focus" : "normal", root.theme.text, root.snapColor)
              anchors.verticalCenter: parent.verticalCenter
              implicitWidth: stepBadgeRow.implicitWidth + Style.space(8)

              Row {
                id: stepBadgeRow
                anchors.centerIn: parent
                spacing: 4

                Text {
                  text: root.focusedTemplateIndex === -1 ? "1~6 模板" : ("模板 [" + (root.focusedTemplateIndex + 1) + "] 就绪")
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  color: root.focusedTemplateIndex !== -1 ? root.snapColor : Util.alpha(Color.foreground, 0.70)
                  anchors.verticalCenter: parent.verticalCenter
                }
              }
            }

            // 关闭按钮 — native PanelActionButton
            PanelActionButton {
              iconText: "✕"
              tooltipText: "关闭 (Esc)"
              foreground: Commons.Color.menu.text
              anchors.verticalCenter: parent.verticalCenter
              onClicked: root.dismiss()
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

            // Template card painted with the same Style state tokens as a bordered native
            // Button: normal → hover-cursor → focus (selected template).
            delegate: BorderSurface {
              id: tplCard
              required property var modelData
              required property int index

              readonly property bool isSelectedTpl: root.focusedTemplateIndex === tplCard.index
              readonly property bool isDimmed: root.focusedTemplateIndex !== -1 && !isSelectedTpl
              readonly property bool isCardHovered: cardMouse.containsMouse

              width: (templatesGrid.width - templatesGrid.spacing * 2) / 3
              height: (templatesGrid.height - templatesGrid.spacing) / 2
              radius: Style.cornerRadius
              color: isSelectedTpl ? Style.selectedFillFor(root.theme.text, root.snapColor)
                : (isCardHovered ? Style.hoverFillFor(root.theme.text, root.snapColor) : "transparent")
              borderSpec: Border.controlSpec(isSelectedTpl ? "focus" : (isCardHovered ? "hover-cursor" : "normal"), root.theme.text, root.snapColor)
              opacity: isDimmed ? 0.45 : 1.0

              Behavior on color { ColorAnimation { duration: Style.duration(120) } }
              Behavior on opacity { NumberAnimation { duration: Style.duration(90) } }


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
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      color: tplCard.isSelectedTpl ? root.snapColor : root.theme.text
                      anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                      text: tplCard.modelData.hint ? ("· " + tplCard.modelData.hint) : ""
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
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
                    radius: Style.cornerRadius
                    color: tplCard.isSelectedTpl ? root.snapColor : root.theme.chipFill
                    border.color: tplCard.isSelectedTpl ? root.snapColor : Util.alpha(root.theme.text, 0.15)
                    border.width: 1

                    Text {
                      font.family: Style.font.family
                      anchors.centerIn: parent
                      text: tplCard.modelData.key || String(tplCard.index + 1)
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      color: tplCard.isSelectedTpl ? root.theme.onAccent : Util.alpha(Color.foreground, 0.75)
                    }
                  }
                }

                // 微缩屏幕画框 (Monitor Display Bezel)
                Rectangle {
                  id: miniCanvas
                  width: parent.width
                  height: parent.height - 21
                  radius: Style.cornerRadius
                  color: root.theme.sunken
                  border.color: Util.alpha(root.theme.text, 0.06)
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
                      radius: Style.cornerRadius

                      color: isHovered ? Util.alpha(root.snapColor, 0.40) : Util.alpha(root.theme.text, 0.08)
                      border.color: isHovered ? root.snapColor : Util.alpha(root.theme.text, 0.16)
                      border.width: Math.max(1, Style.normalBorderWidth)

                      Behavior on color { ColorAnimation { duration: Style.duration(90) } }
                      Behavior on border.color { ColorAnimation { duration: Style.duration(90) } }

                      // 选中模板时的数字按键角标 [1]、[2]...
                      Rectangle {
                        visible: tplCard.isSelectedTpl
                        anchors.centerIn: parent
                        width: 16
                        height: 16
                        radius: Style.cornerRadius
                        color: slotRect.isSlotFocused ? root.snapColor : root.theme.sunken
                        border.color: slotRect.isSlotFocused ? root.snapColor : Util.alpha(root.snapColor, 0.5)
                        border.width: 1

                        Text {
                          font.family: Style.font.family
                          anchors.centerIn: parent
                          text: String(slotRect.index + 1)
                          font.pixelSize: Style.font.caption
                          font.bold: true
                          color: slotRect.isSlotFocused ? root.theme.onAccent : root.theme.textStrong
                        }
                      }

                      // 未选中模板时的区域名称微标 (悬停时显现)
                      Text {
                        visible: !tplCard.isSelectedTpl && slotRect.isHovered
                        anchors.centerIn: parent
                        text: slotRect.modelData.label
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        font.bold: true
                        color: root.theme.textStrong
                      }

                      MouseArea {
                        id: slotMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor

                        onEntered: {
                          root.hoveredZone = slotRect.modelData.id
                        }
                        onExited: {
                          if (root.hoveredZone === slotRect.modelData.id) {
                            root.hoveredZone = ""
                          }
                        }
                        onClicked: {
                          root.executeSnap(slotRect.modelData.id)
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }

        // 底部细线 — native PanelSeparator
        PanelSeparator {
          id: footerSep
          anchors.bottom: flyoutFooter.top
          anchors.bottomMargin: Style.space(6)
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.leftMargin: Style.space(14)
          anchors.rightMargin: Style.space(14)
          foreground: Commons.Color.menu.text
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
              radius: Style.cornerRadius
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
              font.pixelSize: Style.font.caption
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

              // Key-hint chip: normal control fill/border tokens.
              delegate: BorderSurface {
                id: kbdChip
                required property var modelData
                height: kbdRow.implicitHeight + Style.space(4)
                radius: Style.cornerRadius
                color: Style.normalFillFor(root.theme.text, root.snapColor)
                borderSpec: Border.controlSpec("normal", root.theme.text, root.snapColor)
                implicitWidth: kbdRow.implicitWidth + Style.space(8)
                width: implicitWidth

                Row {
                  id: kbdRow
                  anchors.centerIn: parent
                  spacing: 3

                  Text {
                    text: kbdChip.modelData.key
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    color: root.theme.textStrong
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    text: kbdChip.modelData.desc
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
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
