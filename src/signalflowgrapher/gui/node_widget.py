from PySide6.QtGui import QPainter, QPen, QRegion, QFont
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtCore import Qt, QPointF, QRect
from signalflowgrapher.gui.graph_item import GraphItem
from signalflowgrapher.model.model import (
    PositionedNode, PositionedNodeMovedEvent)


class NodeWidget(GraphItem):
    def __init__(self, owner: PositionedNode, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__owner = owner
        self.__base_radius = 8
        self.__base_circle_width = 3
        self.__base_font_size = 10
        self.__zoom_factor = 1.0
        self.__radius = self.__base_radius
        self.__circle_width = self.__base_circle_width
        self.__size = self.__radius * 2 + self.__circle_width * 2
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.resize(self.__size, self.__size)
        mask = QRegion(0, 0, self.__size, self.__size, QRegion.Ellipse)
        self.setMask(mask)

    def set_zoom_transform(self, zoom_factor):
        self.__zoom_factor = max(0.01, float(zoom_factor))
        self.__radius = max(2, int(round(self.__base_radius * self.__zoom_factor)))
        self.__circle_width = max(
            1, int(round(self.__base_circle_width * self.__zoom_factor)))
        self.__size = self.__radius * 2 + self.__circle_width * 2
        self.resize(self.__size, self.__size)
        mask = QRegion(0, 0, self.__size, self.__size, QRegion.Ellipse)
        self.setMask(mask)

    def paintEvent(self, QPaintEvent):
        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen()
        pen.setWidth(self.__circle_width)
        if self.selected:
            pen.setColor(self.palette().highlight().color())
        else:
            pen.setColor(self.palette().text().color())

        painter.setPen(pen)
        width = 2 * self.__radius
        height = width
        painter.setBrush(self.palette().window())
        painter.drawEllipse(
            self.__circle_width,
            self.__circle_width,
            width,
            height)

        if self.selected:
            pen.setColor(self.palette().highlight().color())
            painter.setPen(pen)
            painter.setBrush(self.palette().highlight())
            font = QFont(self.font())
            font.setPointSizeF(max(6.0, self.__base_font_size * self.__zoom_factor))
            painter.setFont(font)
            rect = QRect(0, 0, self.__size, self.__size)
            painter.drawText(
                rect, Qt.AlignCenter, str(self.get_selection_number()))

        painter.end()

    def node_moved_event(self, event: PositionedNodeMovedEvent):
        """
        Triggered after node has been moved.
        Reacts to node move with move of widget.
        """
        if self.__owner is event.node:
            self.move_relative(event.dx, event.dy)

    def get_center(self) -> QPointF:
        """
        Get the position of the center of the widget.
        """
        return QPointF(self.x() + self.width() / 2,
                       self.y() + self.height() / 2)
