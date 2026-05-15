from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QMouseEvent, QCursor, QResizeEvent
from PySide6.QtWidgets import QWidget, QApplication, QMessageBox, QRubberBand
from signalflowgrapher.gui.grid import FixedGrid, NoneGrid
from signalflowgrapher.gui.fixed_grid_widget import FixedGridWidget
from signalflowgrapher.gui.branch_widget import (
    BranchWidget, Spline1HandleWidget, Spline2HandleWidget,
    SplineHandleWidgetMoveEvent, SplineHandleWidgetPressEvent,
    SplineHandleWidgetReleaseEvent, WidgetClickEvent)
from signalflowgrapher.commands.command_handler import CommandHandler
from signalflowgrapher.model.model import (
    Model, CurvedBranchAddedEvent, CurvedBranchRemovedEvent,
    CurvedBranchTransformedEvent, GraphChangedEvent, GraphMovedEvent,
    LabelChangedTextEvent, LabelMovedEvent,
    LabeledObject, PositionedNodeAddedEvent,
    PositionedNodeMovedEvent, PositionedNodeRemovedEvent,
    PositionedNode, CurvedBranch)
from signalflowgrapher.gui.node_widget import NodeWidget
from signalflowgrapher.controllers.main_controller import MainController
from signalflowgrapher.gui.label_widget import LabelWidget
from signalflowgrapher.gui.graph_item import (
    WidgetMoveEvent, WidgetPressEvent, WidgetReleaseEvent, GraphItem)
from signalflowgrapher.common.observable import ValueObservable
import json
import logging
logger = logging.getLogger(__name__)


