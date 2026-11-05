import QtQuick
import QtQuick.Shapes
import "../services"

// A status bar box at any size: dark translucent fill, 15px corners and a 2px accent
// bottom border that thins out around the lower corners (ohmyhypr bar/BarSegment.qml).
Item {
    id: box
    default property alias content: inner.data
    property int padding: 12

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: -1
            fillColor: Style.box
            PathRectangle { width: box.width; height: box.height; radius: Style.radius }
        }
        ShapePath {
            id: border
            readonly property real w: box.width
            readonly property real h: box.height
            readonly property int r: Style.radius
            strokeWidth: -1
            fillColor: Style.border
            PathSvg {
                path: `M 0 ${border.h - border.r} A ${border.r} ${border.r} 0 0 0 ${border.r} ${border.h}`
                    + ` L ${border.w - border.r} ${border.h} A ${border.r} ${border.r} 0 0 0 ${border.w} ${border.h - border.r}`
                    + ` A ${border.r - 2} ${border.r - 2} 0 0 1 ${border.w - border.r + 2} ${border.h - 2}`
                    + ` L ${border.r - 2} ${border.h - 2} A ${border.r - 2} ${border.r - 2} 0 0 1 0 ${border.h - border.r} Z`
            }
        }
    }

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: box.padding
        anchors.bottomMargin: box.padding + 2
    }
}
