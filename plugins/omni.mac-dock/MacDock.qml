pragma ComponentBehavior: Bound
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Icons.js" as Icons

// OmniPal macOS 风格底部 Dock 栏（omni.mac-dock）
//
// 特性：
// 1. 底部居中悬浮胶囊卡片，毛玻璃磨砂质感（纯元数据渲染，零窗口像素抓取，H-5）
// 2. 收藏应用 + 实时运行窗口列表（hyprctl clients -j），同类多窗口聚合计数
// 3. 物理平滑鱼眼波浪放大：鼠标位置驱动高斯衰减，相邻图标连续缩放，离开弹簧回落
// 4. 多窗口实例角标 + 顺序轮转聚焦；点击/激活触发纵向阻尼弹跳动效
// 5. 右键图标弹出上下文动作卡片（聚焦 / 轮转 / 新开实例 / 关闭应用），Esc 或点击外部关闭
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
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.mac-dock"

  // Native Omarchy has no magnification/bounce; keep the macOS feel strictly opt-in
  // (OMNI_DOCK_MAGNIFY=1). Default = static icons, hover fill only.
  readonly property bool magnify: Quickshell.env("OMNI_DOCK_MAGNIFY") === "1"

  // 默认常用应用
  readonly property var defaultFavorites: [
    { id: "term", name: "终端", icon: Icons.glyph.terminal, exec: "xdg-terminal-exec", matchClass: ["kitty", "alacritty", "foot", "terminal"] },
    { id: "browser", name: "浏览器", icon: Icons.glyph.browser, exec: "google-chrome", matchClass: ["google-chrome", "firefox", "chromium", "zen"] },
    { id: "files", name: "访达/文件", icon: Icons.glyph.folder, exec: "omarchy-file-manager", matchClass: ["thunar", "nautilus", "dolphin", "org.gnome.nautilus"] },
    { id: "code", name: "代码编辑", icon: Icons.glyph.code, exec: "code", matchClass: ["code", "cursor", "vscodium"] },
    { id: "settings", name: "Omni 控制中心", icon: Icons.glyph.settings, exec: "omarchy-shell shell toggle omni.settings", matchClass: [] }
  ]

  property var runningClients: []

  // 组合展示项
  property var dockItems: []

  // ---------- 鱼眼波浪状态 ----------
  // 鼠标在 panel 坐标系中的 X；< 0 表示指针不在 Dock 上
  property real pointerX: -1

  // ---------- 交互状态 ----------
  // 委托单元格注册表（用于按序号触发弹跳动效）
  property var cells: ({})
  // 每个应用 class 的窗口轮转聚焦游标
  property var focusCycle: ({})
  // 右键上下文卡片：contextItem 驱动显隐，contextShown 在淡出期间保留快照内容
  property var contextItem: null
  property var contextShown: null
  property real contextCenterX: 0

  // ---------- 设计令牌 ----------
  // Chrome mirrors omarchy.dock (shell/plugins/dock/DockWindow.qml): [popups] surface
  // for the bar and its context menu, Style state fills, Color.urgent for alerts.
  readonly property color dangerColor: Commons.Color.urgent
  readonly property var popupBorderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))

  function open(payloadJson) {
    root.opened = true
    refreshClients()
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    root.closeContextCard()
    if (root.shell && typeof root.shell.hide === "function") root.shell.hide(root.pluginId)
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  function refreshClients() {
    clientsProc.running = false
    clientsProc.running = true
  }

  ShellIpc {
    target: "omni.mac-dock"
    function toggle(): void { root.toggle() }
    function open(): void { root.open("{}") }
    function close(): void { root.dismiss() }
    function refresh(): void { root.refreshClients() }
  }

  // ---------- 窗口动作（全部经 hyprctl dispatch，无绑定修改） ----------
  function focusAddress(addr) {
    if (!addr) return
    var addrStr = (addr.indexOf("address:") === 0) ? addr : ("address:" + addr)
    Quickshell.execDetached(["hyprctl", "dispatch", "focuswindow", addrStr])
  }

  function closeApp(item) {
    if (!item || !item.addresses || item.addresses.length === 0) return
    var parts = []
    for (var i = 0; i < item.addresses.length; i++) {
      parts.push("dispatch closewindow address:" + item.addresses[i])
    }
    Quickshell.execDetached(["hyprctl", "--batch", parts.join(" ; ")])
  }

  function launchExec(execCmd) {
    if (!execCmd) return
    if (String(execCmd).indexOf("omarchy-shell") === 0) root.dismiss()
    Quickshell.execDetached(["bash", "-c", execCmd])
  }

  // 多窗口实例顺序轮转：返回本次应聚焦的窗口地址
  function cycleAddress(item) {
    if (!item || !item.addresses || item.addresses.length === 0) return ""
    var n = item.addresses.length
    if (n === 1) return item.addresses[0]
    var key = String(item.classKey || item.id || item.name)
    var prev = root.focusCycle[key] || 0
    root.focusCycle[key] = prev + 1
    return item.addresses[prev % n]
  }

  function indexOfItem(item) {
    if (!item) return -1
    for (var i = 0; i < root.dockItems.length; i++) {
      if (root.dockItems[i] === item || root.dockItems[i].id === item.id) return i
    }
    return -1
  }

  function bounceAt(index) {
    var c = root.cells[index]
    if (c && typeof c.bounce === "function") c.bounce()
  }

  function activateOrLaunch(item, at) {
    if (item.isRunning && item.windowCount > 0) {
      root.focusAddress(root.cycleAddress(item))
    } else if (item.exec) {
      root.launchExec(item.exec)
    }
    root.bounceAt(at === undefined ? root.indexOfItem(item) : at)
    postActionTimer.restart()
  }

  // ---------- 右键上下文卡片 ----------
  function openContextCard(item, centerX) {
    root.contextCenterX = centerX
    root.contextItem = item
  }

  function closeContextCard() {
    root.contextItem = null
  }

  onContextItemChanged: {
    if (root.contextItem) root.contextShown = root.contextItem
  }

  function contextActions(item) {
    var acts = []
    if (!item) return acts
    if (item.isRunning && item.windowCount > 0) {
      acts.push({ key: "focus", icon: Icons.glyph.focus, label: "聚焦", danger: false })
      if (item.windowCount > 1) {
        acts.push({ key: "cycle", icon: Icons.glyph.cycle, label: "下一窗口 (" + item.windowCount + ")", danger: false })
      }
    }
    if (item.exec) {
      acts.push({ key: "new", icon: Icons.glyph.plus, label: item.isRunning ? "新建" : "启动", danger: false })
    }
    if (item.isRunning && item.windowCount > 0) {
      acts.push({ key: "close", icon: Icons.glyph.close, label: "关闭", danger: true })
    }
    return acts
  }

  function runContextAction(key) {
    var it = root.contextItem
    if (!it) return
    if (key === "focus") {
      root.focusAddress(it.runningAddress || it.addresses[0])
    } else if (key === "cycle") {
      root.focusAddress(root.cycleAddress(it))
    } else if (key === "new") {
      root.launchExec(it.exec)
    } else if (key === "close") {
      root.closeApp(it)
    }
    root.bounceAt(root.indexOfItem(it))
    postActionTimer.restart()
    root.closeContextCard()
  }

  function resolveAppGlyph(cls) {
    return Icons.appForClass(cls)
  }

  function rebuildItems() {
    // 同一 class 的窗口聚合：计数 + 地址列表 + 标题列表（仅元数据，零像素抓取 H-5）
    var groups = {}
    var order = []
    for (var c = 0; c < root.runningClients.length; c++) {
      var client = root.runningClients[c]
      var cls = String(client.class || "").toLowerCase()
      if (!cls) continue
      if (!groups[cls]) {
        groups[cls] = { addresses: [], titles: [] }
        order.push(cls)
      }
      groups[cls].addresses.push(client.address)
      groups[cls].titles.push(String(client.title || ""))
    }

    var items = []
    var consumed = {}

    // 先加入收藏夹（聚合同类多实例）
    for (var i = 0; i < root.defaultFavorites.length; i++) {
      var fav = root.defaultFavorites[i]
      var addrs = []
      var titles = []
      var key = ""
      for (var m = 0; m < fav.matchClass.length; m++) {
        var mc = String(fav.matchClass[m]).toLowerCase()
        if (groups[mc]) {
          consumed[mc] = true
          if (!key) key = mc
          for (var a = 0; a < groups[mc].addresses.length; a++) {
            addrs.push(groups[mc].addresses[a])
            titles.push(groups[mc].titles[a])
          }
        }
      }
      items.push({
        id: fav.id,
        classKey: key,
        name: fav.name,
        icon: fav.icon,
        exec: fav.exec || "",
        isRunning: addrs.length > 0,
        runningAddress: addrs.length > 0 ? addrs[0] : "",
        addresses: addrs,
        windowCount: addrs.length,
        windowTitles: titles,
        isCustom: false
      })
    }

    // 再追加未匹配收藏夹的运行中应用（每个 class 一项，携带实例计数）
    for (var j = 0; j < order.length; j++) {
      var clsKey = order[j]
      if (consumed[clsKey]) continue
      var g = groups[clsKey]
      items.push({
        id: "app:" + clsKey,
        classKey: clsKey,
        name: clsKey.charAt(0) + clsKey.slice(1),
        icon: root.resolveAppGlyph(clsKey),
        exec: "",
        isRunning: true,
        runningAddress: g.addresses[0],
        addresses: g.addresses,
        windowCount: g.addresses.length,
        windowTitles: g.titles,
        isCustom: true
      })
    }

    root.dockItems = items
  }

  // ---------- 进程与定时器 ----------
  Process {
    id: clientsProc
    command: ["hyprctl", "clients", "-j"]
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() {
        var raw = text  // streamFinished() carries no args; read StdioCollector.text
        if (!raw || raw.trim() === "") return
        try {
          var parsed = JSON.parse(raw)
          if (Array.isArray(parsed)) {
            root.runningClients = parsed.filter(function(x) { return x && x.mapped })
            root.rebuildItems()
          }
        } catch(e) {}
      }
    }
  }

  // 动作执行后轻量回刷（等 hyprland 完成聚焦/关闭，不做按键监听）
  Timer {
    id: postActionTimer
    interval: 400
    repeat: false
    onTriggered: root.refreshClients()
  }

  // 指针跨相邻单元格间隙的宽限：短暂离开不视为离开 Dock，避免鱼眼抖动
  Timer {
    id: pointerGrace
    interval: 90
    repeat: false
    onTriggered: root.pointerX = -1
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { bottom: true; left: true; right: true }
    implicitHeight: Style.space(90)
    color: "transparent"
    WlrLayershell.namespace: "omni-mac-dock"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    // 居中 Dock 胶囊条
    BorderSurface {
      id: dockBar
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(12)
      anchors.horizontalCenter: parent.horizontalCenter
      width: contentRow.implicitWidth + Style.space(24)
      height: Style.space(64)
      radius: Style.cornerRadius
      color: Commons.Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Style.normalBorderWidth)


      Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: Style.space(8)

        Repeater {
          model: root.dockItems

          delegate: Item {
            id: dockItemWrapper
            required property var modelData
            required property int index

            // ---------- 鱼眼波浪计算 ----------
            // 单元格中心（panel 坐标）。显式读取祖先链布局属性，Row 重排时绑定自动重估。
            readonly property real cellCenterX: dockBar.x + contentRow.x + dockItemWrapper.x + dockItemWrapper.width / 2
            // 高斯扩散系数：中心图标最大 1.35x，按距离连续衰减
            readonly property real waveFalloff: {
              if (root.pointerX < 0) return 0
              var d = root.pointerX - dockItemWrapper.cellCenterX
              var sigma = Style.space(54)
              return Math.exp(-(d * d) / (2 * sigma * sigma))
            }
            readonly property real iconScale: root.magnify ? 1.0 + 0.35 * dockItemWrapper.waveFalloff : 1.0

            width: Style.space(50)
            height: Style.space(56)
            z: dockItemWrapper.iconScale > 1.03 ? 2 : 0

            Component.onCompleted: root.cells[dockItemWrapper.index] = dockItemWrapper
            Component.onDestruction: {
              if (root.cells[dockItemWrapper.index] === dockItemWrapper) delete root.cells[dockItemWrapper.index]
            }

            function bounce() {
              if (root.magnify && !Style.reduceMotion) bounceAnim.restart()
            }

            // 纵向弹性起跳槽：点击/激活时整槽上跳，带阻尼回落
            Item {
              id: bounceSlot
              anchors.fill: parent

              SequentialAnimation {
                id: bounceAnim
                NumberAnimation {
                  target: bounceSlot
                  property: "y"
                  to: -Style.space(13)
                  duration: Style.duration(140)
                  easing.type: Easing.OutCubic
                }
                NumberAnimation {
                  target: bounceSlot
                  property: "y"
                  to: 0
                  duration: 430
                  easing.type: Easing.OutElastic
                }
              }

              // 图标容器（底边固定，鱼眼缩放向上生长）
              BorderSurface {
                id: iconBox
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Style.space(6)
                anchors.horizontalCenter: parent.horizontalCenter
                width: Style.space(42) * dockItemWrapper.iconScale
                height: width
                radius: Style.cornerRadius
                color: dockItemWrapper.waveFalloff > 0.02
                  ? Style.hoverFillFor(Commons.Color.popups.text, Commons.Color.accent)
                  : Style.normalFillFor(Commons.Color.popups.text, Commons.Color.accent)
                borderSpec: Border.controlSpec(dockItemWrapper.waveFalloff > 0.5 ? "hover-cursor" : "normal", Commons.Color.popups.text, Commons.Color.accent)
                Behavior on width { enabled: root.magnify; SpringAnimation { spring: 3.2; damping: 0.62; epsilon: 0.001 } }

                Text {
                  font.family: Style.font.family
                  text: dockItemWrapper.modelData.icon
                  font.pixelSize: Math.max(10, Math.round(iconBox.width * 0.43))
                  color: Commons.Color.popups.text
                  anchors.centerIn: parent
                }

                // 多窗口实例计数角标
                Rectangle {
                  id: instanceBadge
                  visible: dockItemWrapper.modelData.windowCount > 1
                  anchors {
                    top: parent.top
                    right: parent.right
                    topMargin: -Style.space(3)
                    rightMargin: -Style.space(3)
                  }
                  width: Math.max(Style.space(16), badgeText.implicitWidth + Style.space(8))
                  height: Style.space(16)
                  radius: Style.cornerRadius
                  color: Commons.Color.accent

                  Text {
                    id: badgeText
                    anchors.centerIn: parent
                    text: dockItemWrapper.modelData.windowCount
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    color: Commons.Color.background
                  }
                }
              }
            }

            // 运行中指示圆点 (macOS 样式)
            Rectangle {
              visible: dockItemWrapper.modelData.isRunning
              anchors.bottom: parent.bottom
              anchors.horizontalCenter: parent.horizontalCenter
              width: Style.space(4)
              height: Style.space(4)
              radius: Style.cornerRadius
              color: Commons.Color.popups.text
            }

            // 悬停提示（卡片打开时让位）— same [tooltip] chrome native Button/PanelToolTip paint
            BorderSurface {
              id: tip
              readonly property var spec: Border.surfaceSpec("tooltip", "border", Commons.Color.tooltip.border, Math.max(1, Style.normalBorderWidth))
              visible: itemHover.containsMouse && root.contextItem === null
              anchors.bottom: iconBox.top
              anchors.bottomMargin: Style.space(8)
              anchors.horizontalCenter: parent.horizontalCenter
              width: tipText.implicitWidth + Style.spacing.controlPaddingX * 2 + Border.left(spec) + Border.right(spec)
              height: tipText.implicitHeight + Style.spacing.controlPaddingY * 2 + Border.top(spec) + Border.bottom(spec)
              radius: 0
              color: Commons.Color.tooltip.background
              borderSpec: spec

              Text {
                id: tipText
                textFormat: Text.PlainText
                text: dockItemWrapper.modelData.name
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                color: Commons.Color.tooltip.text
                anchors.centerIn: parent
              }
            }

            MouseArea {
              id: itemHover
              anchors.fill: parent
              hoverEnabled: true
              acceptedButtons: Qt.LeftButton | Qt.RightButton
              cursorShape: Qt.PointingHandCursor
              onPositionChanged: function(mouse) {
                root.pointerX = mapToItem(panel, mouse.x, 0).x
              }
              onEntered: pointerGrace.stop()
              onExited: pointerGrace.restart()
              onClicked: function(mouse) {
                if (mouse.button === Qt.RightButton) {
                  root.openContextCard(dockItemWrapper.modelData, dockItemWrapper.cellCenterX)
                } else {
                  root.activateOrLaunch(dockItemWrapper.modelData, dockItemWrapper.index)
                }
              }
            }
          }
        }
      }
    }
  }

  // ---------- 右键上下文动作卡片（独立浮层，点击外部 / Esc 自动关闭） ----------
  PanelWindow {
    id: cardPanel
    visible: root.opened && root.contextItem !== null
    anchors { bottom: true; left: true; right: true }
    implicitHeight: Style.space(340)
    color: "transparent"
    WlrLayershell.namespace: "omni-mac-dock-card"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: cardPanel.visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    // 外部点击捕获（仅卡片打开期间存在输入占位）
    MouseArea {
      anchors.fill: parent
      enabled: cardPanel.visible
      onClicked: root.closeContextCard()
    }

    Item {
      id: escCatcher
      anchors.fill: parent
      focus: cardPanel.visible
      Keys.onEscapePressed: root.closeContextCard()
    }

    // Context menu card = omarchy.dock's menu chrome: [popups] BorderSurface + native rows.
    BorderSurface {
      id: contextCard
      property var shown: root.contextShown
      property var actions: root.contextActions(root.contextItem || root.contextShown)
      property real anchorX: root.contextCenterX

      width: Style.space(238)
      height: contextCardCol.implicitHeight + contentTopInset + contentBottomInset
      // 悬于 Dock 胶囊条正上方（bar 高 64 + 底边距 12 + 间隙 10），并防止贴边溢出
      x: Math.max(Style.space(10), Math.min(anchorX - width / 2, cardPanel.width - width - Style.space(10)))
      y: cardPanel.height - Style.space(86) - height
      radius: Style.cornerRadius
      color: Commons.Color.popups.background
      borderSpec: root.popupBorderSpec
      padding: Style.spacing.sm
      opacity: root.contextItem !== null ? 1 : 0
      visible: root.contextItem !== null || opacity > 0
      Behavior on opacity { NumberAnimation { duration: Style.duration(140); easing.type: Easing.OutQuad } }


      Column {
        id: contextCardCol
        x: contextCard.contentLeftInset
        y: contextCard.contentTopInset
        width: contextCard.width - contextCard.contentLeftInset - contextCard.contentRightInset
        spacing: Style.spacing.sm

        // 头部：应用图标 + 全称 + 运行状态 — native PanelHero
        PanelHero {
          foreground: Commons.Color.popups.text
          title: contextCard.shown ? contextCard.shown.name : ""
          meta: {
            if (!contextCard.shown) return ""
            if (!contextCard.shown.isRunning) return "未运行"
            var n = contextCard.shown.windowCount || 1
            var t = (contextCard.shown.windowTitles && contextCard.shown.windowTitles[0]) || ""
            return "运行中 · " + n + " 个窗口" + (t ? " · " + t : "")
          }
          iconComponent: Text {
            textFormat: Text.PlainText
            text: contextCard.shown ? contextCard.shown.icon : ""
            font.family: Style.font.family
            font.pixelSize: Style.font.display
            color: Commons.Color.popups.text
          }
        }

        PanelSeparator { foreground: Commons.Color.popups.text }

        // 快捷动作行 — native Button rows (danger rows tinted with Color.urgent)
        Repeater {
          model: contextCard.actions

          delegate: Button {
            id: actionRow
            required property var modelData
            width: contextCardCol.width
            leftAlign: true
            iconText: modelData.icon
            text: modelData.label
            fontSize: Style.font.bodySmall
            iconSize: Style.font.caption
            foreground: modelData.danger ? root.dangerColor : Commons.Color.popups.text
            accent: modelData.danger ? root.dangerColor : Commons.Color.accent
            onClicked: root.runContextAction(actionRow.modelData.key)
          }
        }
      }
    }
  }
}
