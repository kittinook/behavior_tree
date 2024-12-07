# Enhanced Behavior Tree Framework

Enhanced Behavior Tree Framework เป็น library Python สำหรับสร้างและจัดการ Behavior Trees ที่มีความยืดหยุ่นสูง รองรับการทำงานแบบ asynchronous และมีเครื่องมือสำหรับ debugging และ visualization

## ✨ คุณสมบัติหลัก

### 🌳 โครงสร้างพื้นฐาน
- รองรับ node พื้นฐานครบถ้วน (Sequence, Selector, Parallel, Action, Condition)
- Composite nodes หลากหลายรูปแบบพร้อม memory policies
- Decorator nodes สำหรับปรับแต่งพฤติกรรม
- ระบบ Blackboard สำหรับแชร์ข้อมูลระหว่าง nodes

### 🔄 ระบบการทำงาน
- รองรับ async/await
- Parallel execution
- การจัดการ lifecycle ของ nodes
- ระบบ event handling

### 📊 การติดตามและ Debug
- Real-time visualization
- ระบบ logging ที่ละเอียด
- การเก็บสถิติการทำงาน
- Record และ replay การทำงาน

### ⚙️ การกำหนดค่า
- รองรับ YAML, JSON, และ Python configuration
- ระบบตรวจสอบ configuration
- การรวมและ override configuration

## 🚀 การติดตั้ง

```bash
pip install behavior-tree
```

## 📖 การใช้งานพื้นฐาน

### การสร้าง Behavior Tree อย่างง่าย

```python
import asyncio
from enhanced_behavior_tree import (
    BehaviorTreeManager,
    SequenceNode,
    ActionNode,
    ConditionNode
)

# สร้าง action nodes
async def check_battery():
    # จำลองการตรวจสอบแบตเตอรี่
    return True

async def move_to_target():
    # จำลองการเคลื่อนที่
    await asyncio.sleep(1)
    return True

# สร้าง tree
async def main():
    # สร้าง manager
    manager = BehaviorTreeManager()
    
    # สร้าง nodes
    sequence = SequenceNode("main_sequence")
    battery_check = ConditionNode(
        "check_battery",
        condition_func=check_battery
    )
    move = ActionNode(
        "move_to_target",
        action_func=move_to_target
    )
    
    # สร้างโครงสร้าง tree
    sequence.add_child(battery_check)
    sequence.add_child(move)
    
    # ตั้งค่า root node
    manager.root = sequence
    
    # รัน tree
    await manager.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### การใช้งาน Blackboard

```python
from enhanced_behavior_tree import Blackboard

# สร้าง blackboard
blackboard = Blackboard()

# สร้าง namespace
blackboard.create_namespace("robot_state")

# เซ็ตค่า
blackboard.set("battery_level", 85, "robot_state")
blackboard.set("position", (10, 20), "robot_state")

# ดึงค่า
battery = blackboard.get("battery_level", "robot_state")
position = blackboard.get("position", "robot_state")

# สมัครรับการแจ้งเตือน
def on_battery_changed(key, value, old_value):
    print(f"Battery changed from {old_value} to {value}")

blackboard.subscribe("battery_level", on_battery_changed, "robot_state")
```

### การสร้าง Custom Nodes

```python
from enhanced_behavior_tree import ActionNode, NodeStatus

class CustomActionNode(ActionNode):
    """Node ที่สร้างขึ้นเอง"""
    
    async def _tick(self) -> NodeStatus:
        try:
            # การทำงานของ node
            result = await self.do_something()
            
            # อัพเดตสถิติ
            self.stats['total_runs'] += 1
            
            return NodeStatus.SUCCESS if result else NodeStatus.FAILURE
            
        except Exception as e:
            self.logger.error(f"Error: {e}")
            return NodeStatus.ERROR
    
    async def do_something(self):
        # การทำงานจริง
        return True
```

### การใช้งาน Configuration

```yaml
# tree_config.yaml
name: "robot_behavior"
type: "SequenceNode"
children:
  - name: "check_battery"
    type: "ConditionNode"
    properties:
      blackboard_key: "battery_level"
      namespace: "robot_state"
      operator: ">="
      expected_value: 20
  
  - name: "move_to_target"
    type: "ActionNode"
    properties:
      timeout: 5.0
      retry_count: 3
```

```python
from enhanced_behavior_tree import ConfigLoader

# โหลด configuration
loader = ConfigLoader()
config = loader.load_file("tree_config.yaml")

# สร้าง tree จาก configuration
manager = BehaviorTreeManager()
manager.load_from_file("tree_config.yaml")
```

### การใช้งาน Visualization

```python
from enhanced_behavior_tree import TreeVisualizer

# สร้าง visualizer
visualizer = TreeVisualizer()

# สร้างแผนภาพ
visualizer.create_graphviz(manager.root, "tree.png")

# แสดงผลแบบ ASCII
print(visualizer.create_ascii(manager.root))

# เริ่ม real-time monitoring
await visualizer.start_monitoring(manager)
```

## 🔍 การติดตามและ Debug

### การใช้งาน Logging

```python
import logging

# ตั้งค่า logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# เพิ่ม debug node
debug_node = DebugLogNode(
    "debug",
    message="Processing target",
    level="DEBUG"
)
```

### การใช้งาน Metrics

```python
# ดูสถิติการทำงาน
stats = manager.get_stats()
print(f"Total ticks: {stats['total_ticks']}")
print(f"Success rate: {stats['success_count'] / stats['total_ticks']:.2%}")

# ดูสถิติของ node
action_node = manager.root.children[0]
print(f"Action runs: {action_node.stats['total_runs']}")
print(f"Average duration: {action_node.stats['average_duration']:.3f}s")
```

## 🛠 Advanced Features

### การใช้งาน Parallel Execution

```python
from enhanced_behavior_tree import ParallelNode, ParallelPolicy

# สร้าง parallel node
parallel = ParallelNode(
    "parallel_tasks",
    policy=ParallelPolicy.REQUIRE_ONE,
    success_threshold=2
)

# เพิ่ม tasks
parallel.add_child(task1)
parallel.add_child(task2)
parallel.add_child(task3)
```

### การใช้งาน Decorators

```python
from enhanced_behavior_tree.nodes.decorators import (
    RetryNode,
    TimeoutNode,
    InverterNode
)

# Retry decorator
retry = RetryNode(
    "retry_move",
    max_attempts=3,
    delay=1.0
)
retry.add_child(move_node)

# Timeout decorator
timeout = TimeoutNode(
    "timeout_action",
    timeout=5.0
)
timeout.add_child(action_node)
```

## 🤝 การ Contribute

1. Fork repository
2. สร้าง feature branch
3. Commit การเปลี่ยนแปลง
4. Push ไปยัง branch
5. สร้าง Pull Request

## 📄 License

โปรเจคนี้อยู่ภายใต้ MIT License - ดูรายละเอียดใน [LICENSE](LICENSE)

## 📚 Documentation

สำหรับเอกสารเพิ่มเติม:
- [API Reference](docs/api_reference.md)
- [Architecture Overview](docs/architecture.md)
- [Examples](docs/examples.md)
