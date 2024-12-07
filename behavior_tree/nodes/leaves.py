from typing import Dict, Any, Optional, Callable, Awaitable, Union, List
import asyncio
import logging
from enum import Enum
from datetime import datetime, timedelta
import inspect
from functools import wraps

from ..core.node import LeafNode, NodeStatus, NodeEvent

class ActionResult(Enum):
    """ผลลัพธ์ที่เป็นไปได้ของ Action"""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"

def action_result_to_status(result: Union[ActionResult, bool, None]) -> NodeStatus:
    """แปลง ActionResult เป็น NodeStatus"""
    if isinstance(result, ActionResult):
        return {
            ActionResult.SUCCESS: NodeStatus.SUCCESS,
            ActionResult.FAILURE: NodeStatus.FAILURE,
            ActionResult.RUNNING: NodeStatus.RUNNING,
            ActionResult.ERROR: NodeStatus.FAILURE,
            ActionResult.CANCELLED: NodeStatus.FAILURE
        }[result]
    elif isinstance(result, bool):
        return NodeStatus.SUCCESS if result else NodeStatus.FAILURE
    elif result is None:
        return NodeStatus.SUCCESS
    else:
        return NodeStatus.FAILURE

class ActionNode(LeafNode):
    """
    Node สำหรับทำงานที่กำหนด
    รองรับทั้งฟังก์ชันแบบ sync และ async
    
    Properties:
        action_func: ฟังก์ชันที่จะทำงาน
        args: arguments ที่ส่งให้ฟังก์ชัน
        kwargs: keyword arguments ที่ส่งให้ฟังก์ชัน
        timeout: เวลาที่อนุญาตให้ทำงาน
        retry_count: จำนวนครั้งที่จะลองใหม่ถ้าล้มเหลว
        ignore_errors: ไม่สนใจ error ที่เกิดขึ้น
    """
    
    def __init__(
        self,
        name: str,
        action_func: Optional[Callable] = None,
        properties: Optional[Dict[str, Any]] = None,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        timeout: Optional[float] = None,
        retry_count: int = 0,
        ignore_errors: bool = False
    ):
        super().__init__(name, properties)
        self.action_func = action_func
        self.args = args or []
        self.kwargs = kwargs or {}
        self.timeout = timeout
        self.retry_count = retry_count
        self.ignore_errors = ignore_errors
        
        self._current_retry = 0
        self._last_run: Optional[datetime] = None
        self._is_running = False
        self._cancel_requested = False
        
        # เก็บสถิติ
        self.stats = {
            'total_runs': 0,
            'successful_runs': 0,
            'failed_runs': 0,
            'error_runs': 0,
            'average_duration': 0.0,
            'last_result': None,
            'last_error': None
        }
    
    def request_cancel(self) -> None:
        """ขอยกเลิกการทำงาน"""
        self._cancel_requested = True
    
    async def _execute_action(self) -> ActionResult:
        """รันฟังก์ชันที่กำหนด"""
        if not self.action_func:
            return ActionResult.SUCCESS
        
        try:
            if inspect.iscoroutinefunction(self.action_func):
                result = await self.action_func(*self.args, **self.kwargs)
            else:
                result = await asyncio.to_thread(
                    self.action_func, *self.args, **self.kwargs
                )
            
            if isinstance(result, (ActionResult, bool)) or result is None:
                return result
            return ActionResult.SUCCESS
            
        except asyncio.CancelledError:
            return ActionResult.CANCELLED
        except Exception as e:
            if self.ignore_errors:
                self.logger.warning(f"Ignored error in action: {e}")
                return ActionResult.SUCCESS
            self.logger.error(f"Error in action: {e}")
            self.stats['last_error'] = str(e)
            return ActionResult.ERROR
    
    async def _tick(self) -> NodeStatus:
        if self._cancel_requested:
            self._cancel_requested = False
            return NodeStatus.FAILURE
        
        self._is_running = True
        start_time = datetime.now()
        
        try:
            while self._current_retry <= self.retry_count:
                if self.timeout:
                    try:
                        async with asyncio.timeout(self.timeout):
                            result = await self._execute_action()
                    except asyncio.TimeoutError:
                        self.logger.warning(
                            f"Action timed out after {self.timeout}s"
                        )
                        result = ActionResult.FAILURE
                else:
                    result = await self._execute_action()
                
                # อัพเดตสถิติ
                self.stats['total_runs'] += 1
                if result == ActionResult.SUCCESS:
                    self.stats['successful_runs'] += 1
                elif result == ActionResult.FAILURE:
                    self.stats['failed_runs'] += 1
                elif result == ActionResult.ERROR:
                    self.stats['error_runs'] += 1
                
                duration = (datetime.now() - start_time).total_seconds()
                self.stats['average_duration'] = (
                    (self.stats['average_duration'] * 
                     (self.stats['total_runs'] - 1) + duration) /
                    self.stats['total_runs']
                )
                
                self.stats['last_result'] = result
                self._last_run = datetime.now()
                
                # ตรวจสอบผลลัพธ์
                if result in (ActionResult.SUCCESS, ActionResult.RUNNING):
                    return action_result_to_status(result)
                
                if (result == ActionResult.FAILURE and 
                    self._current_retry < self.retry_count):
                    self._current_retry += 1
                    continue
                
                return action_result_to_status(result)
            
            return NodeStatus.FAILURE
            
        finally:
            self._is_running = False
            self._current_retry = 0
    
    def reset(self) -> None:
        """รีเซ็ตสถานะ"""
        super().reset()
        self._current_retry = 0
        self._cancel_requested = False

