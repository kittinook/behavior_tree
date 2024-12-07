import sys
from pathlib import Path
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit,
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QMessageBox,
    QMenu, QInputDialog
)
from PyQt6.QtCore import Qt, QMimeData, QPoint
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QAction

sys.path.append(str(Path(__file__).parent.parent))

from behavior_tree import (
    NodeStatus,
    SequenceNode,
    SelectorNode,
    ParallelNode,
    ActionNode,
    ConditionNode,
    RetryNode,
    TimeoutNode
)

class NodeTypeDialog(QDialog):
    """Dialog for selecting node type and properties"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Node")
        self.setModal(True)

        # Node types
        self.node_types = {
            "Composite Nodes": [
                "SequenceNode",
                "SelectorNode",
                "ParallelNode"
            ],
            "Decorator Nodes": [
                "RetryNode",
                "TimeoutNode"
            ],
            "Leaf Nodes": [
                "ActionNode",
                "ConditionNode"
            ]
        }

        layout = QVBoxLayout()

        # Node type selection
        form_layout = QFormLayout()
        self.type_combo = QComboBox()
        for category in self.node_types.values():
            self.type_combo.addItems(category)
        form_layout.addRow("Node Type:", self.type_combo)

        # Node name
        self.name_edit = QLineEdit()
        form_layout.addRow("Node Name:", self.name_edit)

        # Properties section
        self.properties_layout = QFormLayout()
        self.type_combo.currentTextChanged.connect(self.update_properties)
        
        layout.addLayout(form_layout)
        layout.addWidget(QLabel("Properties:"))
        layout.addLayout(self.properties_layout)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self.update_properties(self.type_combo.currentText())

    def update_properties(self, node_type: str):
        """Update property fields based on node type"""
        # Clear existing properties
        while self.properties_layout.count():
            item = self.properties_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add properties based on node type
        if node_type == "ParallelNode":
            policy_combo = QComboBox()
            policy_combo.addItems(["REQUIRE_ALL", "REQUIRE_ONE"])
            self.properties_layout.addRow("Policy:", policy_combo)

        elif node_type == "RetryNode":
            attempts = QLineEdit("3")
            attempts.setPlaceholderText("Number of attempts")
            self.properties_layout.addRow("Max Attempts:", attempts)

        elif node_type == "TimeoutNode":
            timeout = QLineEdit("1.0")
            timeout.setPlaceholderText("Timeout in seconds")
            self.properties_layout.addRow("Timeout:", timeout)

        elif node_type in ["ActionNode", "ConditionNode"]:
            func_name = QLineEdit()
            func_name.setPlaceholderText("Function name")
            self.properties_layout.addRow("Function:", func_name)

    def get_node_data(self) -> dict:
        """Get node configuration data"""
        data = {
            "type": self.type_combo.currentText(),
            "name": self.name_edit.text(),
            "properties": {}
        }

        # Collect properties
        for i in range(self.properties_layout.rowCount()):
            label = self.properties_layout.itemAt(i*2).widget()
            field = self.properties_layout.itemAt(i*2+1).widget()
            if isinstance(field, QLineEdit):
                data["properties"][label.text().rstrip(":")] = field.text()
            elif isinstance(field, QComboBox):
                data["properties"][label.text().rstrip(":")] = field.currentText()

        return data

class TreeEditorWidget(QTreeWidget):
    """Custom TreeWidget for behavior tree editing"""
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)

        # Setup headers
        self.setHeaderLabels(["Node", "Type", "Properties"])
        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 150)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        if event.source() == self:
            event.accept()
            target = self.itemAt(event.pos())
            if not target:
                return

            items = self.selectedItems()
            if not items:
                return

            item = items[0]
            if item == target:
                return

            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                index = self.indexOfTopLevelItem(item)
                self.takeTopLevelItem(index)

            new_parent = target
            new_parent.addChild(item)
            new_parent.setExpanded(True)
        else:
            event.ignore()

class BehaviorTreeEditor(QMainWindow):
    """Main window for behavior tree editor"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Behavior Tree Editor")
        self.setGeometry(100, 100, 800, 600)

        # Create central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Create toolbar
        toolbar = QHBoxLayout()
        
        # Add node button
        add_btn = QPushButton("Add Node")
        add_btn.clicked.connect(self.add_node)
        toolbar.addWidget(add_btn)

        # Delete node button
        del_btn = QPushButton("Delete Node")
        del_btn.clicked.connect(self.delete_node)
        toolbar.addWidget(del_btn)

        # Save/Load buttons
        save_btn = QPushButton("Save Tree")
        save_btn.clicked.connect(self.save_tree)
        toolbar.addWidget(save_btn)

        load_btn = QPushButton("Load Tree")
        load_btn.clicked.connect(self.load_tree)
        toolbar.addWidget(load_btn)

        layout.addLayout(toolbar)

        # Create tree widget
        self.tree = TreeEditorWidget()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.tree)

    def add_node(self, parent_item=None):
        """Add new node to tree"""
        dialog = NodeTypeDialog(self)
        if dialog.exec():
            data = dialog.get_node_data()
            item = QTreeWidgetItem([
                data["name"],
                data["type"],
                str(data["properties"])
            ])
            
            # Store node data
            item.setData(0, Qt.ItemDataRole.UserRole, data)

            if parent_item:
                parent_item.addChild(item)
            else:
                self.tree.addTopLevelItem(item)

    def delete_node(self):
        """Delete selected node"""
        item = self.tree.currentItem()
        if item:
            if item.parent():
                item.parent().removeChild(item)
            else:
                self.tree.takeTopLevelItem(
                    self.tree.indexOfTopLevelItem(item)
                )

    def save_tree(self):
        """Save tree to JSON file"""
        data = self._serialize_tree()
        try:
            with open("behavior_tree.json", "w") as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(
                self,
                "Success",
                "Tree saved successfully!"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save tree: {e}"
            )

    def load_tree(self):
        """Load tree from JSON file"""
        try:
            with open("behavior_tree.json", "r") as f:
                data = json.load(f)
            self.tree.clear()
            self._deserialize_tree(data)
            QMessageBox.information(
                self,
                "Success",
                "Tree loaded successfully!"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load tree: {e}"
            )

    def show_context_menu(self, position: QPoint):
        """Show context menu for node operations"""
        item = self.tree.itemAt(position)
        if not item:
            return

        menu = QMenu()
        add_child = menu.addAction("Add Child Node")
        edit_node = menu.addAction("Edit Node")
        delete_node = menu.addAction("Delete Node")

        action = menu.exec(self.tree.viewport().mapToGlobal(position))
        
        if action == add_child:
            self.add_node(item)
        elif action == edit_node:
            self._edit_node(item)
        elif action == delete_node:
            self.delete_node()

    def _edit_node(self, item: QTreeWidgetItem):
        """Edit existing node"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        dialog = NodeTypeDialog(self)
        
        # Set current values
        dialog.type_combo.setCurrentText(data["type"])
        dialog.name_edit.setText(data["name"])
        dialog.update_properties(data["type"])

        # Set property values
        for i in range(dialog.properties_layout.rowCount()):
            label = dialog.properties_layout.itemAt(i*2).widget()
            field = dialog.properties_layout.itemAt(i*2+1).widget()
            prop_name = label.text().rstrip(":")
            if prop_name in data["properties"]:
                if isinstance(field, QLineEdit):
                    field.setText(str(data["properties"][prop_name]))
                elif isinstance(field, QComboBox):
                    field.setCurrentText(data["properties"][prop_name])

        if dialog.exec():
            new_data = dialog.get_node_data()
            item.setText(0, new_data["name"])
            item.setText(1, new_data["type"])
            item.setText(2, str(new_data["properties"]))
            item.setData(0, Qt.ItemDataRole.UserRole, new_data)

    def _serialize_tree(self) -> dict:
        """Convert tree to dictionary"""
        def serialize_item(item: QTreeWidgetItem) -> dict:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            node_data = {
                "type": data["type"],
                "name": data["name"],
                "properties": data["properties"],
                "children": []
            }
            
            for i in range(item.childCount()):
                node_data["children"].append(
                    serialize_item(item.child(i))
                )
            return node_data

        root_data = {"children": []}
        for i in range(self.tree.topLevelItemCount()):
            root_data["children"].append(
                serialize_item(self.tree.topLevelItem(i))
            )
        return root_data

    def _deserialize_tree(self, data: dict):
        """Load tree from dictionary"""
        def create_item(node_data: dict) -> QTreeWidgetItem:
            item = QTreeWidgetItem([
                node_data["name"],
                node_data["type"],
                str(node_data["properties"])
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, node_data)
            
            for child_data in node_data["children"]:
                item.addChild(create_item(child_data))
            return item

        for node_data in data["children"]:
            self.tree.addTopLevelItem(create_item(node_data))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    editor = BehaviorTreeEditor()
    editor.show()
    sys.exit(app.exec())