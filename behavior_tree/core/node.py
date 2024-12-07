from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Dict, Any, Optional, List, Set, Callable
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

class NodeStatus(Enum):
    """สถานะที่เป็นไปได้ของ node"""
    SUCCESS = auto()
    FAILURE = auto()
    RUNNING = auto()
    INVALID = auto()
    SKIPPED = auto()  # สำหรับกรณีที่ node ถูกข้ามการทำงาน
    ERROR = auto()    # สำหรับกรณีที่เกิด error ระหว่างทำงาน

class NodeEvent(Enum):
    """เหตุการณ์ที่เกิดขึ้นกับ node"""
    INITIALIZED = auto()
    ENTERING = auto()      # ก่อนเริ่มทำงาน
    EXITING = auto()       # หลังทำงานเสร็จ
    SETUP = auto()         # เมื่อเริ่มต้น node
    SHUTDOWN = auto()      # เมื่อปิด node
    STATUS_CHANGED = auto() # เมื่อสถานะเปลี่ยน
    ERROR = auto()         # เมื่อเกิด error

@dataclass
class NodeMetadata:
    """ข้อมูล metadata ของ node"""
    created_at: datetime = field(default_factory=datetime.now)
    last_tick: Optional[datetime] = None
    total_ticks: int = 0
    success_count: int = 0
    failure_count: int = 0
    error_count: int = 0
    average_tick_time: float = 0.0
    last_status: Optional[NodeStatus] = None
    
    def update_tick_stats(self, duration: float, status: NodeStatus) -> None:
        """อัพเดตสถิติการทำงาน"""
        self.last_tick = datetime.now()
        self.total_ticks += 1
        
        # อัพเดตสถิติตามสถานะ
        if status == NodeStatus.SUCCESS:
            self.success_count += 1
        elif status == NodeStatus.FAILURE:
            self.failure_count += 1
        elif status == NodeStatus.ERROR:
            self.error_count += 1
        
        # คำนวณเวลาเฉลี่ย
        self.average_tick_time = (
            (self.average_tick_time * (self.total_ticks - 1) + duration) 
            / self.total_ticks
        )
        self.last_status = status

