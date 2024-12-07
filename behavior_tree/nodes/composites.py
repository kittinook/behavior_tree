from typing import Dict, Any, Optional, List
import asyncio
from enum import Enum

from ..core.node import ParentNode, NodeStatus, NodeEvent

class ParallelPolicy(Enum):
    """นโยบายการทำงานของ ParallelNode"""
    REQUIRE_ALL = "REQUIRE_ALL"         # ต้องสำเร็จทั้งหมด
    REQUIRE_ONE = "REQUIRE_ONE"         # สำเร็จอย่างน้อย 1
    SEQUENCE_STAR = "SEQUENCE_STAR"     # ทำตามลำดับแต่ไม่หยุดถ้าล้มเหลว
    SELECTOR_STAR = "SELECTOR_STAR"     # เลือกทำแต่ไม่หยุดถ้าสำเร็จ

class MemoryPolicy(Enum):
    """นโยบายการจำสถานะของ node"""
    PERSISTENT = "PERSISTENT"  # จำสถานะไว้ระหว่าง tick
    FRESH = "FRESH"           # รีเซ็ตสถานะทุก tick

class SequenceNode(ParentNode):
    """
    Node ที่รันลูกตามลำดับจนกว่าจะสำเร็จทั้งหมดหรือมีลูกใดล้มเหลว
    
    Attributes:
        memory_policy: นโยบายการจำสถานะ
        current_child: index ของลูกที่กำลังทำงาน
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        memory_policy: MemoryPolicy = MemoryPolicy.FRESH
    ):
        super().__init__(name, properties)
        self.memory_policy = memory_policy
        self.current_child = 0
    
    async def _tick(self) -> NodeStatus:
        if not self.children:
            return NodeStatus.SUCCESS
        
        # เริ่มจากลูกแรกถ้าไม่ได้จำสถานะ
        if self.memory_policy == MemoryPolicy.FRESH:
            self.current_child = 0
        
        while self.current_child < len(self.children):
            current = self.children[self.current_child]
            
            status = await current.tick()
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
                
            if status == NodeStatus.FAILURE:
                if self.memory_policy == MemoryPolicy.FRESH:
                    self.current_child = 0
                return NodeStatus.FAILURE
                
            self.current_child += 1
        
        # สำเร็จทั้งหมด
        self.current_child = 0
        return NodeStatus.SUCCESS
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self.current_child = 0

class SelectorNode(ParentNode):
    """
    Node ที่รันลูกตามลำดับจนกว่าจะมีลูกสำเร็จหรือล้มเหลวทั้งหมด
    
    Attributes:
        memory_policy: นโยบายการจำสถานะ
        current_child: index ของลูกที่กำลังทำงาน
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        memory_policy: MemoryPolicy = MemoryPolicy.FRESH
    ):
        super().__init__(name, properties)
        self.memory_policy = memory_policy
        self.current_child = 0
    
    async def _tick(self) -> NodeStatus:
        if not self.children:
            return NodeStatus.FAILURE
        
        # เริ่มจากลูกแรกถ้าไม่ได้จำสถานะ
        if self.memory_policy == MemoryPolicy.FRESH:
            self.current_child = 0
        
        while self.current_child < len(self.children):
            current = self.children[self.current_child]
            
            status = await current.tick()
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
                
            if status == NodeStatus.SUCCESS:
                if self.memory_policy == MemoryPolicy.FRESH:
                    self.current_child = 0
                return NodeStatus.SUCCESS
                
            self.current_child += 1
        
        # ล้มเหลวทั้งหมด
        self.current_child = 0
        return NodeStatus.FAILURE
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self.current_child = 0

