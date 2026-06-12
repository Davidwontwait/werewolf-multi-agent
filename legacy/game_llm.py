import random
from typing import List, Dict, Tuple, Optional
from agent import LLMAgent

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

ROLE_CN = {
    "wolf": "狼人",
    "villager": "村民",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人"
}

class Player:
    def __init__(self, player_id: int, role: str):
        self.id = player_id
        self.role = role
        self.alive = True
        self.agent = LLMAgent(player_id, role, ROLE_CN[role])

class Moderator:
    def __init__(self):
        self.players: Dict[int, Player] = {}
        self.phase = "night"
        self.round = 1
        self.night_kills: List[int] = []
        self.witch_antidote_used = False
        self.witch_poison_used = False
        self.public_log: List[str] = []  # 公开信息
        
        self.init_game()
    
    def init_game(self):
        """初始化游戏"""
        roles = []
        for role, count in GAME_CONFIG["roles"].items():
            roles.extend([role] * count)
        
        random.shuffle(roles)
        
        for i in range(GAME_CONFIG["total_players"]):
            self.players[i+1] = Player(i+1, roles[i])
        
        # 告诉狼人队友是谁
        wolves = [p.id for p in self.players.values() if p.role == "wolf"]
        for pid in wolves:
            teammates = [w for w in wolves if w != pid]
            self.players[pid].agent.add_memory(f"你的狼队友是：{teammates}")
    
    def log(self, event: str, public: bool = True):
        """记录日志"""
        log_entry = f"[第{self.round}轮] {event}"
        if public:
            self.public_log.append(log_entry)
        print(log_entry)
    
    def get_alive_players(self) -> List[int]:
        return [p.id for p in self.players.values() if p.alive]
    
    def get_wolves(self) -> List[int]:
        return [p.id for p in self.players.values() if p.role == "wolf" and p.alive]
    
    def is_game_over(self) -> Optional[str]:
        alive = self.get_alive_players()
        wolves = [pid for pid in alive if self.players[pid].role == "wolf"]
        villagers = [pid for pid in alive if self.players[pid].role != "wolf"]
        
        if len(wolves) == 0:
            return "好人"
        if len(wolves) >= len(villagers):
            return "狼人"
        return None
    
    def night_phase(self):
        """夜晚阶段"""
        self.log("=== 天黑请闭眼 ===")
        self.night_kills = []
        
        # 1. 狼人杀人
        wolves = self.get_wolves()
        if wolves:
            alive_non_wolves = [p for p in self.get_alive_players() 
                               if self.players[p].role != "wolf"]
            if alive_non_wolves:
                # 让第一个狼人决策
                kill_target = self.players[wolves[0]].agent.wolf_kill(alive_non_wolves)
                self.night_kills.append(kill_target)
                self.log(f"狼人选择了{kill_target}号玩家", public=False)
                
                # 更新所有狼人记忆
                for wid in wolves:
                    self.players[wid].agent.add_memory(f"第{self.round}晚，狼队杀了{kill_target}号")
        
        # 2. 预言家查验
        seers = [p for p in self.get_alive_players() 
                if self.players[p].role == "seer"]
        for seer_id in seers:
            check_targets = [p for p in self.get_alive_players() if p != seer_id]
            if check_targets:
                target = self.players[seer_id].agent.seer_check(check_targets)
                target_role = self.players[target].role
                result = "狼人" if target_role == "wolf" else "好人"
                self.players[seer_id].agent.add_memory(
                    f"第{self.round}晚，你查验了{target}号，结果是{result}"
                )
                self.log(f"预言家查验了{target}号，结果是{result}", public=False)
        
        # 3. 女巫用药
        witches = [p for p in self.get_alive_players() 
                  if self.players[p].role == "witch"]
        for witch_id in witches:
            if self.night_kills:
                # 解药救人
                if not self.witch_antidote_used:
                    killed = self.night_kills[0]
                    save = self.players[witch_id].agent.witch_save(killed)
                    if save:
                        self.night_kills.pop(0)
                        self.witch_antidote_used = True
                        self.players[witch_id].agent.add_memory(
                            f"第{self.round}晚，你用解药救了{killed}号"
                        )
                        self.log(f"女巫用解药救了{killed}号", public=False)
                
                # 毒药（如果没用解药）
                elif not self.witch_poison_used:
                    alive_players = self.get_alive_players()
                    poison_target = self.players[witch_id].agent.witch_poison(alive_players)
                    if poison_target > 0:
                        self.night_kills.append(poison_target)
                        self.witch_poison_used = True
                        self.players[witch_id].agent.add_memory(
                            f"第{self.round}晚，你用毒药毒了{poison_target}号"
                        )
                        self.log(f"女巫用毒药毒了{poison_target}号", public=False)
    
    def day_phase(self) -> Tuple[bool, List[int]]:
        """白天阶段"""
        self.log("=== 天亮了 ===")
        
        # 公布死亡
        deaths = self.night_kills.copy()
        for death in deaths:
            if self.players[death].alive:
                self.players[death].alive = False
                self.log(f"{death}号玩家死亡")
                
                # 猎人夜间死亡也发动技能
                if self.players[death].role == "hunter":
                    alive = self.get_alive_players()
                    if alive:
                        revenge_target = self.players[death].agent.hunter_shoot(alive)
                        self.players[revenge_target].alive = False
                        self.log(f"猎人{death}号发动技能，带走了{revenge_target}号")
        
        if not deaths:
            self.log("昨晚是平安夜")
        
        # 检查游戏结束
        winner = self.is_game_over()
        if winner:
            return True, deaths
        
        # 发言阶段
        self.log("=== 发言阶段 ===")
        alive = self.get_alive_players()
        for pid in alive:
            speech = self.players[pid].agent.speak(self.public_log)
            self.log(f"{pid}号发言：{speech}")
            
            # 所有存活玩家听到发言
            for other_id in alive:
                if other_id != pid:
                    self.players[other_id].agent.add_memory(f"第{self.round}天，{pid}号说：{speech}")
        
        # 投票阶段
        self.log("=== 投票阶段 ===")
        votes = {}
        for voter_id in alive:
            vote_target = self.players[voter_id].agent.vote(alive)
            votes[vote_target] = votes.get(vote_target, 0) + 1
            self.log(f"{voter_id}号投票给{vote_target}号")
        
        # 找出票数最多的
        if votes:
            max_votes = max(votes.values())
            voted_out = [pid for pid, v in votes.items() if v == max_votes]
            if len(voted_out) == 1:
                out_player = voted_out[0]
                self.players[out_player].alive = False
                self.log(f"{out_player}号被投票出局，身份是{ROLE_CN[self.players[out_player].role]}")
                
                # 猎人被投票出局也发动技能
                if self.players[out_player].role == "hunter":
                    alive = self.get_alive_players()
                    if alive:
                        revenge_target = self.players[out_player].agent.hunter_shoot(alive)
                        self.players[revenge_target].alive = False
                        self.log(f"猎人{out_player}号发动技能，带走了{revenge_target}号")
            else:
                self.log("平票，无人出局")
        
        return False, deaths
    
    def play_game(self):
        """运行游戏"""
        while True:
            self.night_phase()
            game_over, deaths = self.day_phase()
            
            if game_over:
                winner = self.is_game_over()
                self.log(f"=== 游戏结束，{winner}阵营胜利 ===")
                break
            
            self.round += 1
            self.phase = "night"

# 运行游戏
if __name__ == "__main__":
    moderator = Moderator()
    moderator.play_game()