class ConditionNode(LeafNode):
    """
    Node สำหรับตรวจสอบเงื่อนไข
    รองรับทั้งฟังก์ชันและการตรวจสอบค่าใน blackboard
    
    Properties:
        condition_func: ฟังก์ชันที่ใช้ตรวจสอบ
        args: arguments ที่ส่งให้ฟังก์ชัน
        kwargs: keyword arguments ที่ส่งให้ฟังก์ชัน
        blackboard_key: คีย์ใน blackboard ที่จะตรวจสอบ
        expected_value: ค่าที่ต้องการ
        operator: ตัวดำเนินการเปรียบเทียบ
        namespace: namespace ใน blackboard
    """
    
    def __init__(
        self,
        name: str,
        condition_func: Optional[Callable] = None,
        properties: Optional[Dict[str, Any]] = None,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        blackboard_key: Optional[str] = None,
        expected_value: Any = None,
        operator: str = "==",
        namespace: str = "default"
    ):
        super().__init__(name, properties)
        self.condition_func = condition_func
        self.args = args or []
        self.kwargs = kwargs or {}
        self.blackboard_key = blackboard_key
        self.expected_value = expected_value
        self.operator = operator
        self.namespace = namespace
        
        # เก็บสถิติ
        self.stats = {
            'total_checks': 0,
            'true_results': 0,
            'false_results': 0,
            'error_checks': 0,
            'last_result': None,
            'last_error': None
        }
    
    def _check_blackboard(self) -> bool:
        """ตรวจสอบค่าใน blackboard"""
        if not self.blackboard or not self.blackboard_key:
            return False
        
        value = self.blackboard.get(self.blackboard_key, self.namespace)
        
        operators = {
            "==": lambda x, y: x == y,
            "!=": lambda x, y: x != y,
            ">": lambda x, y: x > y,
            "<": lambda x, y: x < y,
            ">=": lambda x, y: x >= y,
            "<=": lambda x, y: x <= y,
            "in": lambda x, y: x in y,
            "not in": lambda x, y: x not in y,
            "contains": lambda x, y: y in x,
            "startswith": lambda x, y: str(x).startswith(str(y)),
            "endswith": lambda x, y: str(x).endswith(str(y))
        }
        
        if self.operator not in operators:
            raise ValueError(f"Invalid operator: {self.operator}")
        
        return operators[self.operator](value, self.expected_value)
    
    async def _execute_condition(self) -> bool:
        """รันฟังก์ชันตรวจสอบ"""
        try:
            if self.condition_func:
                if inspect.iscoroutinefunction(self.condition_func):
                    result = await self.condition_func(
                        *self.args, **self.kwargs
                    )
                else:
                    result = await asyncio.to_thread(
                        self.condition_func, *self.args, **self.kwargs
                    )
                return bool(result)
            
            elif self.blackboard_key:
                return self._check_blackboard()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in condition: {e}")
            self.stats['last_error'] = str(e)
            self.stats['error_checks'] += 1
            return False
    
    async def _tick(self) -> NodeStatus:
        start_time = datetime.now()
        
        try:
            result = await self._execute_condition()
            
            # อัพเดตสถิติ
            self.stats['total_checks'] += 1
            if result:
                self.stats['true_results'] += 1
            else:
                self.stats['false_results'] += 1
            
            self.stats['last_result'] = result
            
            return NodeStatus.SUCCESS if result else NodeStatus.FAILURE
            
        except Exception as e:
            self.logger.error(f"Error during condition check: {e}")
            self.stats['error_checks'] += 1
            self.stats['last_error'] = str(e)
            return NodeStatus.FAILURE

