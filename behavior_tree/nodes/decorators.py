from typing import Dict, Any, Optional, Callable, Union, List
import asyncio
import time
from datetime import datetime, timedelta
import random
from functools import wraps

from ..core.node import ParentNode, NodeStatus, NodeEvent

class DecoratorNode(ParentNode):
    """
    Base class สำหรับ Decorator nodes
    จำกัดให้มีลูกได้แค่ 1 node
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        child: Optional[ParentNode] = None
    ):
        super().__init__(name, properties)
        if child:
            self.add_child(child)
    
    def add_child(self, child: ParentNode) -> None:
        """เพิ่ม child node (จำกัด 1 node)"""
        if len(self.children) >= 1:
            raise ValueError(f"Decorator node '{self.name}' can only have one child")
        super().add_child(child)
    
    @property
    def child(self) -> Optional[ParentNode]:
        """เข้าถึง child node"""
        return self.children[0] if self.children else None

class InverterNode(DecoratorNode):
    """
    กลับสถานะของ child node
    SUCCESS -> FAILURE, FAILURE -> SUCCESS
    """
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        status = await self.child.tick()
        
        if status == NodeStatus.SUCCESS:
            return NodeStatus.FAILURE
        elif status == NodeStatus.FAILURE:
            return NodeStatus.SUCCESS
        return status

class ForceSuccessNode(DecoratorNode):
    """เปลี่ยนสถานะ FAILURE เป็น SUCCESS"""
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.SUCCESS
        
        status = await self.child.tick()
        return (NodeStatus.SUCCESS if status == NodeStatus.FAILURE 
                else status)

class ForceFailureNode(DecoratorNode):
    """เปลี่ยนสถานะ SUCCESS เป็น FAILURE"""
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        status = await self.child.tick()
        return (NodeStatus.FAILURE if status == NodeStatus.SUCCESS 
                else status)

class RepeatNode(DecoratorNode):
    """
    ทำซ้ำ child node ตามจำนวนครั้งที่กำหนด
    
    Properties:
        num_cycles: จำนวนรอบที่จะทำซ้ำ (-1 = ไม่จำกัด)
        success_threshold: จำนวนครั้งที่ต้องสำเร็จ
        failure_threshold: จำนวนครั้งที่ยอมให้ล้มเหลว
        reset_after: รีเซ็ต child หลังจากทำงานกี่รอบ
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        num_cycles: int = -1,
        success_threshold: Optional[int] = None,
        failure_threshold: Optional[int] = None,
        reset_after: Optional[int] = None
    ):
        super().__init__(name, properties)
        self.num_cycles = num_cycles
        self.success_threshold = success_threshold
        self.failure_threshold = failure_threshold
        self.reset_after = reset_after
        
        self._current_cycle = 0
        self._success_count = 0
        self._failure_count = 0
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        # ตรวจสอบจำนวนรอบ
        if (self.num_cycles != -1 and 
            self._current_cycle >= self.num_cycles):
            return NodeStatus.SUCCESS
        
        # รีเซ็ตถ้าถึงรอบที่กำหนด
        if (self.reset_after and 
            self._current_cycle % self.reset_after == 0):
            self.child.reset()
        
        status = await self.child.tick()
        self._current_cycle += 1
        
        # นับจำนวนสำเร็จ/ล้มเหลว
        if status == NodeStatus.SUCCESS:
            self._success_count += 1
        elif status == NodeStatus.FAILURE:
            self._failure_count += 1
        
        # ตรวจสอบ threshold
        if (self.success_threshold and 
            self._success_count >= self.success_threshold):
            return NodeStatus.SUCCESS
        
        if (self.failure_threshold and 
            self._failure_count >= self.failure_threshold):
            return NodeStatus.FAILURE
        
        if status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING
        
        return NodeStatus.RUNNING if self.num_cycles == -1 else status
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self._current_cycle = 0
        self._success_count = 0
        self._failure_count = 0

