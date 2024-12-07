from typing import Dict, Any, Optional, List, Set
import graphviz
from datetime import datetime
import json
import asyncio
import logging
from pathlib import Path
import math
from enum import Enum
from dataclasses import dataclass
import websockets
import threading
from queue import Queue

from ..core.node import BehaviorNode, NodeStatus, NodeEvent, ParentNode

class VisualizationFormat(Enum):
    """รูปแบบการแสดงผลที่รองรับ"""
    GRAPHVIZ = "graphviz"
    SVG = "svg"
    ASCII = "ascii"
    HTML = "html"
    MERMAID = "mermaid"

@dataclass
class NodeVisualData:
    """ข้อมูลการแสดงผลของ node"""
    id: str
    name: str
    type: str
    status: NodeStatus
    depth: int
    parent_id: Optional[str] = None
    children: List[str] = None
    properties: Dict[str, Any] = None
    metadata: Dict[str, Any] = None

class TreeVisualizer:
    """
    คลาสหลักสำหรับแสดงผล Behavior Tree
    รองรับหลายรูปแบบการแสดงผลและ real-time monitoring
    """
    
    def __init__(
        self,
        update_interval: float = 0.1,
        max_history: int = 1000,
        enable_websocket: bool = False,
        websocket_port: int = 8765
    ):
        self.update_interval = update_interval
        self.max_history = max_history
        self.enable_websocket = enable_websocket
        self.websocket_port = websocket_port
        
        # สำหรับเก็บประวัติการเปลี่ยนแปลง
        self.history: List[Dict[str, Any]] = []
        
        # สำหรับ real-time monitoring
        self.monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._update_queue: Queue = Queue()
        
        # สำหรับ WebSocket
        self._websocket_server = None
        self._connected_clients: Set[websockets.WebSocketServerProtocol] = set()
        
        # ตั้งค่าสีและสไตล์
        self.style = {
            NodeStatus.SUCCESS: {"color": "#28a745", "style": "filled"},
            NodeStatus.FAILURE: {"color": "#dc3545", "style": "filled"},
            NodeStatus.RUNNING: {"color": "#ffc107", "style": "filled"},
            NodeStatus.INVALID: {"color": "#6c757d", "style": "filled"},
            NodeStatus.SKIPPED: {"color": "#17a2b8", "style": "filled"},
            NodeStatus.ERROR: {"color": "#dc3545", "style": "filled,bold"}
        }
        
        self.logger = logging.getLogger("TreeVisualizer")
    
    async def start_monitoring(self, tree_manager) -> None:
        """เริ่มการ monitor tree แบบ real-time"""
        if self.monitoring:
            return
            
        self.monitoring = True
        
        if self.enable_websocket:
            await self._start_websocket_server()
        
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(tree_manager)
        )
    
    async def stop_monitoring(self) -> None:
        """หยุดการ monitor"""
        self.monitoring = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        if self._websocket_server:
            self._websocket_server.close()
            await self._websocket_server.wait_closed()
    
    async def _monitor_loop(self, tree_manager) -> None:
        """loop สำหรับ monitor การเปลี่ยนแปลงของ tree"""
        try:
            while self.monitoring:
                if tree_manager.root:
                    # สร้างข้อมูลสถานะปัจจุบัน
                    visual_data = self._create_visual_data(tree_manager.root)
                    timestamp = datetime.now().isoformat()
                    
                    update = {
                        'timestamp': timestamp,
                        'tree_data': visual_data,
                        'stats': tree_manager.get_stats()
                    }
                    
                    # เก็บประวัติ
                    self.history.append(update)
                    if len(self.history) > self.max_history:
                        self.history.pop(0)
                    
                    # ส่งข้อมูลไปยัง WebSocket clients
                    if self._connected_clients:
                        message = json.dumps(update)
                        await self._broadcast_update(message)
                    
                    # เก็บข้อมูลสำหรับการแสดงผลอื่นๆ
                    self._update_queue.put(update)
                
                await asyncio.sleep(self.update_interval)
                
        except asyncio.CancelledError:
            self.logger.info("Monitoring stopped")
        except Exception as e:
            self.logger.error(f"Error in monitor loop: {e}")
    
    def _create_visual_data(self, node: BehaviorNode, depth: int = 0) -> Dict:
        """สร้างข้อมูลสำหรับแสดงผล"""
        data = NodeVisualData(
            id=str(id(node)),
            name=node.name,
            type=node.__class__.__name__,
            status=node.status,
            depth=depth,
            parent_id=str(id(node.parent)) if node.parent else None,
            children=[],
            properties=node.properties,
            metadata={
                'path': node.get_path(),
                'stats': getattr(node, 'stats', {})
            }
        )
        
        if isinstance(node, ParentNode):
            for child in node.children:
                child_data = self._create_visual_data(child, depth + 1)
                data.children.append(child_data)
        
        return data.__dict__
    
    async def _start_websocket_server(self) -> None:
        """เริ่ม WebSocket server"""
        async def handler(websocket, path):
            self._connected_clients.add(websocket)
            try:
                async for message in websocket:
                    # รับคำสั่งจาก client ถ้าจำเป็น
                    pass
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                self._connected_clients.remove(websocket)
        
        self._websocket_server = await websockets.serve(
            handler, 'localhost', self.websocket_port
        )
    
    async def _broadcast_update(self, message: str) -> None:
        """ส่งข้อมูลไปยัง WebSocket clients ทั้งหมด"""
        if not self._connected_clients:
            return
        
        await asyncio.gather(*[
            client.send(message)
            for client in self._connected_clients
        ])
    
    def create_graphviz(
        self,
        root: BehaviorNode,
        filename: Optional[str] = None,
        format: str = "png"
    ) -> graphviz.Digraph:
        """สร้างแผนภาพด้วย Graphviz"""
        dot = graphviz.Digraph(comment='Behavior Tree')
        dot.attr(rankdir='TB')
        
        def add_node(node: BehaviorNode):
            node_id = str(id(node))
            style = self.style.get(node.status, {})
            
            # สร้างข้อความแสดงข้อมูล
            label = f"{node.name}\n({node.__class__.__name__})"
            if hasattr(node, 'stats'):
                stats = node.stats
                if 'total_runs' in stats:
                    label += f"\nRuns: {stats['total_runs']}"
                if 'success_count' in stats:
                    label += f"\nSuccess: {stats['success_count']}"
            
            dot.node(
                node_id,
                label,
                style=style.get('style', ''),
                fillcolor=style.get('color', '#ffffff'),
                fontsize='10'
            )
            
            if isinstance(node, ParentNode):
                for child in node.children:
                    child_id = str(id(child))
                    add_node(child)
                    dot.edge(node_id, child_id)
        
        add_node(root)
        
        if filename:
            dot.render(filename, format=format, cleanup=True)
        
        return dot
    
    def create_ascii(self, root: BehaviorNode) -> str:
        """สร้างแผนภาพแบบ ASCII"""
        output = []
        
        def add_node(node: BehaviorNode, prefix: str = "", is_last: bool = True):
            # สร้างเส้นเชื่อม
            connector = "└── " if is_last else "├── "
            output.append(f"{prefix}{connector}{node.name} ({node.status.name})")
            
            if isinstance(node, ParentNode):
                for i, child in enumerate(node.children):
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    add_node(child, new_prefix, i == len(node.children) - 1)
        
        add_node(root)
        return "\n".join(output)
    
    def create_mermaid(self, root: BehaviorNode) -> str:
        """สร้างแผนภาพแบบ Mermaid"""
        output = ["graph TD"]
        
        def add_node(node: BehaviorNode):
            node_id = str(id(node))
            style = self.style.get(node.status, {})
            
            # กำหนดสไตล์ใน Mermaid
            output.append(
                f"{node_id}[{node.name}<br>({node.status.name})]"
                f":::status{node.status.name}"
            )
            
            if isinstance(node, ParentNode):
                for child in node.children:
                    child_id = str(id(child))
                    add_node(child)
                    output.append(f"{node_id} --> {child_id}")
        
        add_node(root)
        
        # เพิ่ม style classes
        output.append("classDef statusSUCCESS fill:#28a745")
        output.append("classDef statusFAILURE fill:#dc3545")
        output.append("classDef statusRUNNING fill:#ffc107")
        output.append("classDef statusINVALID fill:#6c757d")
        
        return "\n".join(output)
    
    def create_html(self, root: BehaviorNode) -> str:
        """สร้าง HTML สำหรับแสดงผลแบบ interactive"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Behavior Tree Visualization</title>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/vis-network.min.js"></script>
            <style>
                #tree-container {{
                    width: 100%;
                    height: 600px;
                    border: 1px solid lightgray;
                }}
                .node-info {{
                    padding: 10px;
                    border: 1px solid #ddd;
                    margin-top: 10px;
                }}
            </style>
        </head>
        <body>
            <div id="tree-container"></div>
            <div id="node-info" class="node-info"></div>
            
            <script>
                const nodes = new vis.DataSet({json.dumps(self._create_nodes_data(root))});
                const edges = new vis.DataSet({json.dumps(self._create_edges_data(root))});
                
                const container = document.getElementById('tree-container');
                const data = {{ nodes, edges }};
                const options = {{
                    layout: {{
                        hierarchical: {{
                            direction: 'UD',
                            sortMethod: 'directed'
                        }}
                    }},
                    nodes: {{
                        shape: 'box',
                        font: {{ multi: 'html' }}
                    }}
                }};
                
                const network = new vis.Network(container, data, options);
                
                network.on('click', function(params) {{
                    if (params.nodes.length > 0) {{
                        const nodeId = params.nodes[0];
                        const node = nodes.get(nodeId);
                        document.getElementById('node-info').innerHTML = `
                            <h3>${{node.label}}</h3>
                            <p>Status: ${{node.status}}</p>
                            <p>Type: ${{node.type}}</p>
                            ${{node.metadata ? `<pre>${{JSON.stringify(node.metadata, null, 2)}}</pre>` : ''}}
                        `;
                    }}
                }});
                
                // WebSocket connection for real-time updates
                const ws = new WebSocket('ws://localhost:{self.websocket_port}');
                ws.onmessage = function(event) {{
                    const update = JSON.parse(event.data);
                    // Update nodes and edges with new data
                    updateVisualization(update.tree_data);
                }};
                
                function updateVisualization(treeData) {{
                    // Update nodes and edges based on new data
                    // ...
                }}
            </script>
        </body>
        </html>
        """
        return html
    
    def _create_nodes_data(self, root: BehaviorNode) -> List[Dict]:
        """สร้างข้อมูล nodes สำหรับ vis.js"""
        nodes = []
        
        def add_node(node: BehaviorNode):
            style = self.style.get(node.status, {})
            nodes.append({
                'id': str(id(node)),
                'label': f"{node.name}\n({node.__class__.__name__})",
                'status': node.status.name,
                'type': node.__class__.__name__,
                'color': style.get('color', '#ffffff'),
                'metadata': {
                    'path': node.get_path(),
                    'stats': getattr(node, 'stats', {})
                }
            })
            
            if isinstance(node, ParentNode):
                for child in node.children:
                    add_node(child)
        
        add_node(root)
        return nodes
    
    def _create_edges_data(self, root: BehaviorNode) -> List[Dict]:
        """สร้างข้อมูล edges สำหรับ vis.js"""
        edges = []
        
        def add_edges(node: BehaviorNode):
            if isinstance(node, ParentNode):
                node_id = str(id(node))
                for child in node.children:
                    child_id = str(id(child))
                    edges.append({
                        'from': node_id,
                        'to': child_id
                    })
                    add_edges(child)
        
        add_edges(root)
        return edges
    
    def export_svg(self, root: BehaviorNode) -> str:
        """ส่งออกเป็น SVG string"""
        dot = self.create_graphviz(root)
        return dot.pipe(format='svg').decode('utf-8')
    
    def save_animation(
        self,
        filename: str,
        format: str = 'gif',
        duration: int = 1000
    ) -> None:
        """สร้างภาพเคลื่อนไหวจากประวัติการเปลี่ยนแปลง"""
        try:
            import imageio
            import tempfile
            from PIL import Image
            
            frames = []
            temp_dir = Path(tempfile.mkdtemp())
            
            for i, snapshot in enumerate(self.history):
                # สร้างภาพแต่ละเฟรม
                tree_data = snapshot['tree_data']
                dot = graphviz.Digraph()
                self._build_graph_from_data(dot, tree_data)
                
                temp_file = temp_dir / f"frame_{i:04d}.png"
                dot.render(str(temp_file), format='png', cleanup=True)
                
                # อ่านภาพและเพิ่มลงในเฟรม
                frame = Image.open(f"{temp_file}.png")
                frames.append(frame)
            
            # บันทึกเป็น GIF
            if format.lower() == 'gif':
                imageio.mimsave(
                    filename,
                    frames,
                    duration=duration/1000,
                    loop=0
                )
            else:
                raise ValueError(f"Unsupported animation format: {format}")
            
        except ImportError as e:
            self.logger.error(
                f"Required package not found for animation: {e}"
            )
        finally:
            # ลบไฟล์ชั่วคราว
            import shutil
            shutil.rmtree(temp_dir)
    
    def _build_graph_from_data(
        self,
        dot: graphviz.Digraph,
        data: Dict
    ) -> None:
        """สร้างกราฟจากข้อมูล node"""
        dot.attr(rankdir='TB')
        
        def add_node_from_data(node_data: Dict):
            style = self.style.get(
                NodeStatus[node_data['status']], {}
            )
            
            dot.node(
                node_data['id'],
                f"{node_data['name']}\n({node_data['type']})",
                style=style.get('style', ''),
                fillcolor=style.get('color', '#ffffff')
            )
            
            if node_data.get('children'):
                for child in node_data['children']:
                    add_node_from_data(child)
                    dot.edge(node_data['id'], child['id'])
        
        add_node_from_data(data)
    
    def create_sequence_diagram(self, root: BehaviorNode) -> str:
        """สร้าง sequence diagram ในรูปแบบ Mermaid"""
        output = ["sequenceDiagram"]
        
        # สร้างรายการ participants
        participants = set()
        
        def collect_participants(node: BehaviorNode):
            participants.add(node.name)
            if isinstance(node, ParentNode):
                for child in node.children:
                    collect_participants(child)
        
        collect_participants(root)
        
        # เพิ่ม participants
        for participant in sorted(participants):
            output.append(f"participant {participant}")
        
        # สร้างลำดับการทำงาน
        def add_sequence(node: BehaviorNode, parent: Optional[str] = None):
            if parent:
                output.append(
                    f"{parent}->>+{node.name}: tick"
                )
                output.append(
                    f"{node.name}-->>-{parent}: {node.status.name}"
                )
            
            if isinstance(node, ParentNode):
                for child in node.children:
                    add_sequence(child, node.name)
        
        add_sequence(root)
        return "\n".join(output)
    
    async def serve_visualization(
        self,
        host: str = 'localhost',
        port: int = 8080
    ) -> None:
        """เปิด web server สำหรับแสดงผลแบบ interactive"""
        try:
            from aiohttp import web
            
            app = web.Application()
            
            async def index_handler(request):
                if not hasattr(self, '_current_root'):
                    return web.Response(
                        text="No tree data available",
                        content_type='text/html'
                    )
                return web.Response(
                    text=self.create_html(self._current_root),
                    content_type='text/html'
                )
            
            async def ws_handler(request):
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                
                self._connected_clients.add(ws)
                try:
                    async for msg in ws:
                        if msg.type == web.WSMsgType.TEXT:
                            # Handle client messages if needed
                            pass
                finally:
                    self._connected_clients.remove(ws)
                
                return ws
            
            app.router.add_get('/', index_handler)
            app.router.add_get('/ws', ws_handler)
            
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            
            self.logger.info(
                f"Visualization server running at http://{host}:{port}"
            )
            
            # Keep the server running
            while True:
                await asyncio.sleep(3600)
                
        except ImportError:
            self.logger.error(
                "aiohttp package required for web visualization"
            )
        except Exception as e:
            self.logger.error(f"Error in visualization server: {e}")
    
    def generate_metrics_report(self) -> Dict[str, Any]:
        """สร้างรายงานสถิติการทำงานของ tree"""
        if not self.history:
            return {}
        
        total_nodes = 0
        status_counts = {status: 0 for status in NodeStatus}
        execution_times = []
        
        for snapshot in self.history:
            tree_data = snapshot['tree_data']
            stats = snapshot['stats']
            
            def process_node(node_data: Dict):
                nonlocal total_nodes
                total_nodes += 1
                status = NodeStatus[node_data['status']]
                status_counts[status] += 1
                
                if node_data.get('metadata', {}).get('stats'):
                    node_stats = node_data['metadata']['stats']
                    if 'average_duration' in node_stats:
                        execution_times.append(
                            node_stats['average_duration']
                        )
                
                if node_data.get('children'):
                    for child in node_data['children']:
                        process_node(child)
            
            process_node(tree_data)
        
        return {
            'total_snapshots': len(self.history),
            'total_nodes': total_nodes,
            'status_distribution': {
                status.name: count
                for status, count in status_counts.items()
            },
            'average_execution_time': (
                sum(execution_times) / len(execution_times)
                if execution_times else 0
            ),
            'max_execution_time': max(execution_times)
                if execution_times else 0,
            'min_execution_time': min(execution_times)
                if execution_times else 0
        }

