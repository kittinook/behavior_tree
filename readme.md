# Enhanced Behavior Tree Framework

An advanced, flexible, and performant Behavior Tree implementation in Python, built upon the concepts of py_trees with additional features for better usability, flexibility, and scalability.

## Features

- 🌟 **Rich Node Types**
  - Composite nodes (Sequence, Selector, Parallel)
  - Decorator nodes for behavior modification
  - Easy-to-extend node system through plugins

- 🔄 **Advanced Execution**
  - Asynchronous and parallel execution support
  - Configurable tick rates
  - Smart scheduling based on node dependencies

- 📊 **Data Management**
  - Sophisticated blackboard system with namespaces
  - Thread-safe data access
  - Flexible data type support

- 🛠 **Configuration & Integration**
  - YAML/JSON-based tree definition
  - Runtime tree modification
  - Easy integration with ROS, gRPC, or REST APIs

- 🔍 **Debugging & Visualization**
  - Real-time tree visualization
  - Comprehensive logging system
  - Record & replay functionality

## Installation

```bash
pip install enhanced-behavior-tree
```

## Quick Start

1. Define your behavior tree in YAML:

```yaml
name: "robot_behavior"
type: "SEQUENCE"
children:
  - name: "check_battery"
    type: "CONDITION"
    properties:
      threshold: 20.0
  
  - name: "navigate_to_goal"
    type: "ACTION"
    properties:
      goal_position: [1.0, 2.0]
```

2. Use it in your code:

```python
from enhanced_behavior_tree import BehaviorTreeManager
import asyncio

# Initialize the tree manager
manager = BehaviorTreeManager(tick_rate=60)

# Load tree from YAML
manager.load_from_yaml("robot_tree.yaml")

# Run the tree
asyncio.run(manager.run())
```

## Documentation

For detailed documentation, visit:
- [Architecture Overview](docs/architecture.md)
- [API Reference](docs/api_reference.md)
- [Examples](docs/examples.md)

## Example Use Cases

### Robot Control
```python
from enhanced_behavior_tree import BehaviorTreeManager, ActionNode
from enhanced_behavior_tree.nodes import SequenceNode

class MoveToGoalNode(ActionNode):
    async def tick(self):
        goal = self.properties.get("goal")
        # Implementation for robot movement
        return NodeStatus.SUCCESS

# Create and configure your tree
tree = BehaviorTreeManager()
sequence = SequenceNode("robot_sequence")
move_node = MoveToGoalNode("move_to_goal", {"goal": [1.0, 2.0]})
sequence.add_child(move_node)
```

## Contributing

Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md) before submitting a Pull Request.

### Development Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/enhanced-behavior-tree.git
cd enhanced-behavior-tree
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install development dependencies:
```bash
pip install -e ".[dev]"
```

4. Run tests:
```bash
pytest tests/
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by [py_trees](https://github.com/splintered-reality/py_trees)
- Built with modern Python async/await features
- Designed for scalability and performance

## Support

- 📫 For bug reports and feature requests, please use the [GitHub Issues](https://github.com/yourusername/enhanced-behavior-tree/issues)
- 💬 For questions and discussions, join our [Discord Community](https://discord.gg/yourdiscord)