class GraphField(QWidget):
    def __init__(self,
                 controller: MainController,
                 model: Model,
                 command_handler: CommandHandler):
        super(GraphField, self).__init__()
        self.__controller = controller
        self.__model = model
        self.__command_handler = command_handler

        self.__model.observe(self.__handle_model_change)
        self.__selection = list()
        self.selection = ValueObservable(())
        self.__handles = list()
        self.__model_widget_map = {}
        self.__widget_model_map = {}
        self.__model_label_map = {}
        self.__label_model_map = {}
        self.__mouse_press_pos: QPoint = None
        self.__selection_rect = None
        self.__grid_size_base = 30
        self.__zoom_factor = 1.0
        self.__zoom_min = 0.25
        self.__zoom_max = 4.0
        self.__zoom_step = 1.25
        self.__zoom_origin = QPointF(self.width() / 2, self.height() / 2)
        self.__grid_size = self.__scaled_grid_size()
        self.__grid = FixedGrid(self.__grid_size)
        self.__grid_widget = FixedGridWidget(self.__grid_size, parent=self)
        self.__grid_widget.resize(self.size())
        self.__grid_widget.show()
        self.__grid_offset = QPoint()
        self.__rubber_band: QRubberBand = QRubberBand(
            QRubberBand.Rectangle, self)

        self.setMinimumSize(800, 600)

    def on_esc_press(self):
        self.__clear_selection()

    def zoom_in(self):
        self.__set_zoom_factor(self.__zoom_factor * self.__zoom_step)

    def zoom_out(self):
        self.__set_zoom_factor(self.__zoom_factor / self.__zoom_step)

    def reset_zoom(self):
        self.__set_zoom_factor(1.0)

    def __scaled_grid_size(self):
        return max(1, int(round(self.__grid_size_base * self.__zoom_factor)))

    def __to_view_point(self, point: QPointF) -> QPointF:
        return QPointF(
            self.__zoom_origin.x()
            + ((point.x() - self.__zoom_origin.x()) * self.__zoom_factor),
            self.__zoom_origin.y()
            + ((point.y() - self.__zoom_origin.y()) * self.__zoom_factor))

    def __to_model_point(self, point: QPointF) -> QPointF:
        return QPointF(
            self.__zoom_origin.x()
            + ((point.x() - self.__zoom_origin.x()) / self.__zoom_factor),
            self.__zoom_origin.y()
            + ((point.y() - self.__zoom_origin.y()) / self.__zoom_factor))

    def __to_model_delta(self, dx: int, dy: int) -> QPoint:
        return QPoint(int(round(dx / self.__zoom_factor)),
                      int(round(dy / self.__zoom_factor)))

    def __set_zoom_factor(self, factor):
        new_factor = min(self.__zoom_max, max(self.__zoom_min, float(factor)))
        if new_factor == self.__zoom_factor:
            return

        self.__zoom_factor = new_factor
        self.__apply_zoom()

    def zoom_to_fit(self, margin_px: int = 20):
        """Zoom the view so that the whole graph fits into the viewport.

        The algorithm:
        - Compute the bounding box of all model points (nodes and branch control
          points) in model coordinates.
        - Compute the zoom factor so the bounding box (plus margin) fits the
          viewport while clamping to min/max zoom.
        - Apply the new zoom factor and then translate the graph so the
          bounding-box center maps to the viewport center.
        """
        # Nothing to fit
        if not self.__model_widget_map:
            return

        # Collect model-space points to consider for bounding box
        xs = []
        ys = []

        for m in self.__model_widget_map.keys():
            # Nodes
            if hasattr(m, "x") and hasattr(m, "y"):
                xs.append(m.x)
                ys.append(m.y)

            # Branches (curves) may expose spline control points
            if hasattr(m, "spline1_x") and hasattr(m, "spline1_y"):
                xs.append(m.spline1_x)
                ys.append(m.spline1_y)
            if hasattr(m, "spline2_x") and hasattr(m, "spline2_y"):
                xs.append(m.spline2_x)
                ys.append(m.spline2_y)

        if not xs or not ys:
            return

        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        graph_width = max(1, max_x - min_x)
        graph_height = max(1, max_y - min_y)

        viewport_w = max(1, self.width())
        viewport_h = max(1, self.height())

        available_w = max(1, viewport_w - 2 * margin_px)
        available_h = max(1, viewport_h - 2 * margin_px)

        # Desired zoom such that graph fits into available viewport space
        desired_zx = available_w / float(graph_width)
        desired_zy = available_h / float(graph_height)
        desired_z = min(desired_zx, desired_zy)

        # Clamp and apply
        desired_z = min(self.__zoom_max, max(self.__zoom_min, desired_z))

        # Apply an initial zoom (this will repaint and set internal sizes)
        self.__set_zoom_factor(desired_z)

        # After applying zoom, ensure widget extents (node/branch sizes)
        # also fit within the available viewport area. If not, scale down
        # the zoom further.
        widgets = list(self.__model_widget_map.values())
        if widgets:
            vw_min_x = min(w.x() for w in widgets)
            vw_max_x = max(w.x() + w.width() for w in widgets)
            vw_min_y = min(w.y() for w in widgets)
            vw_max_y = max(w.y() + w.height() for w in widgets)

            vw_width = max(1, vw_max_x - vw_min_x)
            vw_height = max(1, vw_max_y - vw_min_y)

            # If the widgets exceed available area, compute scale factor
            scale_x = available_w / float(vw_width)
            scale_y = available_h / float(vw_height)
            scale = min(scale_x, scale_y, 1.0)

            if scale < 1.0:
                # Reduce zoom to accommodate widget sizes
                new_z = self.__zoom_factor * scale
                new_z = min(self.__zoom_max, max(self.__zoom_min, new_z))
                self.__set_zoom_factor(new_z)

                # Recompute widget bbox after scaling
                widgets = list(self.__model_widget_map.values())
                vw_min_x = min(w.x() for w in widgets)
                vw_max_x = max(w.x() + w.width() for w in widgets)
                vw_min_y = min(w.y() for w in widgets)
                vw_max_y = max(w.y() + w.height() for w in widgets)

        # Center bbox in view by moving model and grid offset
        model_cx = min_x + graph_width / 2.0
        model_cy = min_y + graph_height / 2.0

        # Current bbox center in view coords
        bbox_center_view = self.__to_view_point(QPointF(model_cx, model_cy))

        viewport_center_x = self.width() // 2
        viewport_center_y = self.height() // 2

        dx = int(round(viewport_center_x - bbox_center_view.x()))
        dy = int(round(viewport_center_y - bbox_center_view.y()))

        model_move = self.__to_model_delta(dx, dy)

        # Move model and update grid offset
        self.__model.move_graph_relative(model_move.x(), model_move.y())
        self.__grid_offset += QtCore.QPoint(dx, dy)
        self.__grid.set_offset(self.__grid_offset)
        self.__grid_widget.set_offset(self.__grid_offset)
        self.__grid_widget.repaint()

    def __apply_zoom(self):
        self.__zoom_origin = QPointF(self.width() / 2, self.height() / 2)

        scaled_grid_size = self.__scaled_grid_size()
        if scaled_grid_size != self.__grid_size:
            self.__grid_size = scaled_grid_size
            if isinstance(self.__grid, NoneGrid):
                self.__grid = NoneGrid()
            else:
                self.__grid = FixedGrid(self.__grid_size)
            self.__grid_widget.set_grid_size(self.__grid_size)

        self.__grid.set_offset(self.__grid_offset)
        self.__grid_widget.set_offset(self.__grid_offset)

        for model, widget in self.__model_widget_map.items():
            if isinstance(widget, NodeWidget):
                widget.set_zoom_transform(self.__zoom_factor)
                center = self.__to_view_point(QPointF(model.x, model.y))
                widget.move(QPoint(
                    int(round(center.x() - widget.width() / 2)),
                    int(round(center.y() - widget.height() / 2))))
            elif isinstance(widget, BranchWidget):
                widget.set_zoom_transform(self.__zoom_factor,
                                          self.__zoom_origin)

        for label in self.__model_label_map.values():
            label.set_zoom_transform(self.__zoom_factor)

        for handle in self.__handles:
            handle.set_zoom_transform(self.__zoom_factor,
                                      self.__zoom_origin)

        self.__grid_widget.repaint()

    def __scaled_graph_event(self, event):
        return GraphMovedEvent(event.nodes,
                               event.branches,
                               int(round(event.dx * self.__zoom_factor)),
                               int(round(event.dy * self.__zoom_factor)))

    def on_ctrl_press(self):
        self.__grid = NoneGrid()

    def on_ctrl_release(self):
        self.__grid = FixedGrid(self.__grid_size)
        self.__grid.set_offset(self.__grid_offset)
        self.__grid_widget.lower()

    def center_graph(self):
        """Center the whole graph inside the view."""

        # Compute bounding box of all widgets
        if not self.__model_widget_map:
            return  # Nothing to center

        widgets = list(self.__model_widget_map.values())

        min_x = min(w.x() for w in widgets)
        max_x = max(w.x() + w.width() for w in widgets)
        min_y = min(w.y() for w in widgets)
        max_y = max(w.y() + w.height() for w in widgets)

        graph_width = max_x - min_x
        graph_height = max_y - min_y

        # Center position inside viewport
        viewport_center_x = self.width() // 2
        viewport_center_y = self.height() // 2

        graph_center_x = min_x + graph_width // 2
        graph_center_y = min_y + graph_height // 2

        dx = viewport_center_x - graph_center_x
        dy = viewport_center_y - graph_center_y
        model_dx = self.__to_model_delta(dx, dy)

        # Move graph and update grid offset
        self.__model.move_graph_relative(model_dx.x(), model_dx.y())
        self.__grid_offset += QtCore.QPoint(dx, dy)
        self.__grid.set_offset(self.__grid_offset)
        self.__grid_widget.set_offset(self.__grid_offset)
        self.__grid_widget.repaint()


    def __selection_changed(self):
        self.selection.set(tuple(self.__widget_model_map.get(widget)
                                 for widget in self.__selection))

    def mousePressEvent(self, event: QMouseEvent):
        logger.debug("MousePressEvent")
        if event.button() == Qt.LeftButton:
            self.__mouse_press_pos = event.globalPosition().toPoint()
            self.__command_handler.start_script()

            if event.modifiers() == Qt.AltModifier:
                self.__rubber_band.setGeometry(
                    QRect(self.mapFromGlobal(self.__mouse_press_pos), QSize())
                )
                self.__rubber_band.show()
                self.__clear_selection()

    def mouseReleaseEvent(self, event: QMouseEvent):
        logger.debug("MouseReleaseEvent")
        if self.__mouse_press_pos is not None:
            self.__command_handler.end_script()
        self.__mouse_press_pos = None
        self.setCursor(QCursor(Qt.ArrowCursor))

        if self.__rubber_band.isVisible():
            self.__rubber_band.hide()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            grid_pos = self.__grid.get_grid_position(event.position().toPoint())
            model_pos = self.__to_model_point(
                QPointF(grid_pos.x(), grid_pos.y()))
            self.__controller.create_node(int(round(model_pos.x())),
                                          int(round(model_pos.y())))

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.__mouse_press_pos is not None:

            global_position = event.globalPosition().toPoint()
            diff = global_position - self.__mouse_press_pos
            if self.__rubber_band.isVisible():
                self.__rubber_band.setGeometry(
                    QRect(self.mapFromGlobal(self.__mouse_press_pos),
                        event.position().toPoint()).normalized())
                # Add to selection if inside rubber band remove otherwise
                for widget in self.__model_widget_map.values():
                    if self.__rubber_band.geometry().contains(
                            widget.geometry()):
                        self.__add_selection(widget)
                    else:
                        self.__remove_selection(widget)
            else:
                self.setCursor(QCursor(Qt.ClosedHandCursor))
                self.__grid_offset += diff
                self.__grid.set_offset(self.__grid_offset)
                self.__grid_widget.set_offset(self.__grid_offset)
                self.__grid_widget.repaint()
                model_move = self.__to_model_delta(diff.x(), diff.y())
                self.__model.move_graph_relative(model_move.x(),
                                                 model_move.y())
                self.__mouse_press_pos = global_position

    def __on_label_click(self, event):
        if isinstance(event, WidgetPressEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.start_script()
                self.__grid.start_move()
                return

        if isinstance(event, WidgetReleaseEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.end_script()
                model = self.__label_model_map[event.widget]
                widget = self.__model_widget_map[model]
                self.__handle_widget_release(widget, event.mouse_event)
                return

        if isinstance(event, WidgetMoveEvent):
            label_model = self.__label_model_map[event.widget]
            grid_move = self.__grid.relative_move(event.dx,
                                                  event.dy,
                                                  event.widget)
            model_move = self.__to_model_delta(grid_move.x(),
                                               grid_move.y())
            self.__controller.move_label_relative(label_model,
                                                  model_move.x(),
                                                  model_move.y())
            widget = self.__model_widget_map[label_model]
            if event.widget not in self.__selection:
                self.__clear_selection()
                self.__add_selection(widget)

    def __on_node_click(self, event):
        if isinstance(event, WidgetPressEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.start_script()
                self.__grid.start_move()
                return

        if isinstance(event, WidgetReleaseEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.end_script()

                # Do not modify selection after move
                if not event.press_pos == event.mouse_event.globalPosition().toPoint():
                    return

                if event.mouse_event.modifiers() == Qt.ControlModifier:
                    if len(self.__selection) == 1 and \
                            isinstance(self.__selection[0], NodeWidget):
                        start = self.__widget_model_map[self.__selection[0]]
                        end = self.__widget_model_map[event.widget]
                        if start == end:
                            self.__controller.create_self_loop(start)
                        else:
                            self.__controller.create_branch_auto_pos(
                                start, end)

                        self.__clear_selection()
                        self.__add_selection(event.widget)
                        return

                return self.__handle_widget_release(event.widget,
                                                    event.mouse_event)

        if isinstance(event, WidgetMoveEvent):
            if event.widget not in self.__selection:
                self.__clear_selection()
                self.__add_selection(event.widget)

            grid_move = self.__grid.relative_move(
                event.dx,
                event.dy,
                event.widget)
            model_move = self.__to_model_delta(grid_move.x(),
                                               grid_move.y())

            for widget in self.__selection:
                if isinstance(widget, NodeWidget):
                    node = self.__widget_model_map[widget]
                    if model_move.x() != 0 or model_move.y() != 0:
                        self.__controller.move_node(node,
                                                    model_move.x(),
                                                    model_move.y())

    def __on_branch_click(self, event: WidgetPressEvent):
        if isinstance(event, WidgetPressEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__handle_widget_release(event.widget, event.mouse_event)
                if len(self.__selection) == 1 \
                   and event.widget in self.__selection:
                    self.__handles = event.widget.get_handles()
                    for handle in self.__handles:
                        handle.observe(
                            self.__on_spline_handle_click)
                        handle.show()

    def __handle_widget_release(self,
                                widget: GraphItem,
                                mouse_event: QMouseEvent):
        if not mouse_event.modifiers() == Qt.ShiftModifier:
            self.__clear_selection()

        # Clear visible handles
        self.__clear_handles()

        if widget in self.__selection:
            self.__remove_selection(widget)
        else:
            self.__add_selection(widget)

    def __on_spline_handle_click(self, event: WidgetClickEvent):
        if isinstance(event, SplineHandleWidgetPressEvent) \
           and event.mouse_event.button() == Qt.LeftButton:
            self.__command_handler.start_script()
            self.__grid.start_move()

        if isinstance(event, SplineHandleWidgetReleaseEvent) \
           and event.mouse_event.button() == Qt.LeftButton:
            self.__command_handler.end_script()

        if isinstance(event, SplineHandleWidgetMoveEvent):
            widget = event.widget
            dx1, dy1, dx2, dy2 = 0, 0, 0, 0
            grid_move = self.__grid.relative_move(event.dx,
                                                  event.dy,
                                                  event.widget)
            model_move = self.__to_model_delta(grid_move.x(),
                                               grid_move.y())
            if isinstance(widget, Spline1HandleWidget):
                dx1, dy1 = model_move.x(), model_move.y()
            elif isinstance(widget, Spline2HandleWidget):
                dx2, dy2 = model_move.x(), model_move.y()
            self.__controller.transform_branch(
                widget.get_branch(), -dx1, -dy1, -dx2, -dy2)

    def get_selection(self):
        return self.__selection.copy()

    def select_all(self):
        self.__clear_selection()
        for widget in self.__model_widget_map.values():
            self.__add_selection(widget)

    def __clear_handles(self):
        # Remove all handles for next selection
        for handle in self.__handles:
            handle.deleteLater()
        self.__handles.clear()

    def __clear_selection(self):
        self.__clear_handles()

        for widget in self.__selection:
            widget.unselect()

        for label in self.__model_label_map.values():
            label.unselect()

        self.__selection.clear()
        self.update()
        self.__selection_changed()

    def __add_selection(self, widget):
        if (widget not in self.__selection):
            self.__selection.append(widget)
            widget.select(len(self.__selection))

            # Select label
            model = self.__widget_model_map[widget]
            label = self.__model_label_map[model]
            label.select(len(self.__selection))

            self.update()
            self.__selection_changed()

    def __remove_selection(self, widget):
        if widget in self.__selection:
            remove_selection_number = widget.get_selection_number()
            self.__selection.remove(widget)
            widget.unselect()

            # Deselect label
            model = self.__widget_model_map[widget]
            label = self.__model_label_map[model]
            label.unselect()

            # Adjust selection index for other widgets
            for sel in self.__selection:
                if sel.get_selection_number() > remove_selection_number:
                    sel.select(sel.get_selection_number() - 1)

            self.update()
            self.__selection_changed()

    def __handle_model_change(self, event):
        if isinstance(event, PositionedNodeAddedEvent):
            logger.debug("PositionedNodeAddedEvent received")
            self.__add_node(event.node)
            return
        if isinstance(event, PositionedNodeRemovedEvent):
            logger.debug("PositionedNodeRemovedEvent received")
            widget = self.__model_widget_map[event.node]
            widget.deleteLater()
            self.__clear_selection()

            self.__model_widget_map.pop(event.node)
            self.__widget_model_map.pop(widget)

            self.__remove_label_relative(event.node)
            return
        if isinstance(event, CurvedBranchAddedEvent):
            logger.debug("CurvedBranchAddedEvent received")
            self.__add_branch(event.branch)
            return
        if isinstance(event, CurvedBranchRemovedEvent):
            logger.debug("CurvedBranchRemovedEvent received")
            widget = self.__model_widget_map[event.branch]
            self.__clear_selection()
            widget.deleteLater()

            self.__model_widget_map.pop(event.branch)
            self.__widget_model_map.pop(widget)

            self.__remove_label_relative(event.branch)
            return
        if isinstance(event, PositionedNodeMovedEvent):
            view_event = PositionedNodeMovedEvent(
                event.node,
                int(round(event.dx * self.__zoom_factor)),
                int(round(event.dy * self.__zoom_factor)))
            # Propagate event to nodes, branches
            for widget in self.__model_widget_map.values():
                if isinstance(widget, NodeWidget):
                    widget.node_moved_event(view_event)
                elif isinstance(widget, BranchWidget):
                    widget.node_moved_event(view_event)

            # Propagate event to active handles
            for handle in self.__handles:
                handle.node_moved_event(view_event)

            # Propagate event to labels
            for label in self.__model_label_map.values():
                label.node_moved_event(view_event)
            return
        if isinstance(event, CurvedBranchTransformedEvent):
            # Propagate event to handles
            for handle in self.__handles:
                handle.branch_transformed_event(event)

            # Propagate event to branches
            for widget in self.__model_widget_map.values():
                if isinstance(widget, BranchWidget):
                    widget.branch_transformed_event(event)

            # Propagate event to labels
            for label in self.__model_label_map.values():
                label.branch_transformed_event(event)
            return
        if isinstance(event, LabelChangedTextEvent):
            logger.debug("LabelChangedTextEvent received")
            label = self.__model_label_map[event.labeled_obj]
            label.setText(event.new_text)
            label.adjustSize()

            # Propagate event to label
            label.label_changed_text_event(event)
            return
        if isinstance(event, LabelMovedEvent):
            label = self.__model_label_map[event.labeled_obj]
            label.label_moved_event(event)
        if isinstance(event, GraphChangedEvent):
            logger.debug("GraphChangedEvent received")
            self.__clear_selection()
            for widget in self.__widget_model_map:
                widget.deleteLater()
            for label in self.__label_model_map:
                label.deleteLater()

            self.__model_widget_map.clear()
            self.__widget_model_map.clear()
            self.__label_model_map.clear()
            self.__model_label_map.clear()
            for node in event.nodes:
                self.__add_node(node)
            for branch in event.branches:
                self.__add_branch(branch)

            grid_offset_ = self.__model.get_grid_position()
            self.__grid_offset = QPoint(grid_offset_[0], grid_offset_[1])
            self.__apply_zoom()
            return
        if isinstance(event, GraphMovedEvent):
            view_event = self.__scaled_graph_event(event)
            for widget in self.__model_widget_map.values():
                widget.graph_moved_event(view_event)

            for widget in self.__model_label_map.values():
                widget.graph_moved_event(view_event)

            for widget in self.__handles:
                widget.graph_moved_event(view_event)

    def __add_node(self, node):
        widget = NodeWidget(node, parent=self)
        widget.set_zoom_transform(self.__zoom_factor)
        # Set initial position centered to given point
        center = self.__to_view_point(QPointF(node.x, node.y))
        widget.move(QPoint(int(round(center.x() - widget.width() / 2)),
                           int(round(center.y() - widget.height() / 2))))
        widget.observe(self.__on_node_click)
        self.__model_widget_map[node] = widget
        self.__widget_model_map[widget] = node
        widget.show()
        self.__initalize_label(node) ###
        self.__clear_selection()
        self.__add_selection(widget)

    def __add_branch(self, branch):
        widget = BranchWidget(branch,
                              QPoint(int(branch.spline1_x),
                                     int(branch.spline1_y)),
                              QPoint(int(branch.spline2_x),
                                     int(branch.spline2_y)),
                              parent=self)
        widget.set_zoom_transform(self.__zoom_factor, self.__zoom_origin)

        self.__model_widget_map[branch] = widget
        self.__widget_model_map[widget] = branch
        widget.show()

        # Lower branch to ensure it is behind its nodes
        widget.lower()

        # Lower grid widget to keep it behind the branches
        self.__grid_widget.lower()

        # Register click listener for widget
        widget.observe(self.__on_branch_click)

        # Paint widget explicit
        # because the label positioning needs an existing
        # Bézier curve
        widget.repaint()
        self.__initalize_label(branch)
        self.__clear_selection()
        self.__add_selection(widget)

    def __initalize_label(self, labeled_object: LabeledObject):
        widget = self.__model_widget_map[labeled_object]
        label = LabelWidget(labeled_object.label_text,
                            labeled_object,
                            widget,
                            parent=self)

        self.__model_label_map[labeled_object] = label
        self.__label_model_map[label] = labeled_object

        label.observe(self.__on_label_click)
        label.set_zoom_transform(self.__zoom_factor)
        label.show()

    def __remove_label_relative(self, labeled_object: LabeledObject):
        label = self.__model_label_map[labeled_object]
        label.deleteLater()
        self.__model_label_map.pop(labeled_object)
        self.__label_model_map.pop(label)

    def resizeEvent(self, event: QResizeEvent):
        # Resize grid
        self.__grid_widget.resize(self.size())
        self.__apply_zoom()
        super().resizeEvent(event)

    def copy_to_clipboard(self):
        selection = [self.__widget_model_map[w] for w in self.__selection]

        selected_nodes = []
        selected_branches = []

        # Collect nodes
        for m in selection:
            if isinstance(m, PositionedNode):
                selected_nodes.append(m)

        selected_node_ids = {n.id.hex for n in selected_nodes}

        # Collect branches whose endpoints are fully selected
        for m in selection:
            if isinstance(m, CurvedBranch):
                if m.start.id.hex in selected_node_ids and \
                m.end.id.hex in selected_node_ids:
                    selected_branches.append(m)

        data = {
            "nodes": [n.to_dict() for n in selected_nodes],
            "branches": [b.to_dict() for b in selected_branches]
        }

        QApplication.clipboard().setText(json.dumps(data))


    def cut_to_clipboard(self):
        self.copy_to_clipboard()
        models = [self.__widget_model_map[w] for w in self.__selection]
        self.__controller.remove_nodes_and_branches(models)

    def paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if not text.strip():
            return  # clipboard empty

        # Parse JSON
        try:
            data = json.loads(text)
        except Exception:
            return  # invalid JSON

        nodes_data = data.get("nodes", [])
        branches_data = data.get("branches", [])

        if not nodes_data:
            return  # no nodes, nothing to paste


        # Check mouse inside GraphField
        global_pos = QtGui.QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local_pos):
            QMessageBox.warning(self, "Paste error",
                                        "Mouse pointer is outside the graph area.")
            return

        mouse_x, mouse_y = local_pos.x(), local_pos.y()

        # Snap to grid
        grid_x = int(self.__grid_size*round((mouse_x-2) / self.__grid_size))
        grid_y = int(self.__grid_size*round((mouse_y-2) / self.__grid_size))
        model_grid = self.__to_model_point(QPointF(grid_x, grid_y))
        model_grid_x = int(round(model_grid.x()))
        model_grid_y = int(round(model_grid.y()))

        # Compute bounding box of copied nodes
        min_x = min(n["x"] for n in nodes_data)
        min_y = min(n["y"] for n in nodes_data)

        # Offset so min_x/min_y lands at nearest grid cell
        dx = model_grid_x - min_x
        dy = model_grid_y - min_y

        id_map = {}
        new_branches = []

        self.__command_handler.start_script()
        try:
            # Paste nodes
            for nd in nodes_data:
                new_x = nd["x"] + dx
                new_y = nd["y"] + dy

                new_node = self.__controller.create_node(new_x, new_y)

                # Restore node name if present
                name = nd.get("name")
                if name:
                    self.__controller.set_node_name(new_node, name)

                id_map[nd["id"]] = new_node

            # Paste branches
            for bd in branches_data:
                sid = bd["start"]
                eid = bd["end"]

                if sid not in id_map or eid not in id_map:
                    continue  # skip branches if nodes not pasted

                start_node = id_map[sid]
                end_node = id_map[eid]

                s1x = bd.get("spline1_x", 0) + dx
                s1y = bd.get("spline1_y", 0) + dy
                s2x = bd.get("spline2_x", 0) + dx
                s2y = bd.get("spline2_y", 0) + dy
                label_dx = bd.get("label_dx", 0)
                label_dy = bd.get("label_dy", 0)
                weight = bd.get("weight", "")

                branch = self.__controller.create_branch(
                    start_node, end_node,
                    s1x, s1y, s2x, s2y,
                    label_dx, label_dy,
                    weight
                )
                new_branches.append(branch)

        finally:
            self.__command_handler.end_script()

        # Select pasted items
        self.__clear_selection()
        for node in id_map.values():
            widget = self.__model_widget_map.get(node)
            if widget:
                self.__add_selection(widget)
        for branch in new_branches:
            widget = self.__model_widget_map.get(branch)
            if widget:
                self.__add_selection(widget)