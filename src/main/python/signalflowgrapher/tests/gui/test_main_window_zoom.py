import os
from unittest import TestCase
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QMainWindow

from signalflowgrapher.gui.label_widget import LabelWidget
from signalflowgrapher.gui.node_widget import NodeWidget
from signalflowgrapher.gui.branch_widget import (
    BranchWidget, Spline1HandleWidget)
from signalflowgrapher.gui.ui.ui_main_window import Ui_MainWindow


class TestMainWindowZoomActions(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_zoom_actions_are_present(self):
        window = QMainWindow()
        ui = Ui_MainWindow()
        ui.setupUi(window)

        self.assertEqual(ui.action_zoom_in.text(), "Zoom In")
        self.assertEqual(ui.action_zoom_out.text(), "Zoom Out")
        self.assertEqual(ui.action_reset_zoom.text(), "Reset Zoom")
        self.assertEqual(ui.action_zoom_in.shortcut().toString(), "Ctrl++")
        self.assertEqual(ui.action_zoom_out.shortcut().toString(), "Ctrl+-")
        self.assertEqual(ui.action_reset_zoom.shortcut().toString(), "Ctrl+0")

        view_actions = ui.menu_view.actions()
        self.assertIn(ui.action_center_graph, view_actions)
        self.assertIn(ui.action_zoom_in, view_actions)
        self.assertIn(ui.action_zoom_out, view_actions)
        self.assertIn(ui.action_reset_zoom, view_actions)

    def test_node_and_label_scale_with_zoom(self):
        node_owner = MagicMock()
        node_widget = NodeWidget(node_owner)
        base_size = node_widget.size()

        node_widget.set_zoom_transform(2.0)
        larger_size = node_widget.size()
        self.assertGreater(larger_size.width(), base_size.width())
        self.assertGreater(larger_size.height(), base_size.height())

        node_widget.set_zoom_transform(0.5)
        smaller_size = node_widget.size()
        self.assertLess(smaller_size.width(), larger_size.width())
        self.assertLess(smaller_size.height(), larger_size.height())

        owner = MagicMock()
        owner.label_dx = 24
        owner.label_dy = 12
        owner_widget = MagicMock()
        owner_widget.get_center.return_value = QPointF(100, 100)

        label = LabelWidget("Test", owner, owner_widget)
        base_font_size = label.font().pointSizeF()
        base_pos = label.pos()

        label.set_zoom_transform(2.0)
        zoomed_font_size = label.font().pointSizeF()
        zoomed_pos = label.pos()

        self.assertGreater(zoomed_font_size, base_font_size)
        self.assertGreater(zoomed_pos.x(), base_pos.x())
        self.assertGreater(zoomed_pos.y(), base_pos.y())

    def test_branch_and_handle_scale_with_zoom(self):
        start = MagicMock()
        start.x = 50
        start.y = 50
        end = MagicMock()
        end.x = 180
        end.y = 120
        branch = MagicMock()
        branch.start = start
        branch.end = end
        branch.spline1_x = 90
        branch.spline1_y = 20
        branch.spline2_x = 140
        branch.spline2_y = 150

        branch_widget = BranchWidget(branch,
                                     QPointF(branch.spline1_x,
                                              branch.spline1_y),
                                     QPointF(branch.spline2_x,
                                              branch.spline2_y))
        base_branch_size = branch_widget.size()
        branch_widget.set_zoom_transform(1.8, QPointF(0, 0))
        zoomed_branch_size = branch_widget.size()
        self.assertGreaterEqual(zoomed_branch_size.width(),
                                base_branch_size.width())
        self.assertGreaterEqual(zoomed_branch_size.height(),
                                base_branch_size.height())

        node = MagicMock()
        node.x = 50
        node.y = 50
        handle = Spline1HandleWidget(branch=branch,
                                     node=node,
                                     origin=QPointF(50, 50),
                                     spline=QPointF(90, 20))
        base_handle_size = handle.size()
        handle.set_zoom_transform(1.8, QPointF(0, 0))
        zoomed_handle_size = handle.size()
        self.assertGreaterEqual(zoomed_handle_size.width(),
                                base_handle_size.width())
        self.assertGreaterEqual(zoomed_handle_size.height(),
                                base_handle_size.height())

    def test_zoom_to_fit_fits_and_centers(self):
        from signalflowgrapher.model.model import Model, ObservableGraph, PositionedNode, CurvedBranch
        from signalflowgrapher.gui.graph_field import GraphField

        # Prepare model and graph
        model = Model()
        graph = ObservableGraph()
        model.graph = graph

        # Create application-level objects
        controller = MagicMock()
        command_handler = MagicMock()

        # Create graph field and set a viewport size
        gf = GraphField(controller, model, command_handler)
        gf.resize(800, 600)

        # Add two nodes far apart and a curved branch
        n1 = PositionedNode(graph, 50, 50, 0, 0)
        n2 = PositionedNode(graph, 600, 400, 0, 0)

        b = CurvedBranch(n1, n2, 120, 20, 480, 320, 0, 0)

        # Ensure widgets are created
        widgets = list(gf._GraphField__model_widget_map.values())
        self.assertTrue(len(widgets) >= 3)

        margin = 20
        # Call zoom_to_fit
        gf.zoom_to_fit(margin_px=margin)

        # Compute bounding box of widgets in view coords
        min_x = min(w.x() for w in widgets)
        max_x = max(w.x() + w.width() for w in widgets)
        min_y = min(w.y() for w in widgets)
        max_y = max(w.y() + w.height() for w in widgets)

        # Assert bounding box fits inside viewport with margin (allow 1px tolerance)
        tol = 1
        self.assertGreaterEqual(min_x, margin - tol)
        self.assertLessEqual(max_x, gf.width() - margin + tol)
        self.assertGreaterEqual(min_y, margin - tol)
        self.assertLessEqual(max_y, gf.height() - margin + tol)
