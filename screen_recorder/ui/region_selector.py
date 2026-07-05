from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QDialog, QWidget


MIN_REGION_SIZE = 80
HANDLE_SIZE = 10


class RegionSelector(QDialog):
    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self._start = QPoint()
        self._end = QPoint()
        self._selected = QRect()
        self._dragging = False
        self._mouse_grabbed = False
        primary_screen = QApplication.primaryScreen()
        self._virtual_geometry = (
            primary_screen.virtualGeometry()
            if primary_screen is not None
            else QApplication.desktop().geometry()
        )
        self.setGeometry(self._virtual_geometry)

    def selected_rect(self) -> QRect:
        return logical_rect_to_capture_rect(self.selected_logical_rect())

    def selected_logical_rect(self) -> QRect:
        rect = self._selected.normalized()
        top_left = self.mapToGlobal(rect.topLeft())
        return QRect(top_left, rect.size())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start = event.pos()
            self._end = self._start
            self._selected = QRect()
            self.grabMouse()
            self._mouse_grabbed = True
            self.update()
        elif event.button() == Qt.RightButton:
            self.reject()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._end = event.pos()
            selected = QRect(self._start, self._end).normalized()
            self._selected = selected if selected.width() > 10 and selected.height() > 10 else QRect()
            self._release_mouse_if_needed()
            self.update()
            if self._selected.isValid():
                self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self._selected.isValid() and self._selected.width() > 10 and self._selected.height() > 10:
                self.accept()

    def showEvent(self, event) -> None:
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.ActiveWindowFocusReason)
        super().showEvent(event)

    def reject(self) -> None:
        self._release_mouse_if_needed()
        super().reject()

    def accept(self) -> None:
        self._release_mouse_if_needed()
        super().accept()

    def _release_mouse_if_needed(self) -> None:
        if self._mouse_grabbed:
            self.releaseMouse()
            self._mouse_grabbed = False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

        rect = QRect(self._start, self._end).normalized() if self._dragging else self._selected.normalized()
        if rect.isValid():
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(46, 204, 113), 2))
            painter.drawRect(rect)

        painter.setPen(QColor(255, 255, 255))
        hint = "Drag to select an area, release to confirm, Esc/right-click to cancel"
        painter.drawText(
            24,
            36,
            hint,
        )


class RegionFrame(QWidget):
    region_changed = pyqtSignal(QRect)

    def __init__(self, rect: QRect):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._drag_mode = ""
        self._drag_start = QPoint()
        self._start_geometry = QRect()
        self.setGeometry(rect.normalized())
        self.show()

    def capture_rect(self) -> QRect:
        return logical_rect_to_capture_rect(self.geometry())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_mode = self._hit_test(event.pos()) or "move"
            self._drag_start = event.globalPos()
            self._start_geometry = self.geometry()
            self.grabMouse()
        elif event.button() == Qt.RightButton:
            self.hide()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode:
            self._apply_drag(event.globalPos() - self._drag_start)
        else:
            self._update_cursor(self._hit_test(event.pos()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_mode:
            self._drag_mode = ""
            self.releaseMouse()
            self.region_changed.emit(self.capture_rect())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        border_rect = self.rect().adjusted(2, 2, -3, -3)
        painter.setPen(QPen(QColor(46, 204, 113), 3))
        painter.drawRect(border_rect)

        painter.setBrush(QColor(46, 204, 113))
        painter.setPen(Qt.NoPen)
        for rect in self._handle_rects().values():
            painter.drawRect(rect)

    def _hit_test(self, point: QPoint) -> str:
        for name, rect in self._handle_rects().items():
            if rect.contains(point):
                return name

        margin = HANDLE_SIZE
        left = point.x() <= margin
        right = point.x() >= self.width() - margin
        top = point.y() <= margin
        bottom = point.y() >= self.height() - margin

        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        if left:
            return "left"
        if right:
            return "right"
        return "move"

    def _handle_rects(self) -> dict[str, QRect]:
        size = HANDLE_SIZE
        half = size // 2
        w = self.width()
        h = self.height()
        return {
            "top_left": QRect(0, 0, size, size),
            "top": QRect(w // 2 - half, 0, size, size),
            "top_right": QRect(w - size, 0, size, size),
            "right": QRect(w - size, h // 2 - half, size, size),
            "bottom_right": QRect(w - size, h - size, size, size),
            "bottom": QRect(w // 2 - half, h - size, size, size),
            "bottom_left": QRect(0, h - size, size, size),
            "left": QRect(0, h // 2 - half, size, size),
        }

    def _apply_drag(self, delta: QPoint) -> None:
        rect = QRect(self._start_geometry)
        mode = self._drag_mode

        if mode == "move":
            rect.moveTopLeft(self._start_geometry.topLeft() + delta)
        else:
            if "left" in mode:
                rect.setLeft(rect.left() + delta.x())
            if "right" in mode:
                rect.setRight(rect.right() + delta.x())
            if "top" in mode:
                rect.setTop(rect.top() + delta.y())
            if "bottom" in mode:
                rect.setBottom(rect.bottom() + delta.y())

            if rect.width() < MIN_REGION_SIZE:
                if "left" in mode:
                    rect.setLeft(rect.right() - MIN_REGION_SIZE)
                else:
                    rect.setRight(rect.left() + MIN_REGION_SIZE)
            if rect.height() < MIN_REGION_SIZE:
                if "top" in mode:
                    rect.setTop(rect.bottom() - MIN_REGION_SIZE)
                else:
                    rect.setBottom(rect.top() + MIN_REGION_SIZE)

        self.setGeometry(rect.normalized())
        self.region_changed.emit(self.capture_rect())

    def _update_cursor(self, mode: str) -> None:
        cursors = {
            "top_left": Qt.SizeFDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "move": Qt.SizeAllCursor,
        }
        self.setCursor(cursors.get(mode, Qt.ArrowCursor))


def logical_rect_to_capture_rect(rect: QRect) -> QRect:
    rect = rect.normalized()
    screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    width = max(2, int(rect.width() * ratio))
    height = max(2, int(rect.height() * ratio))
    if width % 2:
        width -= 1
    if height % 2:
        height -= 1
    return QRect(
        int(rect.left() * ratio),
        int(rect.top() * ratio),
        width,
        height,
    )
