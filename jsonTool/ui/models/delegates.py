# jsonTool/ui/models/delegates.py
from PySide6.QtWidgets import QStyledItemDelegate, QLineEdit, QLabel
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QStyle


class SolidEditorDelegate(QStyledItemDelegate):
    """
    General: Fixed "ghosting" issue during editing (available in both Editor and Table).
    """
    def createEditor(self, parent, option, index):
        ed = super().createEditor(parent, option, index)
        if isinstance(ed, QLineEdit):
            ed.setAutoFillBackground(True)
            ed.setAttribute(Qt.WA_OpaquePaintEvent, True)
            pal = ed.palette()
            pal.setColor(QPalette.Base, option.palette.color(QPalette.Base))
            pal.setColor(QPalette.Text, option.palette.color(QPalette.Text))
            ed.setPalette(pal)
        return ed

    def paint(self, painter, option, index):
        if option.state & QStyle.State_Editing:
            painter.save()
            painter.fillRect(option.rect, option.palette.brush(QPalette.Base))
            painter.restore()
            return
        super().paint(painter, option, index)


class OverlayHintDelegate(QStyledItemDelegate):
    """
    General: Display a tooltip near the cell showing "Or: xxx" during editing,
    which automatically hides after editing ends. Applies to QTreeView / QTableView.
    """
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setAutoFillBackground(True)
        editor.setAttribute(Qt.WA_OpaquePaintEvent, True)
        pal = editor.palette()
        pal.setColor(QPalette.Base, option.palette.color(QPalette.Base))
        pal.setColor(QPalette.Text, option.palette.color(QPalette.Text))
        editor.setPalette(pal)

        old_text = index.model().data(index, Qt.DisplayRole)
        if old_text is None:
            old_text = ""

        from PySide6.QtWidgets import QLabel
        hint = QLabel(self.view.viewport())
        hint.setObjectName("oldValueHint")
        hint.setText(f"Or: {str(old_text)}")
        hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        hint.setStyleSheet(
            """
            QLabel#oldValueHint{
                background: rgba(30,30,30,0.88);
                color: rgba(255,255,255,0.92);
                border: 1px solid rgba(255,255,255,0.25);
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 11px;
            }
            """
        )
        hint.hide()
        editor.setProperty("_overlay_hint", hint)
        editor.editingFinished.connect(lambda: self._hide_and_delete_hint(editor))
        return editor

    def setEditorData(self, editor, index):
        val = index.model().data(index, Qt.EditRole)
        editor.setText("" if val is None else str(val))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

        hint = editor.property("_overlay_hint")
        if not hint:
            return

        cell_rect: QRect = self.view.visualRect(index)
        hint.adjustSize()
        size = hint.size()
        below_pos = QPoint(cell_rect.left(), cell_rect.bottom() + 2)
        above_pos = QPoint(cell_rect.left(), cell_rect.top() - size.height() - 2)

        vp = self.view.viewport().rect()
        pos = below_pos
        if pos.y() + size.height() > vp.bottom():
            pos = above_pos

        if pos.x() + size.width() > vp.right():
            pos.setX(max(vp.left(), vp.right() - size.width()))
        if pos.x() < vp.left():
            pos.setX(vp.left())

        hint.move(pos)
        if not hint.isVisible():
            hint.show()
            hint.raise_()

    def destroyEditor(self, editor, index):
        self._hide_and_delete_hint(editor)
        return super().destroyEditor(editor, index)

    def paint(self, painter, option, index):
        if option.state & QStyle.State_Editing:
            painter.fillRect(option.rect, option.palette.brush(QPalette.Base))
            return
        super().paint(painter, option, index)

    def _hide_and_delete_hint(self, editor):
        hint = editor.property("_overlay_hint")
        if hint:
            hint.hide()
            hint.deleteLater()
            editor.setProperty("_overlay_hint", None)