class ConsoleVisualizer:
    """คลาสสำหรับแสดงผลใน console แบบ real-time"""
    
    def __init__(self, refresh_rate: float = 0.5):
        self.refresh_rate = refresh_rate
        self._stop_event = threading.Event()
    
    def start(self, tree_manager) -> None:
        """เริ่มแสดงผลแบบ real-time"""
        def update_loop():
            try:
                import os
                while not self._stop_event.is_set():
                    # Clear screen
                    os.system('cls' if os.name == 'nt' else 'clear')
                    
                    # แสดงสถานะปัจจุบัน
                    if tree_manager.root:
                        print(self._create_tree_view(tree_manager.root))
                        print("\nStats:")
                        stats = tree_manager.get_stats()
                        for key, value in stats.items():
                            print(f"{key}: {value}")
                    
                    time.sleep(self.refresh_rate)
            except KeyboardInterrupt:
                self.stop()
        
        threading.Thread(target=update_loop, daemon=True).start()
    
    def stop(self) -> None:
        """หยุดแสดงผล"""
        self._stop_event.set()
    
    def _create_tree_view(self, node: BehaviorNode, prefix: str = "") -> str:
        """สร้าง tree view แบบ text"""
        output = []
        
        # สร้างสีสำหรับ status
        colors = {
            NodeStatus.SUCCESS: '\033[92m',  # green
            NodeStatus.FAILURE: '\033[91m',  # red
            NodeStatus.RUNNING: '\033[93m',  # yellow
            NodeStatus.INVALID: '\033[90m',  # gray
            NodeStatus.ERROR: '\033[91m\033[1m',  # bold red
        }
        RESET = '\033[0m'
        
        # สร้างบรรทัดสำหรับ node นี้
        status_color = colors.get(node.status, '')
        node_line = (f"{prefix}├── {status_color}{node.name} "
                    f"({node.status.name}){RESET}")
        output.append(node_line)
        
        # เพิ่มสถิติถ้ามี
        if hasattr(node, 'stats'):
            stats = getattr(node, 'stats')
            if stats:
                stats_lines = [
                    f"{prefix}│   ├── {key}: {value}"
                    for key, value in stats.items()
                ]
                output.extend(stats_lines)
        
        # เพิ่ม children
        if isinstance(node, ParentNode):
            for i, child in enumerate(node.children):
                is_last = i == len(node.children) - 1
                new_prefix = f"{prefix}│   " if not is_last else f"{prefix}    "
                child_view = self._create_tree_view(child, new_prefix)
                output.append(child_view)
        
        return "\n".join(output)