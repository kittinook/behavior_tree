import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsItem,
    QDockWidget, QListWidget, QLineEdit, QFormLayout, QWidget, QPushButton, QGraphicsEllipseItem, QGraphicsLineItem
)
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush

class NodeItem(QGraphicsEllipseItem):
    def __init__(self, name, node_type, x=0, y=0):
        super().__init__(-50, -25, 100, 50)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPen(QPen(Qt.GlobalColor.black))
        self.setBrush(QBrush(Qt.GlobalColor.lightGray))
        self.name = name
        self.node_type = node_type
        self.setToolTip(f"{node_type} Node: {name}")
        self.setPos(x, y)

    def __repr__(self):
        return f"NodeItem(name={self.name}, type={self.node_type})"

class ConnectionItem(QGraphicsLineItem):
    def __init__(self, source_node, target_node):
        super().__init__()
        self.source_node = source_node
        self.target_node = target_node
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        self.update_position()

    def update_position(self):
        source_center = self.source_node.sceneBoundingRect().center()
        target_center = self.target_node.sceneBoundingRect().center()
        self.setLine(source_center.x(), source_center.y(), target_center.x(), target_center.y())

class BehaviorTreeEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Behavior Tree Editor")
        self.setGeometry(100, 100, 1200, 800)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.setCentralWidget(self.view)

        self.scene.setSceneRect(0, 0, 2000, 2000)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._create_node_palette()
        self._create_properties_panel()
        self._setup_undo_redo()

        self.selected_node = None
        self.temp_connection = None

    def _create_node_palette(self):
        dock = QDockWidget("Node Palette", self)
        self.node_list = QListWidget()

        self.node_list.addItem("Sequence Node")
        self.node_list.addItem("Selector Node")
        self.node_list.addItem("Action Node")
        self.node_list.addItem("Condition Node")

        self.node_list.itemDoubleClicked.connect(self._add_node_from_palette)
        dock.setWidget(self.node_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _create_properties_panel(self):
        dock = QDockWidget("Properties", self)
        self.properties_widget = QWidget()
        self.properties_layout = QFormLayout()

        self.name_field = QLineEdit()
        self.type_field = QLineEdit()
        self.type_field.setReadOnly(True)

        self.properties_layout.addRow("Name:", self.name_field)
        self.properties_layout.addRow("Type:", self.type_field)

        self.properties_widget.setLayout(self.properties_layout)
        dock.setWidget(self.properties_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _setup_undo_redo(self):
        self.undo_stack = []
        self.redo_stack = []

    def _add_node_from_palette(self, item):
        node_type = item.text()
        node_name = f"{node_type}_{len(self.scene.items())}"
        node = NodeItem(node_name, node_type, x=100, y=100)
        self.scene.addItem(node)
        node.setSelected(True)
        self._update_properties(node)
        self._add_to_undo_stack(lambda: self.scene.removeItem(node))

    def _update_properties(self, node):
        if isinstance(node, NodeItem):
            self.name_field.setText(node.name)
            self.type_field.setText(node.node_type)

    def _add_to_undo_stack(self, undo_action):
        self.undo_stack.append(undo_action)
        self.redo_stack.clear()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.scene.itemAt(self.view.mapToScene(event.pos()), self.view.transform())
            if isinstance(item, NodeItem):
                if self.temp_connection:
                    self.scene.removeItem(self.temp_connection)
                    self.temp_connection = None

                if self.selected_node and self.selected_node != item:
                    connection = ConnectionItem(self.selected_node, item)
                    self.scene.addItem(connection)
                    self._add_to_undo_stack(lambda: self.scene.removeItem(connection))
                    self.selected_node = None
                else:
                    self.selected_node = item
            else:
                self.selected_node = None
        elif event.button() == Qt.MouseButton.RightButton:
            if self.selected_node:
                pos = self.view.mapToScene(event.pos())
                self.temp_connection = QGraphicsLineItem(
                    self.selected_node.sceneBoundingRect().center().x(),
                    self.selected_node.sceneBoundingRect().center().y(),
                    pos.x(), pos.y()
                )
                self.temp_connection.setPen(QPen(Qt.GlobalColor.gray, 2, Qt.PenStyle.DashLine))
                self.scene.addItem(self.temp_connection)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.temp_connection:
            pos = self.view.mapToScene(event.pos())
            source_center = self.selected_node.sceneBoundingRect().center()
            self.temp_connection.setLine(
                source_center.x(), source_center.y(), pos.x(), pos.y()
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.temp_connection:
            self.scene.removeItem(self.temp_connection)
            self.temp_connection = None
        super().mouseReleaseEvent(event)

    def undo(self):
        if self.undo_stack:
            action = self.undo_stack.pop()
            self.redo_stack.append(action)
            action()

    def redo(self):
        if self.redo_stack:
            action = self.redo_stack.pop()
            self.undo_stack.append(action)
            action()

    def tick(self):
        for item in self.scene.selectedItems():
            if isinstance(item, NodeItem):
                print(f"Ticking Node: {item}")

    def run_simulation(self):
        print("Running simulation...")
        for item in self.scene.items():
            if isinstance(item, NodeItem):
                print(f"Simulating Node: {item}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BehaviorTreeEditor()
    window.show()
    sys.exit(app.exec())