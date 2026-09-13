import QtQuick 2.15
import QtQuick.Layouts 1.15
import Quickshell 1.0
import Quickshell.Io 1.0

Item {
    id: root

    // --- Config ---
    property string stateFilePath: "/run/user/1000/omnipal/state.json"
    property int pollIntervalMs: 2000

    // --- State ---
    property bool engineRunning: false
    property string currentMode: "omarchy"
    property string currentName: "Omarchy 原生模式"
    property int activeBindingsCount: 0

    // --- Display Maps ---
    readonly property var modeIcons: ({
        "windows": "⊞",
        "mac":     "◆",
        "omarchy": "⊡"
    })
    readonly property var modeColors: ({
        "windows": "#0078d4",
        "mac":     "#a2aaad",
        "omarchy": "#a3be8c"
    })
    readonly property var modeNames: ({
        "windows": "Windows 11 习惯模式",
        "mac":     "macOS 习惯模式",
        "omarchy": "Omarchy 原生模式"
    })

    implicitWidth: row.implicitWidth + 16
    implicitHeight: row.implicitHeight + 8

    // --- Polling Timer ---
    Timer {
        id: pollTimer
        interval: root.pollIntervalMs
        running: true
        repeat: true
        onTriggered: statusProcess.running = true
    }

    // --- Status Process (reads state via CLI) ---
    Process {
        id: statusProcess
        command: ["omni-profile", "status", "--json"]
        running: false

        stdout: SplitParser {
            onRead: data => {
                try {
                    const state = JSON.parse(data);
                    root.currentMode = state.mode || "omarchy";
                    root.currentName = state.name || root.modeNames[root.currentMode];
                    root.activeBindingsCount = state.active_bindings_count || 0;
                    root.engineRunning = true;
                } catch (e) {
                    root.engineRunning = false;
                }
            }
        }

        onRunningChanged: {
            if (!running && exitCode !== 0) {
                root.engineRunning = false;
            }
        }
    }

    // --- Cycle Process ---
    Process {
        id: cycleProcess
        command: ["omni-profile", "cycle"]
        running: false

        onRunningChanged: {
            if (!running) {
                // After cycle completes, re-read state
                statusProcess.running = true;
            }
        }
    }

    // --- Cheatsheet Process ---
    Process {
        id: cheatsheetProcess
        command: ["omni-profile", "cheatsheet"]
        running: false

        stdout: SplitParser {
            onRead: data => {
                console.log("OmniPal Cheatsheet:\n" + data);
            }
        }
    }

    // --- Derived ---
    property color currentColor: root.modeColors[root.currentMode] || "#a3be8c"

    // --- Helpers ---

    function cycleMode() {
        if (cycleProcess.running) return;
        cycleProcess.running = true;
    }

    function showCheatsheet() {
        if (cheatsheetProcess.running) return;
        cheatsheetProcess.running = true;
    }

    // --- Visuals ---

    Rectangle {
        anchors.fill: parent
        radius: 4
        color: root.engineRunning
            ? Qt.rgba(root.currentColor.r, root.currentColor.g, root.currentColor.b, 0.15)
            : Qt.rgba(0.5, 0.5, 0.5, 0.1)
        border.width: 1
        border.color: root.engineRunning
            ? Qt.rgba(root.currentColor.r, root.currentColor.g, root.currentColor.b, 0.3)
            : Qt.rgba(0.5, 0.5, 0.5, 0.2)
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 4

        Text {
            text: root.engineRunning
                ? (root.modeIcons[root.currentMode] || "?")
                : "⊘"
            font.family: "monospace"
            font.pixelSize: 14
            font.bold: true
            color: root.engineRunning ? root.currentColor : "#bf616a"
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.engineRunning
                ? root.currentMode.toUpperCase()
                : "OFF"
            font.family: "monospace"
            font.pixelSize: 11
            font.weight: Font.Medium
            color: root.engineRunning ? "#d8dee9" : "#65737e"
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    // --- Tooltip ---
    Rectangle {
        id: tooltip
        visible: mouseArea.containsMouse
        width: tooltipText.implicitWidth + 12
        height: tooltipText.implicitHeight + 8
        radius: 4
        color: "#2e3440"
        border.color: "#4c566a"
        border.width: 1
        anchors.bottom: parent.top
        anchors.bottomMargin: 6
        anchors.horizontalCenter: parent.horizontalCenter
        opacity: mouseArea.containsMouse ? 1 : 0
        z: 100

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Text {
            id: tooltipText
            anchors.centerIn: parent
            text: {
                if (!root.engineRunning)
                    return "OmniPal Engine 未运行\n启动: omni-profile daemon";
                return (root.modeNames[root.currentMode] || root.currentMode)
                    + "\n生效快捷键: " + root.activeBindingsCount
                    + "\n左键: 切换模式 | 右键: 速查表";
            }
            font.family: "monospace"
            font.pixelSize: 10
            color: "#d8dee9"
            lineHeight: 1.3
            horizontalAlignment: Text.AlignHCenter
        }
    }

    // --- Mouse ---
    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton

        onClicked: mouse => {
            if (mouse.button === Qt.LeftButton) {
                root.cycleMode();
            } else if (mouse.button === Qt.RightButton) {
                root.showCheatsheet();
            }
        }
    }
}
