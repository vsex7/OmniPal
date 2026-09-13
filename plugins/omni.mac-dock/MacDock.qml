import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui

// OmniPal macOS 风格底部 Dock 栏（omni.mac-dock）
//
// 特性：
// 1. 底部居中悬浮胶囊卡片，毛玻璃磨砂质感
// 2. 结合常用收藏应用与实时运行中窗口列表（基于 hyprctl clients -j）
// 3. 运行指示小圆点与平滑悬停动效
// 4. 左键聚焦或启动应用，右键关闭窗口
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  readonly property string pluginId: (root.manifest && root.manifest.id) || "omni.mac-dock"

  // 默认常用应用
  readonly property var defaultFavorites: [
    { id: "term", name: "终端", icon: "", exec: "xdg-terminal-exec", matchClass: ["kitty", "alacritty", "foot", "terminal"] },
    { id: "browser", name: "浏览器", icon: "🌐", exec: "google-chrome", matchClass: ["google-chrome", "firefox", "chromium", "zen"] },
    { id: "files", name: "访达/文件", icon: "📁", exec: "omarchy-file-manager", matchClass: ["thunar", "nautilus", "dolphin", "org.gnome.nautilus"] },
    { id: "code", name: "代码编辑", icon: "", exec: "code", matchClass: ["code", "cursor", "vscodium"] },
    { id: "settings", name: "Omni 控制中心", icon: "⚙", exec: "omarchy-shell shell toggle omni.settings", matchClass: [] }
  ]

  property var runningClients: []

  // 组合展示项
  property var dockItems: []

  function open(payloadJson) {
    root.opened = true
    refreshClients()
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

  function refreshClients() {
    clientsProc.running = true
  }

  function activateOrLaunch(item) {
    if (item.runningAddress) {
      dispatchProc.command = ["hyprctl", "dispatch", "hl.dsp.focus({ window = \"address:" + item.runningAddress + "\" })"]
      dispatchProc.running = true
    } else if (item.exec) {
      if (item.exec.indexOf("omarchy-shell") === 0) {
        root.dismiss()
      }
      launchProc.command = ["bash", "-c", item.exec]
      launchProc.running = true
    }
  }

  function rebuildItems() {
    var items = []
    var matchedClasses = {}

    // 先加入收藏夹
    for (var i = 0; i < root.defaultFavorites.length; i++) {
      var fav = root.defaultFavorites[i]
      var isRunning = false
      var addr = ""
      for (var c = 0; c < root.runningClients.length; c++) {
        var client = root.runningClients[c]
        var cls = String(client.class || "").toLowerCase()
        if (fav.matchClass.indexOf(cls) !== -1) {
          isRunning = true
          addr = client.address
          matchedClasses[cls] = true
          break
        }
      }
      items.push({
        name: fav.name,
        icon: fav.icon,
        exec: fav.exec,
        isRunning: isRunning,
        runningAddress: addr,
        isCustom: false
      })
    }

    // 再追加未在收藏夹中的运行中应用
    for (var j = 0; j < root.runningClients.length; j++) {
      var cli = root.runningClients[j]
      var clientCls = String(cli.class || "").toLowerCase()
      if (!matchedClasses[clientCls] && cli.title) {
        matchedClasses[clientCls] = true
        var firstChar = cli.class ? cli.class.charAt(0).toUpperCase() : "🗔"
        items.push({
          name: cli.class || cli.title,
          icon: firstChar,
          exec: "",
          isRunning: true,
          runningAddress: cli.address,
          isCustom: true
        })
      }
    }

    root.dockItems = items
  }

  Process {
    id: clientsProc
    command: ["hyprctl", "clients", "-j"]
    running: false
    stdout: SplitParser {
      onRead: function(data) {
        try {
          var parsed = JSON.parse(data)
          if (Array.isArray(parsed)) {
            root.runningClients = parsed.filter(function(x) { return x && x.mapped })
            root.rebuildItems()
          }
        } catch(e) {}
      }
    }
  }

  Process { id: dispatchProc; command: ["true"]; running: false }
  Process { id: launchProc; command: ["true"]; running: false }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { bottom: true; left: true; right: true }
    height: Style.space(90)
    color: "transparent"
    WlrLayershell.namespace: "omni-mac-dock"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    // 居中 Dock 胶囊条
    Rectangle {
      id: dockBar
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(12)
      anchors.horizontalCenter: parent.horizontalCenter
      width: contentRow.implicitWidth + Style.space(24)
      height: Style.space(64)
      radius: Style.space(18)
      color: Util.alpha(Color.menu.background, 0.88)
      border.width: 1
      border.color: Util.alpha(Color.menu.border, 0.5)

      // 阴影微发光
      Rectangle {
        anchors.fill: parent
        anchors.margins: -1
        radius: parent.radius + 1
        color: "transparent"
        border.width: 1
        border.color: Util.alpha(Color.menu.text, 0.08)
      }

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

            width: Style.space(50)
            height: Style.space(54)

            // 图标容器
            Rectangle {
              id: iconBox
              anchors.top: parent.top
              anchors.horizontalCenter: parent.horizontalCenter
              width: itemHover.containsMouse ? Style.space(48) : Style.space(42)
              height: width
              radius: Style.space(10)
              color: itemHover.containsMouse
                ? Util.alpha(Color.menu.text, 0.16)
                : Util.alpha(Color.menu.text, 0.08)

              Behavior on width { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }

              Text {
                text: modelData.icon
                font.pixelSize: itemHover.containsMouse ? 22 : 18
                color: Color.menu.text
                anchors.centerIn: parent
                Behavior on font.pixelSize { NumberAnimation { duration: 120 } }
              }
            }

            // 运行中指示圆点 (macOS 样式)
            Rectangle {
              visible: modelData.isRunning
              anchors.bottom: parent.bottom
              anchors.horizontalCenter: parent.horizontalCenter
              width: Style.space(4)
              height: Style.space(4)
              radius: Style.space(2)
              color: Color.menu.text
            }

            // 悬停提示
            Rectangle {
              visible: itemHover.containsMouse
              anchors.bottom: iconBox.top
              anchors.bottomMargin: Style.space(8)
              anchors.horizontalCenter: parent.horizontalCenter
              width: tipText.implicitWidth + Style.space(12)
              height: tipText.implicitHeight + Style.space(6)
              radius: 4
              color: Util.alpha(Color.menu.background, 0.95)
              border.width: 1
              border.color: Util.alpha(Color.menu.border, 0.4)

              Text {
                id: tipText
                text: modelData.name
                font.pixelSize: Style.font.caption
                color: Color.menu.text
                anchors.centerIn: parent
              }
            }

            MouseArea {
              id: itemHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.activateOrLaunch(modelData)
            }
          }
        }
      }
    }
  }
}
