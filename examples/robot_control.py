import asyncio
import sys
import logging
from datetime import datetime
from pathlib import Path
import random

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from behavior_tree import (
    BehaviorTreeManager,
    SequenceNode,
    SelectorNode,
    ParallelNode,
    ActionNode,
    ConditionNode,
    BlackboardSetNode,
    ParallelPolicy,
    Blackboard,
    RetryNode,
    TimeoutNode
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class RobotController:
    """Robot controller simulation"""
    
    def __init__(self):
        self.position = (0, 0)
        self.battery = 100
        self.has_target = False
        self.carrying_object = False
        self.target_position = None
        self.logger = logging.getLogger("RobotController")
        
        # Statistics
        self.stats = {
            'total_distance': 0.0,
            'objects_picked': 0,
            'battery_charges': 0,
            'start_time': datetime.now()
        }
    
    async def check_battery(self) -> bool:
        """Check if battery level is sufficient"""
        if self.battery <= 20:
            self.logger.warning(f"Low battery: {self.battery}%")
            return False
        return True
    
    async def move_to(self, x: float, y: float) -> bool:
        """Move robot to target position"""
        if self.battery <= 0:
            self.logger.error("Cannot move: Battery depleted")
            return False
        
        # Calculate distance and energy
        dx = x - self.position[0]
        dy = y - self.position[1]
        distance = (dx**2 + dy**2)**0.5
        energy_used = distance * 2
        
        if self.battery < energy_used:
            self.logger.warning("Not enough battery for movement")
            return False
        
        # Simulate movement
        self.logger.info(f"Moving to ({x}, {y})")
        await asyncio.sleep(distance * 0.1)
        
        # Update position and battery
        self.position = (x, y)
        self.battery = max(0, self.battery - energy_used)
        self.stats['total_distance'] += distance
        
        self.logger.info(f"Moved to ({x}, {y}), Battery: {self.battery:.1f}%")
        return True
    
    async def scan_area(self) -> bool:
        """Scan area for targets"""
        self.logger.info("Scanning area...")
        await asyncio.sleep(1.0)
        
        # Use energy for scanning
        self.battery = max(0, self.battery - 5)
        
        # Simulate target finding
        if random.random() < 0.8:  # 80% chance to find target
            self.target_position = (
                random.uniform(-10, 10),
                random.uniform(-10, 10)
            )
            self.has_target = True
            self.logger.info(f"Target found at {self.target_position}")
            return True
        else:
            self.logger.info("No target found")
            return False
    
    async def pick_object(self) -> bool:
        """Pick up object at current position"""
        if not self.has_target:
            self.logger.warning("No target to pick up")
            return False
        
        if self.carrying_object:
            self.logger.warning("Already carrying an object")
            return False
        
        self.logger.info("Picking up object...")
        await asyncio.sleep(0.5)
        
        # Use energy for picking
        self.battery = max(0, self.battery - 2)
        
        self.carrying_object = True
        self.stats['objects_picked'] += 1
        
        self.logger.info("Object picked up successfully")
        return True
    
    async def return_to_base(self) -> bool:
        """Return to charging station"""
        self.logger.info("Returning to base...")
        return await self.move_to(0, 0)
    
    async def charge_battery(self) -> bool:
        """Charge battery at base station"""
        if self.position != (0, 0):
            self.logger.warning("Must be at base to charge")
            return False
        
        initial_battery = self.battery
        charging_time = (100 - self.battery) * 0.05
        
        self.logger.info(f"Charging battery from {self.battery}%")
        await asyncio.sleep(charging_time)
        
        self.battery = 100
        self.stats['battery_charges'] += 1
        
        self.logger.info(f"Charging complete (+{100-initial_battery}%)")
        return True
    
    def get_status_report(self) -> str:
        """Generate status report"""
        uptime = datetime.now() - self.stats['start_time']
        return f"""
Robot Status:
- Position: {self.position}
- Battery: {self.battery:.1f}%
- Carrying Object: {'Yes' if self.carrying_object else 'No'}
- Active Time: {uptime}

Statistics:
- Total Distance: {self.stats['total_distance']:.2f} units
- Objects Picked: {self.stats['objects_picked']}
- Battery Charges: {self.stats['battery_charges']}
"""

async def main():
    # Create robot controller
    robot = RobotController()
    
    # Create tree manager and blackboard
    manager = BehaviorTreeManager()
    blackboard = Blackboard()
    
    # Create main sequence
    main_sequence = SequenceNode("main_sequence")
    
    # Create parallel node for checks
    parallel_check = ParallelNode(
        "checks",
        policy=ParallelPolicy.REQUIRE_ALL
    )
    
    # Create battery check node
    battery_check = ConditionNode(
        "check_battery",
        condition_func=robot.check_battery
    )
    
    # Create work sequence
    work_sequence = SequenceNode("work_sequence")
    
    # Create scan nodes
    scan_action = ActionNode(
        "scan_area",
        action_func=robot.scan_area
    )
    scan_timeout = TimeoutNode(
        "scan_timeout",
        timeout=2.0
    )
    scan_timeout.add_child(scan_action)
    
    scan_retry = RetryNode(
        "scan_retry",
        properties={"max_attempts": 3}
    )
    scan_retry.add_child(scan_timeout)
    
    # Create move nodes
    move_action = ActionNode(
        "move_to_target",
        action_func=lambda: robot.move_to(
            robot.target_position[0],
            robot.target_position[1]
        ) if robot.target_position else False
    )
    
    move = TimeoutNode(
        "move_timeout",
        timeout=5.0
    )
    move.add_child(move_action)
    
    # Create pick nodes
    pick_action = ActionNode(
        "pick_object",
        action_func=robot.pick_object
    )
    
    pick = RetryNode(
        "pick_retry",
        properties={"max_attempts": 2}
    )
    pick.add_child(pick_action)
    
    # Create return nodes
    return_action = ActionNode(
        "return_to_base",
        action_func=robot.return_to_base
    )
    
    return_base = TimeoutNode(
        "return_timeout",
        timeout=5.0
    )
    return_base.add_child(return_action)
    
    # Create charge node
    charge = ActionNode(
        "charge_battery",
        action_func=robot.charge_battery
    )
    
    # Build the tree structure
    work_sequence.add_child(scan_retry)
    work_sequence.add_child(move)
    work_sequence.add_child(pick)
    work_sequence.add_child(return_base)
    
    parallel_check.add_child(battery_check)
    parallel_check.add_child(work_sequence)
    
    main_sequence.add_child(parallel_check)
    main_sequence.add_child(charge)
    
    # Initialize the tree
    manager.root = main_sequence
    main_sequence.initialize(blackboard)
    
    # Run the tree
    try:
        print("\n=== Starting Robot Control ===")
        print(robot.get_status_report())
        
        while True:
            status = await manager.tick_tree()
            if status.name in ['SUCCESS', 'FAILURE']:
                await asyncio.sleep(0.1)
                print("\n=== Current Status ===")
                print(robot.get_status_report())
            
            await asyncio.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n=== Shutting Down ===")
        print(robot.get_status_report())
        manager.stop()

if __name__ == "__main__":
    asyncio.run(main())