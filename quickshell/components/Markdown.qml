import QtQuick
import "../services"

// Record and summary bodies are Markdown; Qt renders the common subset.
Text {
    textFormat: Text.MarkdownText
    wrapMode: Text.Wrap
    color: Style.text
    linkColor: Style.accent
    font.family: Style.font
    font.pixelSize: Style.px(13)
    lineHeight: 1.2
    onLinkActivated: link => Qt.openUrlExternally(link)
}
