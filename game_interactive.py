import random
import json
import os
from typing import List, Dict, Tuple, Optional
from agent import LLMAgent
from feishu_bot import FeishuBot
from game_state import save_state, load_state, clear_state

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
    def __init__(self, player_id: int, role: str, is_human: bool = False):
        self.id = player_id
        self.role = role
        self.alive = True
        self.is_human = is_human
        self.agent = None if is_human else LLMAgent(player_id, role, ROLE_CN[role])
    
    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "alive": self.alive,
            "is_human": self.is_human,
            "memory": self.agent.memory if self.agent else []
        }
    
    @classmethod
    def from_dict(cls, data):
        player = cls(data["id"], data["role"], data["is_human"])
        player.alive = data["alive"]
        if player.agent:
            player.agent.memory = data.get("memory", [])
            # 更新 system prompt
            player.agent.add_memory("")  # 触发 prompt 更新
        return player

class Moderator:
    def __init__(self, human_player_id: Optional[int] = None):
        self.players: Dict[int, Player] = {}
        self.phase = "night"
        self.round = 1
        self.night_kills: List[int] = []
        self.witch_antidote_used = False
        self.witch_poison_used = False
        self.public_log: List[str] = []
        self.feishu = FeishuBot()
        self.human_player_id = human_player_id
        self.waiting_for_human = False
        self.human_question = ""
        
        self.init_game()
    
    def init_game(self):
        """初始化游戏"""
        roles = []
        for role, count in GAME_CONFIG["roles"].items():
            roles.extend([role] * count)
        
        random.shuffle(roles)
        
        for i in range(GAME_CONFIG["total_players"]):
            is_human = (self.human_player_id == i + 1)
            self.players[i+1] = Player(i+1, roles[i], is_human)
        
        # 告诉狼人队友是谁
        wolves = [p.id for p in self.players.values() if p.role == "wolf"]
        for pid in wolves:
            if not self.players[pid].is_human:
                teammates = [w for w in wolves if w != pid]
                self.players[pid].agent.add_memory(f"你的狼队友是：{teammates}")
        
        # 告诉玩家身份
        if self.human_player_id:
            player = self.players[self.human_player_id]
            self.send_to_human(f"🎮 游戏开始！\n你是{self.human_player_id}号玩家，身份是【{ROLE_CN[player.role]}】")
            if player.role == "wolf":
                teammates = [w for w in wolves if w != self.human_player_id]
                self.send_to_human(f"你的狼队友是：{teammates}")
    
    def send_to_human(self, message: str):
        """发送消息给玩家"""
        if self.human_player_id:
            self.feishu.send_message(message)
    
    def log(self, event: str, public: bool = True):
        """记录日志"""
        log_entry = f"[第{self.round}轮] {event}"
        if public:
            self.public_log.append(log_entry)
        print(log_entry)
    
    def save_game_state(self):
        """保存游戏状态"""
        state = {
            "players": {pid: p.to_dict() for pid, p in self.players.items()},
            "phase": self.phase,
            "round": self.round,
            "night_kills": self.night_kills,
            "witch_antidote_used": self.witch_antidote_used,
            "witch_poison_used": self.witch_poison_used,
            "public_log": self.public_log,
            "human_player_id": self.human_player_id,
            "waiting_for_human": self.waiting_for_human,
            "human_question": self.human_question
        }
        save_state(state)
    
    @classmethod
    def load_game_state(cls):
        """加载游戏状态"""
        state = load_state()
        if not state:
            return None
        
        moderator = cls.__new__(cls)
        moderator.players = {int(pid): Player.from_dict(p) for pid, p in state["players"].items()}
        moderator.phase = state["phase"]
        moderator.round = state["round"]
        moderator.night_kills = state["night_kills"]
        moderator.witch_antidote_used = state["witch_antidote_used"]
        moderator.witch_poison_used = state["witch_poison_used"]
        moderator.public_log = state["public_log"]
        moderator.feishu = FeishuBot()
        moderator.human_player_id = state["human_player_id"]
        moderator.waiting_for_human = state["waiting_for_human"]
        moderator.human_question = state["human_question"]
        
        return moderator
    
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
    
    def ask_human(self, question: str):
        """询问玩家决策，保存状态并等待"""
        self.waiting_for_human = True
        self.human_question = question
        self.send_to_human(f"❓ {question}")
        self.save_game_state()
    
    def night_phase(self):
        """夜晚阶段"""
        self.log("🌙 天黑请闭眼")
        self.night_kills = []
        
        # 1. 狼人杀人
        wolves = self.get_wolves()
        if wolves:
            alive_non_wolves = [p for p in self.get_alive_players() 
                               if self.players[p].role != "wolf"]
            if alive_non_wolves:
                # 如果玩家是狼人，让他决策
                human_wolf = [w for w in wolves if self.players[w].is_human]
                if human_wolf:
                    self.ask_human(f"你是狼人，要杀几号？\n存活目标：{alive_non_wolves}\n回复数字（例如：3）")
                    return "waiting"
                else:
                    kill_target = self.players[wolves[0]].agent.wolf_kill(alive_non_wolves)
                    self.night_kills.append(kill_target)
                    self.log(f"🔪 狼人选择了{kill_target}号玩家", public=False)
                    
                    for wid in wolves:
                        if not self.players[wid].is_human:
                            self.players[wid].agent.add_memory(f"第{self.round}晚，狼队杀了{kill_target}号")
        
        # 2. 预言家查验
        seers = [p for p in self.get_alive_players() 
                if self.players[p].role == "seer"]
        for seer_id in seers:
            check_targets = [p for p in self.get_alive_players() if p != seer_id]
            if check_targets:
                if self.players[seer_id].is_human:
                    self.ask_human(f"你是预言家，要查验几号？\n存活目标：{check_targets}\n回复数字（例如：3）")
                    return "waiting"
                else:
                    target = self.players[seer_id].agent.seer_check(check_targets)
                    target_role = self.players[target].role
                    result = "狼人" if target_role == "wolf" else "好人"
                    self.players[seer_id].agent.add_memory(
                        f"第{self.round}晚，你查验了{target}号，结果是{result}"
                    )
                    self.log(f"🔮 预言家查验了{target}号，结果是{result}", public=False)
        
        # 3. 女巫用药
        witches = [p for p in self.get_alive_players() 
                  if self.players[p].role == "witch"]
        for witch_id in witches:
            if self.night_kills:
                # 解药救人
                if not self.witch_antidote_used:
                    killed = self.night_kills[0]
                    if self.players[witch_id].is_human:
                        self.ask_human(f"你是女巫，{killed}号被杀了，要用解药救吗？\n回复 yes 或 no")
                        return "waiting"
                    else:
                        save = self.players[witch_id].agent.witch_save(killed)
                        if save:
                            self.night_kills.pop(0)
                            self.witch_antidote_used = True
                            self.players[witch_id].agent.add_memory(
                                f"第{self.round}晚，你用解药救了{killed}号"
                            )
                            self.log(f"💊 女巫用解药救了{killed}号", public=False)
                
                # 毒药
                elif not self.witch_poison_used:
                    alive_players = self.get_alive_players()
                    if self.players[witch_id].is_human:
                        self.ask_human(f"你是女巫，要用毒药毒几号？\n存活目标：{alive_players}\n回复数字（0=不用毒）")
                        return "waiting"
                    else:
                        poison_target = self.players[witch_id].agent.witch_poison(alive_players)
                        if poison_target > 0:
                            self.night_kills.append(poison_target)
                            self.witch_poison_used = True
                            self.players[witch_id].agent.add_memory(
                                f"第{self.round}晚，你用毒药毒了{poison_target}号"
                            )
                            self.log(f"☠️ 女巫用毒药毒了{poison_target}号", public=False)
        
        return "continue"
    
    def continue_night_phase(self, human_response: str):
        """继续夜晚阶段（玩家回复后）"""
        # TODO: 解析玩家回复，继续夜晚流程
        pass
    
    def day_phase(self) -> Tuple[bool, List[int]]:
        """白天阶段"""
        self.log("☀️ 天亮了")
        
        # 公布死亡
        deaths = self.night_kills.copy()
        for death in deaths:
            if self.players[death].alive:
                self.players[death].alive = False
                self.log(f"💀 {death}号玩家死亡")
                
                # 猎人发动技能
                if self.players[death].role == "hunter":
                    alive = self.get_alive_players()
                    if alive:
                        if self.players[death].is_human:
                            self.ask_human(f"你是猎人，你死了，要带走几号？\n存活目标：{alive}\n回复数字（例如：3）")
                            return "waiting", deaths
                        else:
                            revenge_target = self.players[death].agent.hunter_shoot(alive)
                            self.players[revenge_target].alive = False
                            self.log(f"🔫 猎人{death}号发动技能，带走了{revenge_target}号")
        
        if not deaths:
            self.log("🌅 昨晚是平安夜")
        
        # 检查游戏结束
        winner = self.is_game_over()
        if winner:
            return "game_over", deaths
        
        # 发言阶段
        self.log("💬 发言阶段")
        alive = self.get_alive_players()
        for pid in alive:
            if self.players[pid].is_human:
                self.ask_human(f"轮到你发言了（{pid}号），请说2-3句话")
                return "waiting_speech", deaths
            else:
                speech = self.players[pid].agent.speak(self.public_log)
                self.log(f"{pid}号：{speech}")
                
                for other_id in alive:
                    if other_id != pid and not self.players[other_id].is_human:
                        self.players[other_id].agent.add_memory(f"第{self.round}天，{pid}号说：{speech}")
        
        # 投票阶段
        self.log("🗳️ 投票阶段")
        votes = {}
        for voter_id in alive:
            if self.players[voter_id].is_human:
                self.ask_human(f"轮到你投票了（{voter_id}号），要投几号？\n存活目标：{alive}\n回复数字（例如：3）")
                return "waiting_vote", deaths
            else:
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
                self.log(f"⚰️ {out_player}号被投票出局，身份是{ROLE_CN[self.players[out_player].role]}")
                
                # 猎人被投票出局也发动技能
                if self.players[out_player].role == "hunter":
                    alive = self.get_alive_players()
                    if alive:
                        if self.players[out_player].is_human:
                            self.ask_human(f"你是猎人，被投票出局了，要带走几号？\n存活目标：{alive}\n回复数字（例如：3）")
                            return "waiting_hunter", deaths
                        else:
                            revenge_target = self.players[out_player].agent.hunter_shoot(alive)
                            self.players[revenge_target].alive = False
                            self.log(f"🔫 猎人{out_player}号发动技能，带走了{revenge_target}号")
            else:
                self.log("⚖️ 平票，无人出局")
        
        return "continue", deaths
    
    def play_game(self):
        """运行游戏"""
        self.send_to_human("🐺 狼人杀游戏开始！\n9人局：3狼人、3村民、1预言家、1女巫、1猎人")
        
        while True:
            result = self.night_phase()
            if result == "waiting":
                self.save_game_state()
                return
            
            result, deaths = self.day_phase()
            if result in ["waiting_speech", "waiting_vote", "waiting_hunter"]:
                self.save_game_state()
                return
            
            if result == "game_over":
                winner = self.is_game_over()
                self.log(f"🎉 游戏结束，{winner}阵营胜利！")
                self.send_to_human(f"🎉 游戏结束，{winner}阵营胜利！")
                clear_state()
                break
            
            self.round += 1
            self.phase = "night"
            self.save_game_state()

if __name__ == "__main__":
    # 测试：全自动模式（无玩家）
    moderator = Moderator(human_player_id=None)
    moderator.play_game()
