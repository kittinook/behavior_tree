from typing import Dict, Any, Optional, List, Set, Type
import asyncio
import logging
import time
import json
from pathlib import Path
from datetime import datetime
import yaml
import threading
from concurrent.futures import ThreadPoolExecutor

from .node import BehaviorNode, NodeStatus, NodeEvent, ParentNode
from .blackboard import Blackboard
from ..utils.config_loader import ConfigLoader

class TreeSnapshot:
    """คลาสสำหรับเก็บ snapshot ของ tree ณ เวลาใดเวลาหนึ่ง"""
    def __init__(self, tree_manager: 'BehaviorTreeManager'):
        self.timestamp = datetime.now()
        self.node_states: Dict[str, NodeStatus] = {}
        self.blackboard_data: Dict[str, Any] = {}
        
        # บันทึกสถานะของ nodes
        self._capture_node_states(tree_manager.root)
        
        # บันทึกข้อมูลใน blackboard
        if tree_manager.blackboard:
            for namespace in tree_manager.blackboard._data.keys():
                self.blackboard_data[namespace] = {
                    key: tree_manager.blackboard.get(key, namespace)
                    for key in tree_manager.blackboard.get_keys(namespace)
                }
    
    def _capture_node_states(self, node: Optional[BehaviorNode]) -> None:
        """บันทึกสถานะของ node และลูกทั้งหมด"""
        if node:
            self.node_states[node.get_path()] = node.status
            if isinstance(node, ParentNode):
                for child in node.children:
                    self._capture_node_states(child)

class TreeExecutionContext:
    """คลาสสำหรับเก็บข้อมูลการทำงานของ tree"""
    def __init__(self):
        self.start_time = datetime.now()
        self.total_ticks = 0
        self.snapshots: List[TreeSnapshot] = []
        self.last_tick_duration = 0.0
        self.average_tick_duration = 0.0
        self.error_count = 0
        self.success_count = 0
        self.failure_count = 0

