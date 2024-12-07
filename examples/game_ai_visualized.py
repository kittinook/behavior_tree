import asyncio
import sys
import logging
from datetime import datetime
from pathlib import Path
import random
from enum import Enum, auto
import curses
import math

# Add project root to Python path
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
    TimeoutNode,
    TreeVisualizer
)

class EntityType(Enum):
    PLAYER = auto()
    ENEMY = auto()
    ITEM = auto()
    COVER = auto()

class GameEntity:
    def __init__(self, entity_type: EntityType, position: tuple, properties: dict = None):
        self.type = entity_type
        self.position = position
        self.properties = properties or {}

class GameAI:
    """Complex game AI with multiple behaviors and states"""
    
    def __init__(self):
        # Character stats
        self.health = 100
        self.max_health = 100
        self.ammo = 30
        self.max_ammo = 30
        self.energy = 100
        self.max_energy = 100
        self.position = (0, 0)
        self.direction = 0  # degrees
        
        # Game state
        self.enemies = []  # List of GameEntity
        self.items = []    # List of GameEntity
        self.covers = []   # List of GameEntity
        self.in_combat = False
        self.current_target = None
        self.current_cover = None
        self.last_known_enemy_position = None
        
        # Combat stats
        self.damage = 10
        self.accuracy = 0.7
        self.stealth = 0.5
        self.detected = False
        
        # Cooldowns and timers
        self.last_attack_time = 0
        self.last_heal_time = 0
        self.attack_cooldown = 1.0
        self.heal_cooldown = 5.0
        
        # Statistics
        self.stats = {
            'shots_fired': 0,
            'hits': 0,
            'damage_dealt': 0,
            'damage_taken': 0,
            'items_collected': 0,
            'distance_traveled': 0,
            'start_time': datetime.now()
        }
        
        self.logger = logging.getLogger("GameAI")

        # Initialize game world
        self._setup_game_world()

    def _setup_game_world(self):
        """Initialize game entities"""
        # Add some enemies
        self.enemies = [
            GameEntity(EntityType.ENEMY, (random.uniform(-20, 20), random.uniform(-20, 20)),
                      {'health': 100, 'ammo': 50})
            for _ in range(3)
        ]
        
        # Add items (health, ammo, etc.)
        self.items = [
            GameEntity(EntityType.ITEM, (random.uniform(-20, 20), random.uniform(-20, 20)),
                      {'type': random.choice(['health', 'ammo', 'energy'])})
            for _ in range(5)
        ]
        
        # Add cover positions
        self.covers = [
            GameEntity(EntityType.COVER, (random.uniform(-20, 20), random.uniform(-20, 20)),
                      {'protection': random.uniform(0.3, 0.8)})
            for _ in range(4)
        ]

    def _calculate_distance(self, pos1: tuple, pos2: tuple) -> float:
        """Calculate distance between two positions"""
        return math.sqrt((pos2[0] - pos1[0])**2 + (pos2[1] - pos1[1])**2)

    async def scan_for_enemies(self) -> bool:
        """Scan surrounding area for enemies"""
        self.logger.info("Scanning for enemies...")
        await asyncio.sleep(0.5)
        
        for enemy in self.enemies:
            distance = self._calculate_distance(self.position, enemy.position)
            if distance < 15:  # Detection range
                self.current_target = enemy
                self.last_known_enemy_position = enemy.position
                self.in_combat = True
                self.logger.info(f"Enemy detected at distance {distance:.1f}")
                return True
        
        self.in_combat = False
        return False

    async def find_cover(self) -> bool:
        """Find nearest suitable cover position"""
        if not self.covers:
            return False
            
        best_cover = None
        best_score = float('inf')
        
        for cover in self.covers:
            distance = self._calculate_distance(self.position, cover.position)
            if self.current_target:
                enemy_distance = self._calculate_distance(cover.position, 
                                                       self.current_target.position)
                # Score based on distance and protection
                score = distance - enemy_distance * cover.properties['protection']
                if score < best_score:
                    best_score = score
                    best_cover = cover
        
        if best_cover:
            self.current_cover = best_cover
            self.logger.info(f"Found cover with protection {best_cover.properties['protection']:.1f}")
            return True
            
        return False

    async def move_to_position(self, target_pos: tuple) -> bool:
        """Move to specific position"""
        if not target_pos:
            return False
            
        distance = self._calculate_distance(self.position, target_pos)
        
        # Simulate movement
        movement_time = distance * 0.1
        await asyncio.sleep(movement_time)
        
        # Update position
        self.position = target_pos
        self.energy = max(0, self.energy - distance * 0.5)
        self.stats['distance_traveled'] += distance
        
        self.logger.info(f"Moved to position {target_pos}, Energy: {self.energy:.1f}")
        return True

    async def attack_target(self) -> bool:
        """Attack current target"""
        if not self.current_target or self.ammo <= 0:
            return False
            
        # Check cooldown
        current_time = datetime.now().timestamp()
        if current_time - self.last_attack_time < self.attack_cooldown:
            return False
            
        # Calculate hit chance
        distance = self._calculate_distance(self.position, self.current_target.position)
        base_accuracy = self.accuracy
        if self.current_cover:
            base_accuracy *= (1 + self.current_cover.properties['protection'])
        
        hit_chance = base_accuracy * (1 - distance/50)  # Decrease accuracy with distance
        
        # Attack
        self.ammo -= 1
        self.stats['shots_fired'] += 1
        self.last_attack_time = current_time
        
        if random.random() < hit_chance:
            damage = self.damage * random.uniform(0.8, 1.2)
            self.current_target.properties['health'] -= damage
            self.stats['hits'] += 1
            self.stats['damage_dealt'] += damage
            self.logger.info(f"Hit target for {damage:.1f} damage!")
            return True
            
        self.logger.info("Missed target!")
        return False

    async def reload_weapon(self) -> bool:
        """Reload weapon"""
        if self.ammo == self.max_ammo:
            return False
            
        self.logger.info("Reloading weapon...")
        await asyncio.sleep(2)
        
        old_ammo = self.ammo
        self.ammo = self.max_ammo
        
        self.logger.info(f"Reloaded (+{self.max_ammo - old_ammo} rounds)")
        return True

    async def use_medkit(self) -> bool:
        """Use medkit to heal"""
        if self.health >= self.max_health:
            return False
            
        # Check cooldown
        current_time = datetime.now().timestamp()
        if current_time - self.last_heal_time < self.heal_cooldown:
            return False
            
        self.logger.info("Using medkit...")
        await asyncio.sleep(1.5)
        
        heal_amount = min(50, self.max_health - self.health)
        self.health += heal_amount
        self.last_heal_time = current_time
        
        self.logger.info(f"Healed for {heal_amount} HP")
        return True

    def get_status_report(self) -> str:
        """Generate detailed status report"""
        return f"""
Game AI Status:
Health: {self.health}/{self.max_health} HP
Ammo: {self.ammo}/{self.max_ammo}
Energy: {self.energy}/{self.max_energy}
Position: {self.position}
In Combat: {'Yes' if self.in_combat else 'No'}
Current Target: {'Yes' if self.current_target else 'No'}
Using Cover: {'Yes' if self.current_cover else 'No'}

Statistics:
Shots Fired: {self.stats['shots_fired']}
Hits: {self.stats['hits']}
Accuracy: {(self.stats['hits']/self.stats['shots_fired']*100 if self.stats['shots_fired'] > 0 else 0):.1f}%
Damage Dealt: {self.stats['damage_dealt']:.1f}
Distance Traveled: {self.stats['distance_traveled']:.1f}
Items Collected: {self.stats['items_collected']}
Active Time: {datetime.now() - self.stats['start_time']}
"""

