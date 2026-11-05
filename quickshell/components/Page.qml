import QtQuick
import QtQuick.Controls
import "../services"

// Scrolling body of a view or tab.
Flickable {
    id: root
    default property alias content: column.data
    property alias spacing: column.spacing

    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    function scroll(pages: real): void {
        contentY = Math.max(0, Math.min(contentHeight - height, contentY + height * 0.8 * pages));
    }

    Column {
        id: column
        width: root.width - 14
        topPadding: 20
        bottomPadding: 20
        spacing: 18
    }
}
