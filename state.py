
import json
import random
from typing import List, Dict, Optional
from dataclasses import dataclass, field

# 游戏配置
GAME_CONFIG = {
    "total_players": 9,
    "roles": {
        "wolf": 3,
        "villager": 3,
        "seer": 1,
        "witch": 1,
        "hunter": 1
    }
}

@dataclass
class Player:
    id: int
    role: str
    alive: bool = True
    memory: List[str] = field(default_factory=list)
    
    def add_memory(self, info: str):
        self.memory.append(info)

@dataclass
class GameState:
    players: Dict[int, Player] = field(default_factory=dict)
    phase: str = "night"  # night, day_discuss, day_vote
    round: int = 1
    night_kills: List[int] = field(default_factory=list)
    witch_antidote_used: bool = False
    witch_poison_used: bool = False
    seer_checks: Dict[int, str] = field(default_factory=dict)  # player_id -> result
    
    def get_alive_players(self) -> List[int]:
        return [p.id for p in self.players.values() if p.alive]
    
    def get_wolves(self) -> List[int]:
        return [p.id for p in self.players.values() if p.role == "wolf" and p.alive]
    
    def is_game_over(self) -> Optional[str]:
        alive = self.get_alive_players()
        wolves = [pid for pid in alive if self.players[pid].role == "wolf"]
        villagers = [pid for pid in alive if self.players[pid].role != "wolf"]
        
        if len(wolves) == 0:
            return "villager"
        if len(wolves) >= len(villagers):
            return "wolf"
        return None

def init_game() -> GameState:
    state = GameState()
    roles = []
    for role, count in GAME_CONFIG["roles"].items():
        roles.extend([role] * count)
    
    random.shuffle(roles)
    
    for i in range(GAME_CONFIG["total_players"]):
        state.players[i+1] = Player(id=i+1, role=roles[i])
    
    # 初始化每个玩家的记忆
    for pid, player in state.players.items():
        if player.role == "wolf":
            wolves = state.get_wolves()
            player.add_memory(f"你是{pid}号玩家，身份是狼人。你的狼队友是：{[w for w in wolves if w != pid]}")
        elif player.role == "seer":
            player.add_memory(f"你是{pid}号玩家，身份是预言家。每晚可以查验一个人的身份。")
        elif player.role == "witch":
            player.add_memory(f"你是{pid}号玩家，身份是女巫。你有一瓶解药和一瓶毒药。")
        elif player.role == "hunter":
            player.add_memory(f"你是{pid}号玩家，身份是猎人。死亡时可以带走一个人。")
        else:
            player.add_memory(f"你是{pid}号玩家，身份是村民。")
    
    return state