async def main():
    # Initialize game AI and tree components
    ai = GameAI()
    manager = BehaviorTreeManager()
    blackboard = Blackboard()
    visualizer = TreeVisualizer()
    
    # Create main selector
    main_selector = SelectorNode("main_selector")
    
    # Create combat sequence
    combat_sequence = SequenceNode("combat_sequence")
    
    # Health check
    health_check = ConditionNode(
        "check_health",
        condition_func=lambda: ai.health > 30
    )
    
    # Create parallel node for scanning and cover
    scan_cover_parallel = ParallelNode(
        "scan_and_cover",
        policy=ParallelPolicy.REQUIRE_ALL
    )
    
    # Scan sequence
    scan = RetryNode(
        "scan_retry",
        properties={"max_attempts": 3}
    )
    scan_action = ActionNode(
        "scan_area",
        action_func=ai.scan_for_enemies
    )
    scan.add_child(scan_action)
    
    # Find and move to cover
    cover_sequence = SequenceNode("cover_sequence")
    find_cover = ActionNode(
        "find_cover",
        action_func=ai.find_cover
    )
    move_to_cover = ActionNode(
        "move_to_cover",
        action_func=lambda: ai.move_to_position(
            ai.current_cover.position if ai.current_cover else None
        )
    )
    cover_sequence.add_child(find_cover)
    cover_sequence.add_child(move_to_cover)
    
    # Add to parallel node
    scan_cover_parallel.add_child(scan)
    scan_cover_parallel.add_child(cover_sequence)
    
    # Create attack sequence
    attack_sequence = SequenceNode("attack_sequence")
    
    # Attack with retries
    attack = RetryNode(
        "attack_retry",
        properties={"max_attempts": 3}
    )
    attack_action = ActionNode(
        "attack",
        action_func=ai.attack_target
    )
    attack.add_child(attack_action)
    
    # Add nodes to combat sequence
    combat_sequence.add_child(health_check)
    combat_sequence.add_child(scan_cover_parallel)
    combat_sequence.add_child(attack)
    
    # Create support sequence for healing/reloading
    support_sequence = SequenceNode("support_sequence")
    
    heal = ActionNode(
        "heal",
        action_func=ai.use_medkit
    )
    reload = ActionNode(
        "reload",
        action_func=ai.reload_weapon
    )
    
    support_sequence.add_child(heal)
    support_sequence.add_child(reload)
    
    # Add sequences to main selector
    main_selector.add_child(combat_sequence)
    main_selector.add_child(support_sequence)
    
    # Set up tree
    manager.root = main_selector
    main_selector.initialize(blackboard)
    
    # Run game loop
    try:
        print("\n=== Starting Game AI ===")
        print(ai.get_status_report())
        
        frame_count = 0
        while True:
            # Update AI
            status = await manager.tick_tree()
            
            # Update visualization every 10 frames
            frame_count += 1
            if frame_count % 10 == 0:
                # Generate tree visualization
                tree_viz = visualizer.create_ascii(manager.root)
                
                # Clear screen and show current status
                print("\033[2J\033[H")  # Clear screen
                print("=== Game AI Status ===")
                print(ai.get_status_report())
                print("\n=== Behavior Tree ===")
                print(tree_viz)
            
            await asyncio.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n=== Game Over ===")
        print(ai.get_status_report())
        manager.stop()

if __name__ == "__main__":
    asyncio.run(main())