class BehaviorNode(ABC):
    """
    Base class สำหรับ behavior tree node ทั้งหมด
    
    Attributes:
        name: ชื่อของ node
        properties: คุณสมบัติของ node
        status: สถานะปัจจุบัน
        parent: node แม่
        blackboard: blackboard ที่ใช้
        logger: logger สำหรับ node
        metadata: ข้อมูลสถิติของ node
        event_handlers: handler สำหรับ event ต่างๆ
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        preconditions: Optional[List[Callable[[], bool]]] = None,
        postconditions: Optional[List[Callable[[], bool]]] = None
    ):
        self.name = name
        self.properties = properties or {}
        self.status = NodeStatus.INVALID
        self.parent: Optional['BehaviorNode'] = None
        self.blackboard = None
        self.preconditions = preconditions or []
        self.postconditions = postconditions or []
        
        # ตั้งค่า logger
        self.logger = logging.getLogger(f"BehaviorTree.{name}")
        
        # สร้าง metadata
        self.metadata = NodeMetadata()
        
        # ตั้งค่า event handlers
        self.event_handlers: Dict[NodeEvent, Set[Callable]] = {
            event: set() for event in NodeEvent
        }
        
        # สถานะการทำงาน
        self._is_initialized = False
        self._is_setup = False
        self._current_tick_start: Optional[float] = None
    
    async def setup(self) -> None:
        """ตั้งค่าเริ่มต้นของ node"""
        if not self._is_setup:
            await self._emit_event(NodeEvent.SETUP)
            self._is_setup = True
    
    async def shutdown(self) -> None:
        """ปิดการทำงานของ node"""
        if self._is_setup:
            await self._emit_event(NodeEvent.SHUTDOWN)
            self._is_setup = False
    
    def initialize(self, blackboard) -> None:
        """เริ่มต้น node ด้วย blackboard"""
        self.blackboard = blackboard
        self._is_initialized = True
        asyncio.create_task(self._emit_event(NodeEvent.INITIALIZED))
    
    def add_event_handler(
        self,
        event: NodeEvent,
        handler: Callable[['BehaviorNode', NodeEvent], None]
    ) -> None:
        """เพิ่ม event handler"""
        self.event_handlers[event].add(handler)
    
    def remove_event_handler(
        self,
        event: NodeEvent,
        handler: Callable[['BehaviorNode', NodeEvent], None]
    ) -> None:
        """ลบ event handler"""
        self.event_handlers[event].discard(handler)
    
    async def _emit_event(self, event: NodeEvent) -> None:
        """ส่ง event ไปยัง handlers ทั้งหมด"""
        for handler in self.event_handlers[event]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(self, event)
                else:
                    handler(self, event)
            except Exception as e:
                self.logger.error(f"Error in event handler: {e}")
    
    def _check_preconditions(self) -> bool:
        """ตรวจสอบ preconditions ทั้งหมด"""
        for condition in self.preconditions:
            try:
                if not condition():
                    return False
            except Exception as e:
                self.logger.error(f"Error in precondition: {e}")
                return False
        return True
    
    def _check_postconditions(self) -> bool:
        """ตรวจสอบ postconditions ทั้งหมด"""
        for condition in self.postconditions:
            try:
                if not condition():
                    return False
            except Exception as e:
                self.logger.error(f"Error in postcondition: {e}")
                return False
        return True
    
    async def tick(self) -> NodeStatus:
        """
        ประมวลผล node ในรอบนี้
        
        Returns:
            NodeStatus: สถานะหลังจากประมวลผล
        """
        if not self._is_initialized:
            self.logger.error("Node not initialized")
            return NodeStatus.ERROR
        
        if not self._is_setup:
            await self.setup()
        
        # เช็ค preconditions
        if not self._check_preconditions():
            self.status = NodeStatus.SKIPPED
            return self.status
        
        # เริ่มจับเวลา
        self._current_tick_start = time.time()
        
        try:
            # แจ้ง event ก่อนทำงาน
            await self._emit_event(NodeEvent.ENTERING)
            
            # ทำงานหลัก
            self.status = await self._tick()
            
            # เช็ค postconditions
            if not self._check_postconditions():
                self.status = NodeStatus.FAILURE
            
        except Exception as e:
            self.logger.error(f"Error during tick: {e}")
            self.status = NodeStatus.ERROR
            await self._emit_event(NodeEvent.ERROR)
            
        finally:
            # จบการทำงานและอัพเดตสถิติ
            duration = time.time() - self._current_tick_start
            self.metadata.update_tick_stats(duration, self.status)
            self._current_tick_start = None
            
            # แจ้ง event หลังทำงาน
            await self._emit_event(NodeEvent.EXITING)
        
        return self.status
    
    @abstractmethod
    async def _tick(self) -> NodeStatus:
        """
        การทำงานหลักของ node ที่ต้อง implement
        
        Returns:
            NodeStatus: สถานะหลังทำงาน
        """
        pass
    
    def reset(self) -> None:
        """รีเซ็ตสถานะของ node"""
        self.status = NodeStatus.INVALID
    
    def get_path(self) -> str:
        """
        Returns:
            str: path ของ node จาก root
        """
        if self.parent is None:
            return self.name
        return f"{self.parent.get_path()}/{self.name}"
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(name='{self.name}', status={self.status.name})"
        )

class LeafNode(BehaviorNode):
    """Base class สำหรับ node ที่ไม่มีลูก (Action และ Condition nodes)"""
    pass

class ParentNode(BehaviorNode):
    """
    Base class สำหรับ node ที่มีลูก
    
    Attributes:
        children: รายการ node ลูก
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        preconditions: Optional[List[Callable[[], bool]]] = None,
        postconditions: Optional[List[Callable[[], bool]]] = None
    ):
        super().__init__(name, properties, preconditions, postconditions)
        self.children: List[BehaviorNode] = []
    
    def add_child(self, child: BehaviorNode) -> None:
        """เพิ่ม node ลูก"""
        child.parent = self
        self.children.append(child)
        if self.blackboard:
            child.initialize(self.blackboard)
    
    def remove_child(self, child: BehaviorNode) -> None:
        """ลบ node ลูก"""
        if child in self.children:
            child.parent = None
            self.children.remove(child)
    
    async def setup(self) -> None:
        """ตั้งค่าเริ่มต้นของ node และลูกทั้งหมด"""
        await super().setup()
        for child in self.children:
            await child.setup()
    
    async def shutdown(self) -> None:
        """ปิดการทำงานของ node และลูกทั้งหมด"""
        for child in self.children:
            await child.shutdown()
        await super().shutdown()
    
    def initialize(self, blackboard) -> None:
        """เริ่มต้น node และลูกทั้งหมดด้วย blackboard"""
        super().initialize(blackboard)
        for child in self.children:
            child.initialize(blackboard)
    
    def reset(self) -> None:
        """รีเซ็ตสถานะของ node และลูกทั้งหมด"""
        super().reset()
        for child in self.children:
            child.reset()