class ParallelNode(ParentNode):
    """
    Node ที่รันลูกพร้อมกัน
    
    Attributes:
        policy: นโยบายการทำงาน
        success_threshold: จำนวนลูกที่ต้องสำเร็จ (ถ้ากำหนด)
        failure_threshold: จำนวนลูกที่ยอมให้ล้มเหลว (ถ้ากำหนด)
        synchronized: ทำงานแบบ synchronized หรือไม่
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        policy: ParallelPolicy = ParallelPolicy.REQUIRE_ALL,
        success_threshold: Optional[int] = None,
        failure_threshold: Optional[int] = None,
        synchronized: bool = False
    ):
        super().__init__(name, properties)
        self.policy = policy
        self.success_threshold = success_threshold
        self.failure_threshold = failure_threshold
        self.synchronized = synchronized
        
        # เก็บสถานะของแต่ละลูก
        self.child_status: Dict[str, NodeStatus] = {}
    
    async def _tick(self) -> NodeStatus:
        if not self.children:
            return NodeStatus.SUCCESS
        
        # รีเซ็ตสถานะถ้าทำงานแบบ synchronized
        if self.synchronized:
            self.child_status.clear()
        
        # สร้าง tasks สำหรับลูกทุกตัว
        tasks = []
        for child in self.children:
            if (not self.synchronized or 
                child.get_path() not in self.child_status):
                tasks.append(self._run_child(child))
        
        # รัน tasks พร้อมกัน
        if tasks:
            await asyncio.gather(*tasks)
        
        # ตรวจสอบผลตามนโยบาย
        return self._evaluate_results()
    
    async def _run_child(self, child: ParentNode) -> None:
        """รันลูกและเก็บสถานะ"""
        status = await child.tick()
        self.child_status[child.get_path()] = status
    
    def _evaluate_results(self) -> NodeStatus:
        """ประเมินผลตามนโยบายที่กำหนด"""
        if not self.child_status:
            return NodeStatus.INVALID
        
        success_count = sum(
            1 for s in self.child_status.values()
            if s == NodeStatus.SUCCESS
        )
        failure_count = sum(
            1 for s in self.child_status.values()
            if s == NodeStatus.FAILURE
        )
        running_count = sum(
            1 for s in self.child_status.values()
            if s == NodeStatus.RUNNING
        )
        
        # ตรวจสอบ threshold ถ้ากำหนด
        if self.success_threshold and success_count >= self.success_threshold:
            return NodeStatus.SUCCESS
            
        if self.failure_threshold and failure_count >= self.failure_threshold:
            return NodeStatus.FAILURE
        
        # ตรวจสอบตามนโยบาย
        if self.policy == ParallelPolicy.REQUIRE_ALL:
            if failure_count > 0:
                return NodeStatus.FAILURE
            if running_count > 0:
                return NodeStatus.RUNNING
            return NodeStatus.SUCCESS
            
        elif self.policy == ParallelPolicy.REQUIRE_ONE:
            if success_count > 0:
                return NodeStatus.SUCCESS
            if running_count > 0:
                return NodeStatus.RUNNING
            return NodeStatus.FAILURE
            
        elif self.policy == ParallelPolicy.SEQUENCE_STAR:
            if running_count > 0:
                return NodeStatus.RUNNING
            if success_count == len(self.children):
                return NodeStatus.SUCCESS
            return NodeStatus.FAILURE
            
        elif self.policy == ParallelPolicy.SELECTOR_STAR:
            if running_count > 0:
                return NodeStatus.RUNNING
            if success_count > 0:
                return NodeStatus.SUCCESS
            return NodeStatus.FAILURE
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self.child_status.clear()

class ReactiveSequence(SequenceNode):
    """
    Sequence node ที่ตรวจสอบเงื่อนไขก่อนหน้าตลอด
    ถ้าเงื่อนไขก่อนหน้าล้มเหลว จะหยุดทำงานทันที
    """
    
    async def _tick(self) -> NodeStatus:
        if not self.children:
            return NodeStatus.SUCCESS
        
        # ตรวจสอบเงื่อนไขทั้งหมดก่อนหน้า
        for i in range(self.current_child):
            status = await self.children[i].tick()
            if status == NodeStatus.FAILURE:
                self.current_child = 0
                return NodeStatus.FAILURE
        
        # ทำงานปกติ
        return await super()._tick()

class ReactiveSelector(SelectorNode):
    """
    Selector node ที่ตรวจสอบเงื่อนไขก่อนหน้าตลอด
    ถ้าเงื่อนไขก่อนหน้าสำเร็จ จะใช้ node นั้นทันที
    """
    
    async def _tick(self) -> NodeStatus:
        if not self.children:
            return NodeStatus.FAILURE
        
        # ตรวจสอบเงื่อนไขทั้งหมดก่อนหน้า
        for i in range(self.current_child):
            status = await self.children[i].tick()
            if status == NodeStatus.SUCCESS:
                self.current_child = i
                return NodeStatus.SUCCESS
        
        # ทำงานปกติ
        return await super()._tick()

class RandomSelector(SelectorNode):
    """
    Selector node ที่สุ่มลำดับการทำงานของลูก
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        memory_policy: MemoryPolicy = MemoryPolicy.FRESH
    ):
        super().__init__(name, properties, memory_policy)
        self._shuffled_indices: List[int] = []
    
    async def _tick(self) -> NodeStatus:
        if not self.children:
            return NodeStatus.FAILURE
        
        # สุ่มลำดับใหม่ถ้าจำเป็น
        if not self._shuffled_indices:
            import random
            self._shuffled_indices = list(range(len(self.children)))
            random.shuffle(self._shuffled_indices)
        
        # ทำงานตามลำดับที่สุ่ม
        while self._shuffled_indices:
            index = self._shuffled_indices.pop(0)
            status = await self.children[index].tick()
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            if status == NodeStatus.SUCCESS:
                self._shuffled_indices.clear()
                return NodeStatus.SUCCESS
        
        return NodeStatus.FAILURE
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self._shuffled_indices.clear()