class RetryNode(DecoratorNode):
    """
    ลองทำซ้ำเมื่อล้มเหลว
    
    Properties:
        max_attempts: จำนวนครั้งสูงสุดที่จะลอง
        delay: ระยะเวลารอระหว่างการลอง
        exponential_backoff: เพิ่มระยะเวลารอแบบ exponential
        jitter: สุ่มระยะเวลารอเพิ่ม/ลด
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        max_attempts: int = 3,
        delay: float = 0,
        exponential_backoff: bool = False,
        jitter: float = 0
    ):
        super().__init__(name, properties)
        self.max_attempts = max_attempts
        self.base_delay = delay
        self.exponential_backoff = exponential_backoff
        self.jitter = jitter
        self._attempt = 0
    
    def _calculate_delay(self) -> float:
        """คำนวณระยะเวลารอ"""
        if self.base_delay <= 0:
            return 0
            
        delay = (self.base_delay * (2 ** self._attempt) 
                if self.exponential_backoff 
                else self.base_delay)
        
        if self.jitter > 0:
            jitter = random.uniform(-self.jitter, self.jitter)
            delay = max(0, delay + jitter)
        
        return delay
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        while self._attempt < self.max_attempts:
            status = await self.child.tick()
            
            if status == NodeStatus.SUCCESS:
                self._attempt = 0
                return NodeStatus.SUCCESS
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            
            self._attempt += 1
            delay = self._calculate_delay()
            if delay > 0:
                await asyncio.sleep(delay)
        
        self._attempt = 0
        return NodeStatus.FAILURE
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self._attempt = 0

class TimeoutNode(DecoratorNode):
    """
    จำกัดเวลาการทำงานของ child node
    
    Properties:
        timeout: ระยะเวลาที่อนุญาต (วินาที)
        on_timeout: การทำงานเมื่อหมดเวลา (FAILURE หรือ SUCCESS)
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        timeout: Union[float, timedelta] = 1.0,
        on_timeout: NodeStatus = NodeStatus.FAILURE
    ):
        super().__init__(name, properties)
        self.timeout = (timeout.total_seconds() 
                       if isinstance(timeout, timedelta) 
                       else float(timeout))
        self.on_timeout = on_timeout
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        try:
            # สร้าง task และใช้ asyncio.wait_for แทน asyncio.timeout
            task = asyncio.create_task(self.child.tick())
            status = await asyncio.wait_for(task, timeout=self.timeout)
            return status
            # async with asyncio.timeout(self.timeout):
            #     return await self.child.tick()
        except asyncio.TimeoutError:
            self.logger.warning(
                f"Node {self.child.name} timed out after {self.timeout}s"
            )
            return self.on_timeout

class DelayNode(DecoratorNode):
    """
    หน่วงเวลาก่อนและ/หรือหลังการทำงานของ child node
    
    Properties:
        pre_delay: ระยะเวลารอก่อนทำงาน
        post_delay: ระยะเวลารอหลังทำงาน
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        pre_delay: float = 0,
        post_delay: float = 0
    ):
        super().__init__(name, properties)
        self.pre_delay = pre_delay
        self.post_delay = post_delay
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        if self.pre_delay > 0:
            await asyncio.sleep(self.pre_delay)
        
        status = await self.child.tick()
        
        if self.post_delay > 0:
            await asyncio.sleep(self.post_delay)
        
        return status

class BlackboardConditionNode(DecoratorNode):
    """
    ตรวจสอบเงื่อนไขใน blackboard ก่อนทำงาน
    
    Properties:
        key: คีย์ที่จะตรวจสอบ
        value: ค่าที่ต้องการ
        operator: ตัวดำเนินการเปรียบเทียบ (==, !=, >, <, >=, <=)
        namespace: namespace ใน blackboard
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        key: str = None,
        value: Any = None,
        operator: str = "==",
        namespace: str = "default"
    ):
        super().__init__(name, properties)
        self.key = key or properties.get('key')
        self.value = value or properties.get('value')
        self.operator = operator
        self.namespace = namespace
        
        if not self.key:
            raise ValueError("Blackboard key must be specified")
    
    def _check_condition(self, bb_value: Any) -> bool:
        """ตรวจสอบเงื่อนไข"""
        if bb_value is None:
            return False
            
        operators = {
            "==": lambda x, y: x == y,
            "!=": lambda x, y: x != y,
            ">": lambda x, y: x > y,
            "<": lambda x, y: x < y,
            ">=": lambda x, y: x >= y,
            "<=": lambda x, y: x <= y
        }
        
        if self.operator not in operators:
            raise ValueError(f"Invalid operator: {self.operator}")
            
        return operators[self.operator](bb_value, self.value)
    
    async def _tick(self) -> NodeStatus:
        if not self.child or not self.blackboard:
            return NodeStatus.FAILURE
        
        bb_value = self.blackboard.get(self.key, self.namespace)
        if not self._check_condition(bb_value):
            return NodeStatus.FAILURE
        
        return await self.child.tick()

class CooldownNode(DecoratorNode):
    """
    กำหนด cooldown time ระหว่างการทำงาน
    
    Properties:
        cooldown: ระยะเวลา cooldown (วินาที)
        reset_on_failure: รีเซ็ต cooldown เมื่อล้มเหลว
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        cooldown: float = 1.0,
        reset_on_failure: bool = False
    ):
        super().__init__(name, properties)
        self.cooldown = cooldown
        self.reset_on_failure = reset_on_failure
        self._last_success_time: Optional[float] = None
    
    async def _tick(self) -> NodeStatus:
        if not self.child:
            return NodeStatus.FAILURE
        
        # ตรวจสอบ cooldown
        if self._last_success_time is not None:
            elapsed = time.time() - self._last_success_time
            if elapsed < self.cooldown:
                return NodeStatus.FAILURE
        
        status = await self.child.tick()
        
        if status == NodeStatus.SUCCESS:
            self._last_success_time = time.time()
        elif status == NodeStatus.FAILURE and self.reset_on_failure:
            self._last_success_time = None
        
        return status
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self._last_success_time = None
