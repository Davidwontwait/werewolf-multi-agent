
import random
from typing import List, Dict, Tuple
from state import GameState, init_game

class Moderator:
    def __init__(self):
        self.state = init_game()
        self.log = []
    
    def log_event(self, event: str):
        self.log.append(f"[第{self.state.round}轮] {event}")
        print(event)
    
    def night_phase(self):
        self.log_event("=== 天黑请闭眼 ===")
        self.state.night_kills = []
        
        # 1. 狼人杀人
        wolves = self.state.get_wolves()
        if wolves:
            alive_non_wolves = [p for p in self.state.get_alive_players() 
                               if self.state.players[p].role != "wolf"]
            if alive_non_wolves:
                kill_target = random.choice(alive_non_wolves)
                self.state.night_kills.append(kill_target)
                self.log_event(f"狼人选择了{kill_target}号玩家")
                
                # 更新狼人记忆
                for wid in wolves:
                    self.state.players[wid].add_memory(f"第{self.state.round}晚，狼队杀了{kill_target}号")
        
        # 2. 预言家查验
        seers = [p for p in self.state.get_alive_players() 
                if self.state.players[p].role == "seer"]
        for seer_id in seers:
            check_targets = [p for p in self.state.get_alive_players() if p != seer_id]
            if check_targets:
                target = random.choice(check_targets)
                target_role = self.state.players[target].role
                result = "狼人" if target_role == "wolf" else "好人"
                self.state.seer_checks[target] = result
                self.state.players[seer_id].add_memory(
                    f"第{self.state.round}晚，查验{target}号，结果是{result}"
                )
                self.log_event(f"预言家查验了{target}号，结果是{result}")
        
        # 3. 女巫用药
        witches = [p for p in self.state.get_alive_players() 
                  if self.state.players[p].role == "witch"]
        for witch_id in witches:
            if self.state.night_kills:
                # 解药救人（第一晚必救）
                if not self.state.witch_antidote_used and self.state.round == 1:
                    saved = self.state.night_kills.pop(0)
                    self.state.witch_antidote_used = True
                    self.state.players[witch_id].add_memory(
                        f"第{self.state.round}晚，用解药救了{saved}号"
                    )
                    self.log_event(f"女巫用解药救了{saved}号")
                # 女巫一晚只能用一瓶药，用了救药就不能用毒
                # 如果没救人，30%概率用毒
                elif not self.state.witch_poison_used and random.random() < 0.3:
                    poison_targets = [p for p in self.state.get_alive_players() 
                                    if p != witch_id and self.state.players[p].role != "wolf"]
                    if poison_targets:
                        poison_target = random.choice(poison_targets)
                        self.state.night_kills.append(poison_target)
                        self.state.witch_poison_used = True
                        self.state.players[witch_id].add_memory(
                            f"第{self.state.round}晚，用毒药用毒了{poison_target}号"
                        )
                        self.log_event(f"女巫用毒药毒了{poison_target}号")
    
    def day_phase(self) -> Tuple[bool, List[int]]:
        self.state.phase = "day_discuss"
        self.log_event("=== 天亮了 ===")
        
        # 公布死亡
        deaths = self.state.night_kills.copy()
        role_cn = {"wolf": "狼人", "villager": "村民", "seer": "预言家", 
                  "witch": "女巫", "hunter": "猎人"}
        for death in deaths:
            if self.state.players[death].alive:
                self.state.players[death].alive = False
                self.log_event(f"{death}号玩家死亡，身份是{role_cn[self.state.players[death].role]}")
                
                # 猎人夜间死亡也发动技能
                if self.state.players[death].role == "hunter":
                    revenge_targets = [p for p in self.state.get_alive_players() if p != death]
                    if revenge_targets:
                        revenge_target = random.choice(revenge_targets)
                        self.state.players[revenge_target].alive = False
                        self.log_event(f"猎人{death}号发动技能，带走了{revenge_target}号，身份是{role_cn[self.state.players[revenge_target].role]}")
        
        if not deaths:
            self.log_event("昨晚是平安夜")
        
        # 检查游戏结束
        winner = self.state.is_game_over()
        if winner:
            return True, deaths
        
        # 发言阶段（简化：每个存活玩家发言）
        self.log_event("=== 发言阶段 ===")
        alive = self.state.get_alive_players()
        for pid in alive:
            player = self.state.players[pid]
            # 简单发言逻辑
            if player.role == "wolf":
                speech = f"我是{pid}号，我觉得{random.choice([p for p in alive if p != pid])}号很可疑"
            elif player.role == "seer":
                speech = f"我是{pid}号，我是预言家，昨晚查验了{random.choice([p for p in alive if p != pid])}号"
            else:
                speech = f"我是{pid}号，我是好人，大家冷静分析"
            
            self.log_event(f"{pid}号发言：{speech}")
            
            # 所有存活玩家听到发言
            for other_id in alive:
                if other_id != pid:
                    self.state.players[other_id].add_memory(f"第{self.state.round}天，{pid}号说：{speech}")
        
        # 投票阶段
        self.state.phase = "day_vote"
        self.log_event("=== 投票阶段 ===")
        votes = {}
        for voter_id in alive:
            targets = [p for p in alive if p != voter_id]
            if targets:
                vote_target = random.choice(targets)
                votes[vote_target] = votes.get(vote_target, 0) + 1
                self.log_event(f"{voter_id}号投票给{vote_target}号")
        
        # 找出票数最多的
        max_votes = max(votes.values())
        voted_out = [pid for pid, v in votes.items() if v == max_votes]
        if len(voted_out) == 1:
            out_player = voted_out[0]
            self.state.players[out_player].alive = False
            role_cn = {"wolf": "狼人", "villager": "村民", "seer": "预言家", 
                      "witch": "女巫", "hunter": "猎人"}
            self.log_event(f"{out_player}号被投票出局，身份是{role_cn[self.state.players[out_player].role]}")
            
            # 猎人技能
            if self.state.players[out_player].role == "hunter":
                revenge_targets = [p for p in self.state.get_alive_players() if p != out_player]
                if revenge_targets:
                    revenge_target = random.choice(revenge_targets)
                    self.state.players[revenge_target].alive = False
                    self.log_event(f"猎人{out_player}号发动技能，带走了{revenge_target}号，身份是{role_cn[self.state.players[revenge_target].role]}")
        else:
            self.log_event("平票，无人出局")
        
        return False, deaths
    
    def play_game(self):
        while True:
            self.night_phase()
            game_over, deaths = self.day_phase()
            
            if game_over:
                winner = self.state.is_game_over()
                self.log_event(f"=== 游戏结束，{winner}阵营胜利 ===")
                break
            
            self.state.round += 1
            self.state.phase = "night"

# 运行游戏
moderator = Moderator()
moderator.play_game()

print("\n=== 游戏日志 ===")
for log in moderator.log:
    print(log)
