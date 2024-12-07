from typing import Dict, Any, Optional, List, Type, Union
import yaml
import json
import logging
from pathlib import Path
import jsonschema
from dataclasses import dataclass
from enum import Enum
import importlib.util
import sys

from ..core.node import NodeStatus
from ..nodes.composites import ParallelPolicy, MemoryPolicy

class ConfigFormat(Enum):
    """รูปแบบไฟล์ configuration ที่รองรับ"""
    YAML = "yaml"
    JSON = "json"
    PYTHON = "py"

@dataclass
class NodeConfig:
    """โครงสร้างข้อมูล configuration ของ node"""
    name: str
    type: str
    properties: Dict[str, Any] = None
    children: List['NodeConfig'] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """แปลงเป็น dictionary"""
        result = {
            'name': self.name,
            'type': self.type
        }
        if self.properties:
            result['properties'] = self.properties
        if self.children:
            result['children'] = [
                child.to_dict() for child in self.children
            ]
        return result

class ConfigValidationError(Exception):
    """ข้อผิดพลาดจากการตรวจสอบ configuration"""
    pass

class ConfigLoader:
    """
    คลาสสำหรับโหลดและตรวจสอบ configuration ของ Behavior Tree
    รองรับการโหลดจาก YAML, JSON, และ Python module
    """
    
    # Schema สำหรับตรวจสอบ configuration
    SCHEMA = {
        "type": "object",
        "required": ["name", "type"],
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string"},
            "properties": {
                "type": "object",
                "additionalProperties": True
            },
            "children": {
                "type": "array",
                "items": {"$ref": "#"}
            }
        }
    }
    
    def __init__(self, custom_validators: Dict[str, callable] = None):
        self.logger = logging.getLogger("ConfigLoader")
        self.custom_validators = custom_validators or {}
        
        # เก็บ node types ที่รองรับ
        self._node_types = self._collect_node_types()
        
        # สร้าง validator
        self.validator = jsonschema.validators.validator_for(self.SCHEMA)(
            self.SCHEMA
        )
    
    def _collect_node_types(self) -> Dict[str, Type]:
        """รวบรวม node types ทั้งหมดที่รองรับ"""
        from ..nodes import composites, decorators, leaves
        
        node_types = {}
        
        # เพิ่ม built-in nodes
        modules = [composites, decorators, leaves]
        for module in modules:
            for name, obj in module.__dict__.items():
                if (isinstance(obj, type) and 
                    name.endswith('Node')):
                    node_types[name] = obj
        
        return node_types
    
    def load_file(
        self,
        file_path: Union[str, Path],
        format: Optional[ConfigFormat] = None
    ) -> NodeConfig:
        """
        โหลด configuration จากไฟล์
        
        Args:
            file_path: path ของไฟล์
            format: รูปแบบไฟล์ (ถ้าไม่ระบุจะใช้นามสกุลไฟล์)
            
        Returns:
            NodeConfig: configuration ที่โหลด
            
        Raises:
            ConfigValidationError: ถ้า configuration ไม่ถูกต้อง
        """
        path = Path(file_path)
        
        if not format:
            format = self._detect_format(path)
        
        try:
            if format == ConfigFormat.YAML:
                with path.open('r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            elif format == ConfigFormat.JSON:
                with path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            elif format == ConfigFormat.PYTHON:
                data = self._load_python_module(path)
            else:
                raise ValueError(f"Unsupported format: {format}")
            
            # ตรวจสอบและแปลงเป็น NodeConfig
            return self.validate_and_parse(data)
            
        except Exception as e:
            raise ConfigValidationError(
                f"Error loading configuration from {path}: {e}"
            )
    
    def _detect_format(self, path: Path) -> ConfigFormat:
        """ตรวจสอบรูปแบบไฟล์จากนามสกุล"""
        suffix = path.suffix.lower()
        if suffix in {'.yml', '.yaml'}:
            return ConfigFormat.YAML
        elif suffix == '.json':
            return ConfigFormat.JSON
        elif suffix == '.py':
            return ConfigFormat.PYTHON
        else:
            raise ValueError(f"Cannot detect format for: {path}")
    
    def _load_python_module(self, path: Path) -> Dict[str, Any]:
        """โหลด configuration จาก Python module"""
        try:
            # เพิ่ม directory ของไฟล์เข้าไปใน Python path
            sys.path.insert(0, str(path.parent))
            
            # โหลด module
            spec = importlib.util.spec_from_file_location(
                path.stem, str(path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # ดึง configuration
            if not hasattr(module, 'TREE_CONFIG'):
                raise ConfigValidationError(
                    "Python module must define TREE_CONFIG"
                )
            
            return module.TREE_CONFIG
            
        finally:
            # ลบ path ที่เพิ่มเข้าไป
            sys.path.pop(0)
    
    def validate_and_parse(self, data: Dict[str, Any]) -> NodeConfig:
        """
        ตรวจสอบและแปลง dictionary เป็น NodeConfig
        
        Args:
            data: dictionary ที่จะตรวจสอบ
            
        Returns:
            NodeConfig: configuration ที่ตรวจสอบแล้ว
            
        Raises:
            ConfigValidationError: ถ้า configuration ไม่ถูกต้อง
        """
        # ตรวจสอบโครงสร้างพื้นฐาน
        try:
            self.validator.validate(data)
        except jsonschema.exceptions.ValidationError as e:
            raise ConfigValidationError(f"Invalid configuration: {e}")
        
        # ตรวจสอบ node type
        node_type = data['type']
        if node_type not in self._node_types:
            raise ConfigValidationError(
                f"Unknown node type: {node_type}"
            )
        
        # ตรวจสอบ properties ของ node
        self._validate_node_properties(data)
        
        # แปลงเป็น NodeConfig
        return self._parse_node_config(data)
    
    def _validate_node_properties(self, data: Dict[str, Any]) -> None:
        """ตรวจสอบ properties ของ node"""
        node_type = data['type']
        properties = data.get('properties', {})
        
        # ตรวจสอบ custom validator ถ้ามี
        if node_type in self.custom_validators:
            try:
                self.custom_validators[node_type](properties)
            except Exception as e:
                raise ConfigValidationError(
                    f"Invalid properties for {node_type}: {e}"
                )
        
        # ตรวจสอบ enum values
        if 'parallel_policy' in properties:
            try:
                ParallelPolicy(properties['parallel_policy'])
            except ValueError:
                raise ConfigValidationError(
                    f"Invalid parallel_policy: {properties['parallel_policy']}"
                )
        
        if 'memory_policy' in properties:
            try:
                MemoryPolicy(properties['memory_policy'])
            except ValueError:
                raise ConfigValidationError(
                    f"Invalid memory_policy: {properties['memory_policy']}"
                )
    
    def _parse_node_config(self, data: Dict[str, Any]) -> NodeConfig:
        """แปลง dictionary เป็น NodeConfig"""
        children = None
        if 'children' in data:
            children = [
                self._parse_node_config(child)
                for child in data['children']
            ]
        
        return NodeConfig(
            name=data['name'],
            type=data['type'],
            properties=data.get('properties'),
            children=children
        )
    
    def save_config(
        self,
        config: NodeConfig,
        file_path: Union[str, Path],
        format: Optional[ConfigFormat] = None
    ) -> None:
        """
        บันทึก configuration ลงไฟล์
        
        Args:
            config: configuration ที่จะบันทึก
            file_path: path ของไฟล์
            format: รูปแบบไฟล์ (ถ้าไม่ระบุจะใช้นามสกุลไฟล์)
        """
        path = Path(file_path)
        
        if not format:
            format = self._detect_format(path)
        
        # แปลงเป็น dictionary
        data = config.to_dict()
        
        try:
            if format == ConfigFormat.YAML:
                with path.open('w', encoding='utf-8') as f:
                    yaml.dump(data, f, default_flow_style=False)
            elif format == ConfigFormat.JSON:
                with path.open('w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            elif format == ConfigFormat.PYTHON:
                with path.open('w', encoding='utf-8') as f:
                    f.write("TREE_CONFIG = ")
                    f.write(repr(data))
            else:
                raise ValueError(f"Unsupported format: {format}")
                
        except Exception as e:
            self.logger.error(f"Error saving configuration: {e}")
            raise

class ConfigMerger:
    """
    คลาสสำหรับรวม configuration หลายไฟล์เข้าด้วยกัน
    รองรับการ override และ extend configuration
    """
    
    def __init__(self):
        self.logger = logging.getLogger("ConfigMerger")
    
    def merge_configs(
        self,
        base: NodeConfig,
        override: NodeConfig
    ) -> NodeConfig:
        """
        รวม configuration สองอัน
        override จะทับค่าใน base
        """
        # สร้าง config ใหม่
        merged = NodeConfig(
            name=override.name or base.name,
            type=override.type or base.type
        )
        
        # รวม properties
        if base.properties or override.properties:
            merged.properties = {
                **(base.properties or {}),
                **(override.properties or {})
            }
        
        # รวม children
        if base.children or override.children:
            merged.children = self._merge_children(
                base.children or [],
                override.children or []
            )
        
        return merged
    
    def _merge_children(
        self,
        base_children: List[NodeConfig],
        override_children: List[NodeConfig]
    ) -> List[NodeConfig]:
        """รวม children nodes"""
        result = base_children.copy()
        
        # สร้าง map ของ children ตามชื่อ
        base_map = {child.name: i for i, child in enumerate(base_children)}
        
        for override_child in override_children:
            if override_child.name in base_map:
                # อัพเดต existing child
                index = base_map[override_child.name]
                result[index] = self.merge_configs(
                    result[index],
                    override_child
                )
            else:
                # เพิ่ม child ใหม่
                result.append(override_child)
        
        return result