class BehaviorTreeManager:
    """
    คลาสหลักสำหรับจัดการ Behavior Tree
    รองรับการทำงานแบบ async, การจัดการ subtrees, และการบันทึก/โหลดสถานะ
    """
    
    def __init__(
        self,
        tick_rate: float = 60.0,
        max_workers: int = 4,
        enable_snapshots: bool = False,
        snapshot_interval: int = 100,  # ทุกๆ กี่ ticks จะเก็บ snapshot
        log_level: int = logging.INFO
    ):
        # ตั้งค่าพื้นฐาน
        self.tick_rate = tick_rate
        self.root: Optional[BehaviorNode] = None
        self.blackboard = Blackboard()
        self.running = False
        self.paused = False
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # ตั้งค่าการทำงาน
        self.enable_snapshots = enable_snapshots
        self.snapshot_interval = snapshot_interval
        self.context = TreeExecutionContext()
        
        # สำหรับจัดการ subtrees
        self.subtrees: Dict[str, BehaviorNode] = {}
        self._subtree_locks: Dict[str, threading.Lock] = {}
        
        # ตั้งค่า logging
        self.logger = logging.getLogger("BehaviorTreeManager")
        self.logger.setLevel(log_level)
        
        # สำหรับโหลด configuration
        self.config_loader = ConfigLoader()
    
    async def tick_tree(self) -> NodeStatus:
        """ประมวลผล tree หนึ่งรอบ"""
        if not self.root:
            self.logger.warning("No root node set")
            return NodeStatus.INVALID
        
        if self.paused:
            return self.root.status
        
        start_time = time.time()
        
        try:
            status = await self.root.tick()
            
            # อัพเดตสถิติ
            self.context.total_ticks += 1
            self.context.last_tick_duration = time.time() - start_time
            self.context.average_tick_duration = (
                (self.context.average_tick_duration * 
                 (self.context.total_ticks - 1) +
                 self.context.last_tick_duration) /
                self.context.total_ticks
            )
            
            if status == NodeStatus.SUCCESS:
                self.context.success_count += 1
            elif status == NodeStatus.FAILURE:
                self.context.failure_count += 1
            elif status == NodeStatus.ERROR:
                self.context.error_count += 1
            
            # เก็บ snapshot ถ้าเปิดใช้งาน
            if (self.enable_snapshots and 
                self.context.total_ticks % self.snapshot_interval == 0):
                self.take_snapshot()
            
            return status
            
        except Exception as e:
            self.logger.error(f"Error during tree tick: {e}")
            self.context.error_count += 1
            return NodeStatus.ERROR
    
    async def run(self) -> None:
        """รัน behavior tree แบบต่อเนื่อง"""
        if not self.root:
            self.logger.error("Cannot run tree: No root node set")
            return
        
        self.running = True
        tick_interval = 1.0 / self.tick_rate
        
        self.logger.info(
            f"Starting behavior tree with tick rate: {self.tick_rate} Hz"
        )
        
        try:
            # Setup nodes
            await self.root.setup()
            
            while self.running:
                start_time = time.time()
                
                status = await self.tick_tree()
                self.logger.debug(f"Tree tick completed with status: {status}")
                
                # รักษา tick rate
                elapsed = time.time() - start_time
                if elapsed < tick_interval:
                    await asyncio.sleep(tick_interval - elapsed)
                else:
                    self.logger.warning(
                        f"Tick took longer than interval: {elapsed:.4f}s"
                    )
                    
        except asyncio.CancelledError:
            self.logger.info("Tree execution cancelled")
        except Exception as e:
            self.logger.error(f"Error during tree execution: {e}")
        finally:
            # Shutdown nodes
            await self.root.shutdown()
            self.running = False
    
    def stop(self) -> None:
        """หยุดการทำงานของ tree"""
        self.running = False
        self.logger.info("Stopping behavior tree")
    
    def pause(self) -> None:
        """หยุดการทำงานชั่วคราว"""
        self.paused = True
        self.logger.info("Pausing behavior tree")
    
    def resume(self) -> None:
        """เริ่มการทำงานต่อ"""
        self.paused = False
        self.logger.info("Resuming behavior tree")
    
    def take_snapshot(self) -> TreeSnapshot:
        """สร้าง snapshot ของ tree ปัจจุบัน"""
        snapshot = TreeSnapshot(self)
        self.context.snapshots.append(snapshot)
        return snapshot
    
    def restore_snapshot(self, snapshot: TreeSnapshot) -> None:
        """กู้คืนสถานะของ tree จาก snapshot"""
        def restore_node_states(node: BehaviorNode) -> None:
            path = node.get_path()
            if path in snapshot.node_states:
                node.status = snapshot.node_states[path]
            if isinstance(node, ParentNode):
                for child in node.children:
                    restore_node_states(child)
        
        if self.root:
            restore_node_states(self.root)
        
        # กู้คืนข้อมูล blackboard
        for namespace, data in snapshot.blackboard_data.items():
            for key, value in data.items():
                self.blackboard.set(key, value, namespace)
    
    def register_subtree(self, name: str, root: BehaviorNode) -> None:
        """ลงทะเบียน subtree"""
        self._subtree_locks[name] = threading.Lock()
        with self._subtree_locks[name]:
            self.subtrees[name] = root
            root.initialize(self.blackboard)
    
    def get_subtree(self, name: str) -> Optional[BehaviorNode]:
        """ดึง subtree ตามชื่อ"""
        with self._subtree_locks.get(name, threading.Lock()):
            return self.subtrees.get(name)
    
    def save_to_file(self, file_path: str) -> None:
        """บันทึก tree ลงไฟล์"""
        def serialize_node(node: BehaviorNode) -> Dict[str, Any]:
            data = {
                'name': node.name,
                'type': node.__class__.__name__,
                'properties': node.properties
            }
            if isinstance(node, ParentNode):
                data['children'] = [
                    serialize_node(child) for child in node.children
                ]
            return data
        
        tree_data = {
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'tick_rate': self.tick_rate,
                'total_ticks': self.context.total_ticks
            },
            'tree': serialize_node(self.root) if self.root else None,
            'subtrees': {
                name: serialize_node(root)
                for name, root in self.subtrees.items()
            }
        }
        
        path = Path(file_path)
        if path.suffix == '.json':
            with open(path, 'w') as f:
                json.dump(tree_data, f, indent=2)
        elif path.suffix in {'.yml', '.yaml'}:
            with open(path, 'w') as f:
                yaml.dump(tree_data, f)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
    
    def load_from_file(self, file_path: str) -> None:
        """โหลด tree จากไฟล์"""
        tree_data = self.config_loader.load_file(file_path)
        if not tree_data:
            raise ValueError("Failed to load tree configuration")
        
        # ตั้งค่าจาก metadata
        if 'metadata' in tree_data:
            self.tick_rate = tree_data['metadata'].get('tick_rate', self.tick_rate)
        
        # สร้าง main tree
        if 'tree' in tree_data:
            self.root = self._build_tree(tree_data['tree'])
            if self.root:
                self.root.initialize(self.blackboard)
        
        # สร้าง subtrees
        if 'subtrees' in tree_data:
            for name, subtree_data in tree_data['subtrees'].items():
                subtree = self._build_tree(subtree_data)
                if subtree:
                    self.register_subtree(name, subtree)
    
    def _build_tree(self, config: Dict[str, Any]) -> Optional[BehaviorNode]:
        """สร้าง tree จาก configuration"""
        try:
            # นำเข้า node types ที่จำเป็น
            from ..nodes.composites import (
                SequenceNode, SelectorNode, ParallelNode
            )
            from ..nodes.decorators import (
                InverterNode, RetryNode, TimeoutNode
            )
            from ..nodes.leaves import ActionNode, ConditionNode
            
            # map ระหว่างชื่อ class และ class จริง
            node_classes: Dict[str, Type[BehaviorNode]] = {
                'SequenceNode': SequenceNode,
                'SelectorNode': SelectorNode,
                'ParallelNode': ParallelNode,
                'InverterNode': InverterNode,
                'RetryNode': RetryNode,
                'TimeoutNode': TimeoutNode,
                'ActionNode': ActionNode,
                'ConditionNode': ConditionNode
            }
            
            node_type = config['type']
            if node_type not in node_classes:
                raise ValueError(f"Unknown node type: {node_type}")
            
            # สร้าง node
            node_class = node_classes[node_type]
            node = node_class(
                name=config['name'],
                properties=config.get('properties', {})
            )
            
            # เพิ่ม children (ถ้ามี)
            if 'children' in config and isinstance(node, ParentNode):
                for child_config in config['children']:
                    child = self._build_tree(child_config)
                    if child:
                        node.add_child(child)
            
            return node
            
        except Exception as e:
            self.logger.error(f"Error building tree node: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """ดึงสถิติการทำงานของ tree"""
        return {
            'total_ticks': self.context.total_ticks,
            'average_tick_duration': self.context.average_tick_duration,
            'error_count': self.context.error_count,
            'success_count': self.context.success_count,
            'failure_count': self.context.failure_count,
            'uptime': (datetime.now() - self.context.start_time).total_seconds(),
            'snapshot_count': len(self.context.snapshots),
            'current_status': self.root.status if self.root else None
        }