class WaitNode(ActionNode):
    """
    Node สำหรับรอตามเวลาที่กำหนด
    
    Properties:
        duration: ระยะเวลาที่จะรอ (วินาที)
        random_variance: ความแปรปรวนของเวลารอ (0-1)
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        duration: float = 1.0,
        random_variance: float = 0.0
    ):
        super().__init__(name, properties)
        self.base_duration = duration
        self.random_variance = max(0.0, min(1.0, random_variance))
    
    async def _tick(self) -> NodeStatus:
        if self.random_variance > 0:
            import random
            variance = self.base_duration * self.random_variance
            duration = random.uniform(
                self.base_duration - variance,
                self.base_duration + variance
            )
        else:
            duration = self.base_duration
        
        try:
            await asyncio.sleep(duration)
            return NodeStatus.SUCCESS
        except asyncio.CancelledError:
            return NodeStatus.FAILURE

class DebugLogNode(ActionNode):
    """
    Node สำหรับบันทึก log ข้อมูล
    
    Properties:
        message: ข้อความที่จะบันทึก
        level: ระดับของ log
        include_timestamp: เพิ่มเวลาในข้อความ
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        message: str = "",
        level: str = "INFO",
        include_timestamp: bool = True
    ):
        super().__init__(name, properties)
        self.message = message
        self.level = getattr(logging, level.upper())
        self.include_timestamp = include_timestamp
    
    async def _tick(self) -> NodeStatus:
        try:
            message = self.message
            if self.include_timestamp:
                message = f"[{datetime.now().isoformat()}] {message}"
            
            self.logger.log(self.level, message)
            return NodeStatus.SUCCESS
        except Exception as e:
            self.logger.error(f"Error logging message: {e}")
            return NodeStatus.FAILURE

class BlackboardSetNode(ActionNode):
    """
    Node สำหรับเซ็ตค่าใน blackboard
    
    Properties:
        key: คีย์ที่จะเซ็ต
        value: ค่าที่จะเซ็ต
        namespace: namespace ที่จะเซ็ต
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        key: str = None,
        value: Any = None,
        namespace: str = "default"
    ):
        super().__init__(name, properties)
        self.key = key or properties.get('key')
        self.value = value or properties.get('value')
        self.namespace = namespace
        
        if not self.key:
            raise ValueError("Blackboard key must be specified")
    
    async def _tick(self) -> NodeStatus:
        try:
            if not self.blackboard:
                return NodeStatus.FAILURE
            
            self.blackboard.set(
                self.key,
                self.value,
                self.namespace
            )
            return NodeStatus.SUCCESS
        except Exception as e:
            self.logger.error(f"Error setting blackboard value: {e}")
            return NodeStatus.FAILURE

class BlackboardDeleteNode(ActionNode):
    """
    Node สำหรับลบค่าใน blackboard
    
    Properties:
        key: คีย์ที่จะลบ
        namespace: namespace ที่จะลบ
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        key: str = None,
        namespace: str = "default"
    ):
        super().__init__(name, properties)
        self.key = key or properties.get('key')
        self.namespace = namespace
        
        if not self.key:
            raise ValueError("Blackboard key must be specified")
    
    async def _tick(self) -> NodeStatus:
        try:
            if not self.blackboard:
                return NodeStatus.FAILURE
            
            if self.blackboard.exists(self.key, self.namespace):
                self.blackboard.unset(self.key, self.namespace)
                return NodeStatus.SUCCESS
            return NodeStatus.FAILURE
        except Exception as e:
            self.logger.error(f"Error deleting blackboard value: {e}")
            return NodeStatus.FAILURE

class EventEmitNode(ActionNode):
    """
    Node สำหรับส่ง event
    
    Properties:
        event: event ที่จะส่ง
        data: ข้อมูลที่จะส่งไปกับ event
    """
    
    def __init__(
        self,
        name: str,
        properties: Optional[Dict[str, Any]] = None,
        event: Optional[NodeEvent] = None,
        data: Any = None
    ):
        super().__init__(name, properties)
        self.event = event
        self.data = data
    
    async def _tick(self) -> NodeStatus:
        try:
            if self.event:
                await self._emit_event(self.event)
            return NodeStatus.SUCCESS
        except Exception as e:
            self.logger.error(f"Error emitting event: {e}")
            return NodeStatus.FAILURE

