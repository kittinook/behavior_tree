from typing import Dict, Any, Optional, Set, List
import threading
import logging
from dataclasses import dataclass
from datetime import datetime
import json

@dataclass
class BlackboardEntry:
    """ข้อมูลที่เก็บใน blackboard พร้อม metadata"""
    value: Any
    timestamp: datetime
    namespace: str
    access_count: int = 0
    last_modified_by: str = None

class BlackboardClient:
    """
    Client interface สำหรับเข้าถึง Blackboard
    ช่วยจำกัดการเข้าถึงข้อมูลให้อยู่ในขอบเขตที่กำหนด
    """
    def __init__(self, blackboard: 'Blackboard', namespace: str, client_id: str):
        self.blackboard = blackboard
        self.namespace = namespace
        self.client_id = client_id
        self._subscriptions: Set[str] = set()
    
    def get(self, key: str) -> Any:
        """ดึงข้อมูลจาก namespace ที่กำหนด"""
        return self.blackboard.get(key, self.namespace)
    
    def set(self, key: str, value: Any) -> None:
        """เซ็ตค่าใน namespace ที่กำหนด"""
        self.blackboard.set(key, value, self.namespace, self.client_id)
    
    def unset(self, key: str) -> None:
        """ลบค่าใน namespace ที่กำหนด"""
        self.blackboard.unset(key, self.namespace)
    
    def exists(self, key: str) -> bool:
        """ตรวจสอบว่ามีค่าอยู่หรือไม่"""
        return self.blackboard.exists(key, self.namespace)
    
    def subscribe(self, key: str, callback: callable) -> None:
        """ลงทะเบียนรับการแจ้งเตือนเมื่อค่าเปลี่ยน"""
        self.blackboard.subscribe(key, callback, self.namespace)
        self._subscriptions.add(key)
    
    def unsubscribe_all(self) -> None:
        """ยกเลิกการรับการแจ้งเตือนทั้งหมด"""
        for key in self._subscriptions:
            self.blackboard.unsubscribe(key, None, self.namespace)
        self._subscriptions.clear()