class TimedConditionNode(ConditionNode):
    """
    Node สำหรับตรวจสอบเงื่อนไขในช่วงเวลาที่กำหนด
    
    Properties:
        duration: ระยะเวลาที่ต้องเป็นจริงต่อเนื่อง
        required_success_ratio: สัดส่วนที่ต้องเป็นจริง (0-1)
    """
    
    def __init__(
        self,
        name: str,
        condition_func: Optional[Callable] = None,
        properties: Optional[Dict[str, Any]] = None,
        duration: float = 1.0,
        required_success_ratio: float = 1.0,
        check_interval: float = 0.1
    ):
        super().__init__(name, condition_func, properties)
        self.duration = duration
        self.required_success_ratio = max(0.0, min(1.0, required_success_ratio))
        self.check_interval = check_interval
    
    async def _tick(self) -> NodeStatus:
        start_time = datetime.now()
        checks_count = 0
        success_count = 0
        
        try:
            while True:
                result = await self._execute_condition()
                checks_count += 1
                if result:
                    success_count += 1
                
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= self.duration:
                    success_ratio = success_count / checks_count
                    return (NodeStatus.SUCCESS 
                           if success_ratio >= self.required_success_ratio 
                           else NodeStatus.FAILURE)
                
                await asyncio.sleep(self.check_interval)
                
        except Exception as e:
            self.logger.error(f"Error in timed condition: {e}")
            return NodeStatus.FAILURE

class ThrottleNode(ActionNode):
    """
    Node สำหรับจำกัดความถี่ในการทำงาน
    
    Properties:
        min_interval: ระยะเวลาขั้นต่ำระหว่างการทำงาน
        max_executions: จำนวนครั้งสูงสุดที่อนุญาต
        window_size: ขนาดหน้าต่างเวลาสำหรับนับจำนวนครั้ง
    """
    
    def __init__(
        self,
        name: str,
        action_func: Optional[Callable] = None,
        properties: Optional[Dict[str, Any]] = None,
        min_interval: float = 0.0,
        max_executions: Optional[int] = None,
        window_size: Optional[float] = None
    ):
        super().__init__(name, action_func, properties)
        self.min_interval = min_interval
        self.max_executions = max_executions
        self.window_size = window_size
        
        self._last_execution: Optional[datetime] = None
        self._execution_times: List[datetime] = []
    
    def _can_execute(self) -> bool:
        """ตรวจสอบว่าสามารถทำงานได้หรือไม่"""
        now = datetime.now()
        
        # ตรวจสอบ interval
        if (self.min_interval > 0 and self._last_execution and
            (now - self._last_execution).total_seconds() < self.min_interval):
            return False
        
        # ตรวจสอบจำนวนครั้งใน window
        if self.max_executions and self.window_size:
            window_start = now - timedelta(seconds=self.window_size)
            self._execution_times = [
                t for t in self._execution_times if t >= window_start
            ]
            if len(self._execution_times) >= self.max_executions:
                return False
        
        return True
    
    async def _tick(self) -> NodeStatus:
        if not self._can_execute():
            return NodeStatus.FAILURE
        
        status = await super()._tick()
        
        if status != NodeStatus.RUNNING:
            now = datetime.now()
            self._last_execution = now
            self._execution_times.append(now)
        
        return status

class RetryUntilSuccessNode(ActionNode):
    """
    Node ที่พยายามทำงานจนกว่าจะสำเร็จ
    
    Properties:
        max_attempts: จำนวนครั้งสูงสุดที่จะลอง (-1 = ไม่จำกัด)
        delay_between_attempts: เวลารอระหว่างการลอง
        exponential_backoff: เพิ่มเวลารอแบบ exponential
    """
    
    def __init__(
        self,
        name: str,
        action_func: Optional[Callable] = None,
        properties: Optional[Dict[str, Any]] = None,
        max_attempts: int = -1,
        delay_between_attempts: float = 0.0,
        exponential_backoff: bool = False
    ):
        super().__init__(name, action_func, properties)
        self.max_attempts = max_attempts
        self.base_delay = delay_between_attempts
        self.exponential_backoff = exponential_backoff
        self._attempts = 0
    
    def _calculate_delay(self) -> float:
        """คำนวณเวลารอ"""
        if self.base_delay <= 0:
            return 0
        
        if self.exponential_backoff:
            return self.base_delay * (2 ** (self._attempts - 1))
        return self.base_delay
    
    async def _tick(self) -> NodeStatus:
        while self.max_attempts == -1 or self._attempts < self.max_attempts:
            self._attempts += 1
            
            status = await super()._tick()
            
            if status == NodeStatus.SUCCESS:
                self._attempts = 0
                return NodeStatus.SUCCESS
            
            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            
            delay = self._calculate_delay()
            if delay > 0:
                await asyncio.sleep(delay)
        
        self._attempts = 0
        return NodeStatus.FAILURE