class Blackboard:
    """
    ระบบ Blackboard สำหรับแชร์ข้อมูลระหว่าง node
    รองรับ namespace และ thread-safe access
    """
    
    def __init__(self):
        self._data: Dict[str, Dict[str, BlackboardEntry]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._subscribers: Dict[str, Dict[str, List[callable]]] = {}
        self._activity_log: List[Dict] = []
        self.logger = logging.getLogger("Blackboard")
        
        # สร้าง default namespace
        self.create_namespace("default")
    
    def create_namespace(self, namespace: str) -> None:
        """สร้าง namespace ใหม่"""
        if namespace not in self._data:
            self._data[namespace] = {}
            self._locks[namespace] = threading.Lock()
            self._subscribers[namespace] = {}
            self.logger.debug(f"Created namespace: {namespace}")
    
    def get_client(self, namespace: str, client_id: str) -> BlackboardClient:
        """สร้าง client interface สำหรับเข้าถึง namespace ที่กำหนด"""
        if namespace not in self._data:
            self.create_namespace(namespace)
        return BlackboardClient(self, namespace, client_id)
    
    def set(self, key: str, value: Any, namespace: str = "default", 
            client_id: str = None) -> None:
        """เซ็ตค่าใน blackboard"""
        if namespace not in self._data:
            self.create_namespace(namespace)
        
        with self._locks[namespace]:
            entry = BlackboardEntry(
                value=value,
                timestamp=datetime.now(),
                namespace=namespace,
                last_modified_by=client_id
            )
            
            old_value = None
            if key in self._data[namespace]:
                old_value = self._data[namespace][key].value
            
            self._data[namespace][key] = entry
            
            # บันทึก activity
            self._activity_log.append({
                'timestamp': entry.timestamp,
                'action': 'set',
                'namespace': namespace,
                'key': key,
                'old_value': old_value,
                'new_value': value,
                'client_id': client_id
            })
            
            # แจ้ง subscribers
            if key in self._subscribers[namespace]:
                for callback in self._subscribers[namespace][key]:
                    try:
                        callback(key, value, old_value)
                    except Exception as e:
                        self.logger.error(f"Error in subscriber callback: {e}")
    
    def get(self, key: str, namespace: str = "default") -> Any:
        """ดึงค่าจาก blackboard"""
        if namespace not in self._data:
            raise KeyError(f"Namespace {namespace} not found")
        
        with self._locks[namespace]:
            if key not in self._data[namespace]:
                return None
            
            entry = self._data[namespace][key]
            entry.access_count += 1
            return entry.value
    
    def exists(self, key: str, namespace: str = "default") -> bool:
        """ตรวจสอบว่ามีค่าอยู่หรือไม่"""
        if namespace not in self._data:
            return False
        
        with self._locks[namespace]:
            return key in self._data[namespace]
    
    def unset(self, key: str, namespace: str = "default") -> None:
        """ลบค่าออกจาก blackboard"""
        if namespace in self._data:
            with self._locks[namespace]:
                if key in self._data[namespace]:
                    del self._data[namespace][key]
                    
                    # บันทึก activity
                    self._activity_log.append({
                        'timestamp': datetime.now(),
                        'action': 'unset',
                        'namespace': namespace,
                        'key': key
                    })
    
    def clear_namespace(self, namespace: str) -> None:
        """ล้างข้อมูลทั้งหมดใน namespace"""
        if namespace in self._data:
            with self._locks[namespace]:
                self._data[namespace].clear()
                self._subscribers[namespace].clear()
                
                # บันทึก activity
                self._activity_log.append({
                    'timestamp': datetime.now(),
                    'action': 'clear_namespace',
                    'namespace': namespace
                })
    
    def subscribe(self, key: str, callback: callable, 
                 namespace: str = "default") -> None:
        """ลงทะเบียนรับการแจ้งเตือนเมื่อค่าเปลี่ยน"""
        if namespace not in self._subscribers:
            self._subscribers[namespace] = {}
        
        if key not in self._subscribers[namespace]:
            self._subscribers[namespace][key] = []
        
        self._subscribers[namespace][key].append(callback)
    
    def unsubscribe(self, key: str, callback: callable, 
                    namespace: str = "default") -> None:
        """ยกเลิกการรับการแจ้งเตือน"""
        if (namespace in self._subscribers and 
            key in self._subscribers[namespace]):
            if callback is None:
                self._subscribers[namespace][key].clear()
            else:
                self._subscribers[namespace][key].remove(callback)
    
    def save_state(self, file_path: str) -> None:
        """บันทึกสถานะทั้งหมดลงไฟล์"""
        state = {
            namespace: {
                key: {
                    'value': entry.value,
                    'timestamp': entry.timestamp.isoformat(),
                    'access_count': entry.access_count,
                    'last_modified_by': entry.last_modified_by
                }
                for key, entry in namespace_data.items()
            }
            for namespace, namespace_data in self._data.items()
        }
        
        with open(file_path, 'w') as f:
            json.dump(state, f, indent=2)
    
    def load_state(self, file_path: str) -> None:
        """โหลดสถานะจากไฟล์"""
        with open(file_path, 'r') as f:
            state = json.load(f)
        
        for namespace, namespace_data in state.items():
            self.create_namespace(namespace)
            with self._locks[namespace]:
                for key, entry_data in namespace_data.items():
                    self._data[namespace][key] = BlackboardEntry(
                        value=entry_data['value'],
                        timestamp=datetime.fromisoformat(entry_data['timestamp']),
                        namespace=namespace,
                        access_count=entry_data['access_count'],
                        last_modified_by=entry_data['last_modified_by']
                    )
    
    def get_activity_log(self) -> List[Dict]:
        """ดึงประวัติการเปลี่ยนแปลงทั้งหมด"""
        return self._activity_log.copy()
