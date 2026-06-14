#!/usr/bin/env python3
"""
狼人杀游戏 runner v2
- 支持 public log 机制
- 支持全自动模式（9个Agent）
- 改进信息隔离
- 状态持久化修复
- 发言连续性修复
- 猎人被毒杀限制开枪
- 预言家验人去重
"""

import argparse
import sys
import random
import os
import re
from typing import Optional, List, Dict, Any


def configure_output_encoding():
    """让 Windows 控制台也能安全输出 emoji 和中文。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def safe_print(message: str):
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(str(message).encode(encoding, errors="replace").decode(encoding, errors="replace"))


def load_env_file(path: str):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                os.environ.setdefault(key, val.strip().strip('"').strip("'"))


configure_output_encoding()

# 加载 .env
load_env_file(os.path.join(os.getcwd(), ".env"))
load_env_file(os.path.expanduser("~/.hermes/.env"))

from agent import LLMAgent
from feishu_bot import FeishuBot
from game_state import save_state, load_state
from config import GAME_CONFIG, ROLE_CN, ROLE_EMOJI

GOD_ROLES = {"seer", "witch", "hunter"}

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
            "private_memory": self.agent.private_memory if self.agent else [],
            "reflections": self.agent.reflections if self.agent else [],
            "checked_players": self.agent.checked_players if self.agent else []
        }
    
    @classmethod
    def from_dict(cls, data):
        player = cls(data["id"], data["role"], data["is_human"])
        player.alive = data["alive"]
        if player.agent:
            player.agent.private_memory = data.get("private_memory", [])
            player.agent.reflections = data.get("reflections", [])
            player.agent.checked_players = data.get("checked_players", [])
        return player

class GameRunner:
    def __init__(self, auto_mode: bool = False, use_feishu: bool = False):
        self.use_feishu = use_feishu
        self.feishu = FeishuBot() if use_feishu else None
        self.state = None
        self.auto_mode = auto_mode  # 全自动模式
    
    def send_feishu(self, message: str):
        """输出消息；开启飞书时同步推送。"""
        if self.use_feishu and self.feishu:
            self.feishu.send_message(message)
        safe_print(message)
    
    def _sync_player_to_state(self, player: Player):
        """将 Player 对象的 Agent 状态同步回 self.state"""
        pid = str(player.id)
        if pid in self.state["players"]:
            self.state["players"][pid] = player.to_dict()
    
    def add_public_log(self, message: str):
        """添加公开日志"""
        if "public_log" not in self.state:
            self.state["public_log"] = []
        self.state["public_log"].append(message)
    
    def start_game(self, human_player_id: Optional[int] = None):
        """开始游戏"""
        # 随机分配角色
        roles = []
        for role, count in GAME_CONFIG["roles"].items():
            roles.extend([role] * count)
        random.shuffle(roles)
        
        # 如果没指定玩家，随机分配（全自动模式则全部为Agent）
        if self.auto_mode:
            human_player_id = None
        elif human_player_id is None:
            human_player_id = random.randint(1, 9)
        elif not 1 <= human_player_id <= GAME_CONFIG["total_players"]:
            raise ValueError(f"玩家编号必须在 1-{GAME_CONFIG['total_players']} 之间")
        
        players = {}
        for i in range(GAME_CONFIG["total_players"]):
            is_human = (human_player_id == i + 1)
            players[str(i+1)] = Player(i+1, roles[i], is_human)
        
        # 告诉狼人队友是谁
        wolves = [int(pid) for pid, p in players.items() if p.role == "wolf"]
        for pid in wolves:
            if not players[str(pid)].is_human:
                teammates = [w for w in wolves if w != pid]
                players[str(pid)].agent.add_private_memory(f"你的狼队友是：{teammates}")
        
        # 初始化状态
        self.state = {
            "players": {pid: p.to_dict() for pid, p in players.items()},
            "phase": "night",
            "round": 1,
            "night_kills": [],
            "poison_kills": [],  # 被女巫毒杀的玩家（猎人不能开枪）
            "hunter_shots": [],
            "night_notes": [],
            "death_order": [],
            "wolf_votes": {},
            "witch_antidote_used": False,
            "witch_poison_used": False,
            "public_log": [],  # 公开日志
            "human_player_id": human_player_id,
            "waiting_for_human": False,
            "human_question": "",
            "pending_action": "",
            "speech_index": 0,
            "speech_order": [],  # 当前发言顺序（用于人类断点续传）
            "speech_messages": [],
            "votes": {},
            "day_messages": [],
            "auto_mode": self.auto_mode,
            "use_feishu": self.use_feishu,
            "observer_mode": False,
            "pending_metadata": {}
        }
        
        # 告诉玩家身份
        if human_player_id:
            player = players[str(human_player_id)]
            self.send_feishu(f"🎮 **游戏开始！**\n\n9人局配置：\n- 3个狼人 🐺\n- 3个村民 👤\n- 1个预言家 🔮\n- 1个女巫 🧪\n- 1个猎人 🔫\n\n你是 **{human_player_id}号** 玩家\n你的身份是：**{ROLE_EMOJI[player.role]} {ROLE_CN[player.role]}**")
            
            if player.role == "wolf":
                teammates = [w for w in wolves if w != human_player_id]
                self.send_feishu(f"你的狼队友是：{teammates}号")
        
        if self.auto_mode:
            self.send_feishu("🎮 **全自动模式** - 9个Agent对战\n\n游戏开始，请稍候...")
        
        save_state(self.state)
        self.run_night_phase()
    
    def get_player(self, pid: int) -> Player:
        """获取玩家对象"""
        return Player.from_dict(self.state["players"][str(pid)])
    
    def get_alive_players(self) -> List[int]:
        """获取存活玩家"""
        return sorted([int(pid) for pid, p in self.state["players"].items() if p["alive"]])
    
    def get_wolves(self) -> List[int]:
        """获取存活狼人"""
        return [int(pid) for pid, p in self.state["players"].items() if p["role"] == "wolf" and p["alive"]]

    def get_seer_targets(self, seer_id: int) -> List[int]:
        """获取预言家可查验目标，优先排除已查验玩家。"""
        alive = self.get_alive_players()
        checked = self.state["players"][str(seer_id)].setdefault("checked_players", [])
        targets = [pid for pid in alive if pid != seer_id and pid not in checked]
        return targets or [pid for pid in alive if pid != seer_id]

    def get_poison_targets(self, witch_id: int) -> List[int]:
        """获取女巫可毒目标，排除自己和已经确认会在今晚死亡的目标。"""
        pending_deaths = set(self.state.get("night_kills", []))
        return [
            pid for pid in self.get_alive_players()
            if pid != witch_id and pid not in pending_deaths
        ]

    def _add_player_private_memory(self, pid: int, info: str):
        player_data = self.state["players"][str(pid)]
        player_data.setdefault("private_memory", []).append(info)

    def _append_unique_night_kill(self, pid: int):
        if pid not in self.state["night_kills"]:
            self.state["night_kills"].append(pid)
        if pid not in self.state.setdefault("death_order", []):
            self.state["death_order"].append(pid)

    def _ask_human(self, action: str, question: str, metadata: Optional[Dict[str, Any]] = None, message: Optional[str] = None):
        self.state["waiting_for_human"] = True
        self.state["pending_action"] = action
        self.state["human_question"] = question
        self.state["pending_metadata"] = metadata or {}
        self.send_feishu(message or question)
        save_state(self.state)

    def _clear_human_wait(self):
        self.state["waiting_for_human"] = False
        self.state["pending_action"] = ""
        self.state["pending_metadata"] = {}

    def _pause_if_human_dead(self, after: str, message: Optional[str] = None) -> bool:
        human_id = self.state.get("human_player_id")
        if not human_id or self.auto_mode or self.state.get("observer_mode"):
            return False
        player = self.state["players"].get(str(human_id))
        if not player or player.get("alive", True):
            return False

        question = message or (
            f"你（{human_id}号）已经死亡，接下来进入观战模式。\n"
            "回复“观战”或“continue”让剩余 AI 继续自动进行。"
        )
        self._ask_human(
            "observer_continue",
            question,
            {"after": after},
            f"👁️ **你已死亡**\n\n{question}"
        )
        return True

    def _parse_target_response(self, response: str, valid_targets: List[int], allow_zero: bool = False) -> Optional[int]:
        match = re.search(r'\d+', response)
        if not match:
            return None
        target = int(match.group())
        if allow_zero and target == 0:
            return 0
        if target in valid_targets:
            return target
        return None

    def _reject_invalid_response(self, valid_targets: List[int], allow_zero: bool = False):
        zero_hint = "，或回复 0 放弃" if allow_zero else ""
        self.send_feishu(f"输入无效，请从 {valid_targets} 中选择{zero_hint}。")
        save_state(self.state)

    def _record_seer_check(self, seer_id: int, check_target: int):
        is_wolf = self.state["players"][str(check_target)]["role"] == "wolf"
        result = "狼人" if is_wolf else "好人"
        player_data = self.state["players"][str(seer_id)]
        checked = player_data.setdefault("checked_players", [])
        if check_target not in checked:
            checked.append(check_target)
        self._add_player_private_memory(
            seer_id,
            f"第{self.state['round']}晚，你查验了{check_target}号，结果是{result}"
        )
        return result

    def _ask_human_witch_poison(self, witch_id: int, round_num: int) -> bool:
        targets = self.get_poison_targets(witch_id)
        if not targets:
            return False
        question = f"你是女巫，要使用毒药吗？\n可毒目标：{targets}\n回复目标编号，或回复 0 不用毒"
        self._ask_human(
            "witch_poison",
            question,
            {"valid_targets": targets, "allow_zero": True, "witch_id": witch_id},
            f"🧪 **第{round_num}轮 - 女巫毒药**\n\n{question}"
        )
        return True

    def _choose_plurality_target(self, votes: Dict[int, int]) -> Optional[int]:
        if not votes:
            return None
        max_votes = max(votes.values())
        candidates = [pid for pid, count in votes.items() if count == max_votes]
        return random.choice(candidates)

    def _resolve_wolf_votes(self, human_vote: Optional[int] = None):
        round_num = self.state["round"]
        wolves = self.get_wolves()
        alive_non_wolves = [
            pid for pid in self.get_alive_players()
            if self.state["players"][str(pid)]["role"] != "wolf"
        ]
        if not wolves or not alive_non_wolves:
            save_state(self.state)
            self.run_seer_step()
            return

        wolf_votes = {}
        vote_counts = {}

        if human_vote is not None:
            human_id = self.state["human_player_id"]
            wolf_votes[str(human_id)] = human_vote
            vote_counts[human_vote] = vote_counts.get(human_vote, 0) + 1

        for wid in wolves:
            if self.state["players"][str(wid)]["is_human"] and not self.auto_mode:
                continue
            player = self.get_player(wid)
            teammates = [w for w in wolves if w != wid]
            target = player.agent.wolf_kill(self.state["public_log"], alive_non_wolves, teammates)
            if target not in alive_non_wolves:
                target = random.choice(alive_non_wolves)
            wolf_votes[str(wid)] = target
            vote_counts[target] = vote_counts.get(target, 0) + 1

        kill_target = self._choose_plurality_target(vote_counts)
        if kill_target is None:
            kill_target = random.choice(alive_non_wolves)

        self.state["wolf_votes"] = wolf_votes
        self._append_unique_night_kill(kill_target)

        for wid in wolves:
            if not self.state["players"][str(wid)]["is_human"]:
                player = self.get_player(wid)
                player.agent.add_private_memory(
                    f"第{round_num}晚，狼队投票{wolf_votes}，最终杀了{kill_target}号"
                )
                self._sync_player_to_state(player)

        save_state(self.state)
        self.run_seer_step()
    
    def is_game_over(self) -> Optional[str]:
        """检查游戏是否结束：9人预女猎采用屠边规则。"""
        alive = self.get_alive_players()
        wolves = [pid for pid in alive if self.state["players"][str(pid)]["role"] == "wolf"]
        villagers = [pid for pid in alive if self.state["players"][str(pid)]["role"] == "villager"]
        gods = [pid for pid in alive if self.state["players"][str(pid)]["role"] in GOD_ROLES]
        
        if len(wolves) == 0:
            return "好人"
        if len(villagers) == 0 or len(gods) == 0:
            return "狼人"
        return None
    
    def run_night_phase(self):
        """运行夜晚阶段"""
        self.state["night_kills"] = []
        self.state["poison_kills"] = []
        self.state["hunter_shots"] = []
        self.state["night_notes"] = []
        self.state["death_order"] = []
        self.state["wolf_votes"] = {}
        self.state["phase"] = "night"
        save_state(self.state)
        self.run_wolf_step()
    
    def run_wolf_step(self):
        """狼人杀人步骤"""
        round_num = self.state["round"]
        wolves = self.get_wolves()
        
        if wolves:
            alive_non_wolves = [p for p in self.get_alive_players() 
                               if self.state["players"][str(p)]["role"] != "wolf"]
            if alive_non_wolves:
                human_wolf = [w for w in wolves if self.state["players"][str(w)]["is_human"]]
                if human_wolf and not self.auto_mode:
                    question = f"你是狼人，要杀几号？\n存活目标：{alive_non_wolves}\n回复数字（例如：3）"
                    self._ask_human(
                        "wolf_kill",
                        question,
                        {"valid_targets": alive_non_wolves},
                        f"🌙 **第{round_num}轮 - 夜晚**\n\n{question}"
                    )
                    return
                
                self._resolve_wolf_votes()
                return
        
        save_state(self.state)
        self.run_seer_step()
    
    def run_seer_step(self):
        """预言家查验步骤"""
        round_num = self.state["round"]
        seer = [pid for pid, p in self.state["players"].items() 
                if p["role"] == "seer" and p["alive"]]
        
        if seer:
            seer_id = int(seer[0])
            if self.state["players"][str(seer_id)]["is_human"] and not self.auto_mode:
                targets = self.get_seer_targets(seer_id)
                if targets:
                    question = f"你是预言家，要查验几号？\n可查验目标：{targets}\n回复数字（例如：3）"
                    self._ask_human(
                        "seer_check",
                        question,
                        {"valid_targets": targets, "seer_id": seer_id},
                        f"🔮 **第{round_num}轮 - 预言家查验**\n\n{question}"
                    )
                    return
            else:
                seer_player = self.get_player(seer_id)
                alive_players = self.get_alive_players()
                check_target = seer_player.agent.seer_check(self.state["public_log"], alive_players)
                
                # 查验结果
                is_wolf = self.state["players"][str(check_target)]["role"] == "wolf"
                result = "狼人" if is_wolf else "好人"
                
                seer_player.agent.add_private_memory(f"第{round_num}晚，你查验了{check_target}号，结果是{result}")
                self._sync_player_to_state(seer_player)
        
        save_state(self.state)
        self.run_witch_step()
    
    def run_witch_step(self):
        """女巫步骤"""
        round_num = self.state["round"]
        witch = [pid for pid, p in self.state["players"].items() 
                 if p["role"] == "witch" and p["alive"]]
        
        if witch:
            witch_id = int(witch[0])
            if self.state["players"][str(witch_id)]["is_human"] and not self.auto_mode:
                if not self.state["witch_antidote_used"] and self.state["night_kills"]:
                    killed = self.state["night_kills"][0]
                    question = f"今晚{killed}号被狼人杀了。你要用解药救他吗？\n回复 yes/no 或 是/否"
                    self._ask_human(
                        "witch_save",
                        question,
                        {"killed": killed, "witch_id": witch_id},
                        f"🧪 **第{round_num}轮 - 女巫解药**\n\n{question}"
                    )
                    return
                if not self.state["witch_poison_used"] and self._ask_human_witch_poison(witch_id, round_num):
                    return
            else:
                witch_player = self.get_player(witch_id)
                used_medicine = False
                
                # 解药
                if not self.state["witch_antidote_used"] and self.state["night_kills"]:
                    killed = self.state["night_kills"][0]
                    is_first_night = (round_num == 1)
                    if witch_player.agent.witch_save(self.state["public_log"], killed, is_first_night):
                        self.state["night_kills"].remove(killed)
                        self.state["witch_antidote_used"] = True
                        used_medicine = True
                        witch_player.agent.add_private_memory(f"第{round_num}晚，你用解药救了{killed}号")
                        self._sync_player_to_state(witch_player)
                
                # 毒药（女巫每晚只能用一瓶药，用了解药就不能用毒药）
                if not used_medicine and not self.state["witch_poison_used"]:
                    poison_targets = self.get_poison_targets(witch_id)
                    poison_target = witch_player.agent.witch_poison(self.state["public_log"], poison_targets)
                    if poison_target > 0:
                        self._append_unique_night_kill(poison_target)
                        self.state["poison_kills"].append(poison_target)
                        self.state["witch_poison_used"] = True
                        witch_player.agent.add_private_memory(f"第{round_num}晚，你用毒药毒了{poison_target}号")
                        self._sync_player_to_state(witch_player)
        
        save_state(self.state)
        self.run_hunter_step()
    
    def run_hunter_step(self):
        """猎人步骤 — 处理夜间死亡的猎人开枪（在被标记死亡前执行）"""
        poison_kills = self.state.get("poison_kills", [])
        night_kills = self.state["night_kills"]
        round_num = self.state["round"]
        
        for killed in list(night_kills):
            player_data = self.state["players"][str(killed)]
            if player_data["role"] == "hunter":
                # 被女巫毒杀的猎人不能开枪
                if killed in poison_kills:
                    note = f"猎人{killed}号被女巫毒杀，无法发动技能"
                    self.state.setdefault("night_notes", []).append(note)
                    self.add_public_log(note)
                else:
                    # 被狼人杀害的猎人可以开枪
                    hunter_player = self.get_player(killed)
                    pending_deaths = set(night_kills)
                    alive_others = [
                        p for p in self.get_alive_players()
                        if p != killed and p not in pending_deaths
                    ]
                    if alive_others:
                        if hunter_player.is_human and not self.auto_mode:
                            question = f"你（猎人{killed}号）今晚被狼人杀害了！你要带走几号？\n存活目标：{alive_others}\n回复数字（例如：3）"
                            self._ask_human(
                                "hunter_shoot",
                                question,
                                {"valid_targets": alive_others, "after": "day_announcement", "hunter_id": killed},
                                f"🔫 **猎人技能**\n\n{question}"
                            )
                            return
                        else:
                            shoot_target = hunter_player.agent.hunter_shoot(
                                self.state["public_log"],
                                alive_others,
                                "被狼人杀害"
                            )
                            self.state["players"][str(shoot_target)]["alive"] = False
                            if shoot_target not in self.state.setdefault("death_order", []):
                                self.state["death_order"].append(shoot_target)
                            self.state.setdefault("hunter_shots", []).append({
                                "hunter": killed,
                                "target": shoot_target
                            })
                            self.add_public_log(f"猎人{killed}号发动技能，带走了{shoot_target}号")
        
        self.run_day_announcement()
    
    def run_day_announcement(self):
        """白天公告（此时猎人开枪已在 run_hunter_step 处理完毕）"""
        round_num = self.state["round"]
        self.state["phase"] = "day"
        night_kills = list(dict.fromkeys(self.state["night_kills"]))
        self.state["night_kills"] = night_kills
        death_order = list(dict.fromkeys(self.state.get("death_order", night_kills)))
        self.state["death_order"] = death_order
        
        if death_order:
            death_msg = f"☀️ **第{round_num}轮 - 白天**\n💀 昨晚死亡：{', '.join(map(str, death_order))}号"
            for killed in death_order:
                self.state["players"][str(killed)]["alive"] = False
        else:
            death_msg = f"☀️ **第{round_num}轮 - 白天**\n🌅 昨晚是平安夜"

        for shot in self.state.get("hunter_shots", []):
            death_msg += f"\n🔫 猎人{shot['hunter']}号发动技能，带走了{shot['target']}号"
        for note in self.state.get("night_notes", []):
            death_msg += f"\nℹ️ {note}"
        
        self.add_public_log(death_msg)
        self.send_feishu(death_msg)
        save_state(self.state)
        
        # 检查游戏是否结束
        winner = self.is_game_over()
        if winner:
            self.end_game(winner)
            return

        if self._pause_if_human_dead("speech"):
            return
        
        self.run_speech_phase()

    def _build_current_day_facts(self) -> str:
        death_order = self.state.get("death_order", self.state.get("night_kills", []))
        facts = []
        if death_order:
            facts.append(f"本轮昨晚不是平安夜。公开死亡：{', '.join(map(str, death_order))}号。")
        else:
            facts.append("本轮昨晚是平安夜。公开死亡：无。")

        hunter_shots = self.state.get("hunter_shots", [])
        if hunter_shots:
            shots = "；".join(
                f"猎人{shot['hunter']}号发动技能，带走{shot['target']}号"
                for shot in hunter_shots
            )
            facts.append(f"公开猎人事件：{shots}。")

        if death_order:
            facts.append("禁止说本轮昨晚是平安夜、狼空刀、没有新死亡或狼刀没造成伤亡。")
        facts.append("本局白天出局不公开身份；除非有公开查验或公开身份信息，不能说某人已坐实狼人、两狼已清，只能说狼面或疑似。")
        return "\n".join(facts)
    
    def run_speech_phase(self):
        """发言阶段"""
        round_num = self.state["round"]
        self.state["phase"] = "speech"
        alive = self.get_alive_players()
        
        # 确定发言顺序
        death_order = self.state.get("death_order", self.state["night_kills"])
        if death_order:
            # 非平安夜，从死者右边第一个存活玩家开始（座位环形）
            first_dead = death_order[0]
            total = GAME_CONFIG["total_players"]
            # 从死者的下一个座位号开始，环形查找第一个存活玩家
            speech_order = []
            for offset in range(1, total + 1):
                next_id = (first_dead - 1 + offset) % total + 1  # 1-based 环形
                if next_id in alive:
                    start_idx = alive.index(next_id)
                    speech_order = alive[start_idx:] + alive[:start_idx]
                    break
            if not speech_order:
                speech_order = alive
        else:
            # 平安夜，随机起点
            start = random.choice(alive)
            start_idx = alive.index(start)
            speech_order = alive[start_idx:] + alive[:start_idx]
        
        self.state["speech_messages"] = []
        death_info = "平安夜" if not death_order else f"死亡：{death_order}"
        
        # 保存发言顺序到 state，供断点续传使用
        self.state["speech_order"] = speech_order
        self.state["death_info"] = death_info
        self.state["current_day_facts"] = self._build_current_day_facts()
        
        self._continue_speech_phase(speech_order, 0)
    
    def _continue_speech_phase(self, speech_order: List[int], start_index: int):
        """从指定位置继续发言阶段"""
        round_num = self.state["round"]
        self.state["phase"] = "speech"
        alive = self.get_alive_players()
        death_info = self.state.get("death_info", "")
        current_day_facts = self.state.get("current_day_facts", "") or self._build_current_day_facts()
        self.state["current_day_facts"] = current_day_facts
        
        for i in range(start_index, len(speech_order)):
            speaker_id = speech_order[i]
            
            # 跳过已死亡的玩家
            if speaker_id not in alive:
                continue
            
            player = self.get_player(speaker_id)
            
            # 检查是否有人类玩家
            if player.is_human and not self.auto_mode:
                self.state["speech_index"] = i  # 记录当前在 speech_order 中的索引
                question = f"轮到你发言了（{speaker_id}号），请说2-3句话"
                
                context_msg = f"📋 **昨晚情况**：{death_info}\n\n"
                if current_day_facts:
                    context_msg += "🧭 **本轮不可违背事实**\n" + current_day_facts + "\n\n"
                if self.state["speech_messages"]:
                    context_msg += "💬 **前面玩家的发言**\n" + "\n".join(self.state["speech_messages"]) + "\n\n"
                context_msg += f"🎤 **{question}**"
                
                self._ask_human("speech", question, {"speaker_id": speaker_id}, context_msg)
                return
            
            # Agent 发言
            speech = player.agent.speak(
                self.state["public_log"],
                death_info,
                self.state["speech_messages"],
                alive,
                current_day_facts
            )
            
            speech_entry = f"**{speaker_id}号**：{speech}"
            self.state["speech_messages"].append(speech_entry)
            self.add_public_log(f"第{round_num}天，{speaker_id}号说：{speech}")
            
            self.send_feishu(speech_entry)
        
        self.run_vote_phase()

    def _reflect_alive_agents(self, event: str):
        for pid in self.get_alive_players():
            player = self.get_player(pid)
            if not player.is_human:
                player.agent.reflect(self.state["public_log"], event)
                self._sync_player_to_state(player)

    def _advance_after_day_resolution(self, event: str):
        self._reflect_alive_agents(event)
        winner = self.is_game_over()
        if winner:
            self.end_game(winner)
            return
        if self._pause_if_human_dead("next_round"):
            return
        self.state["round"] += 1
        save_state(self.state)
        self.run_night_phase()

    def _agent_vote_for_targets(self, voter_id: int, valid_targets: List[int], death_info: str) -> int:
        player = self.get_player(voter_id)
        target = player.agent.vote(
            self.state["public_log"],
            death_info,
            self.state["speech_messages"],
            valid_targets
        )
        if target not in valid_targets:
            target = random.choice(valid_targets)
        return target

    def _resolve_tie_break_results(self, candidates: List[int], votes: Dict[int, int]):
        round_num = self.state["round"]
        if not votes:
            result_msg = f"🗳️ **PK投票结果**\n⚖️ {', '.join(map(str, candidates))}号平票，无人出局"
            self.send_feishu(result_msg)
            self._advance_after_day_resolution(f"第{round_num}天PK仍平票，无人出局")
            return

        max_votes = max(votes.values())
        voted_out = [pid for pid, count in votes.items() if count == max_votes]
        if len(voted_out) != 1:
            result_msg = f"🗳️ **PK投票结果**\n⚖️ {', '.join(map(str, voted_out))}号再次平票，无人出局"
            self.send_feishu(result_msg)
            self._advance_after_day_resolution(f"第{round_num}天PK仍平票，无人出局")
            return

        self._eliminate_player(voted_out[0], prefix="🗳️ **PK投票结果**")

    def _start_tie_break(self, candidates: List[int]) -> bool:
        round_num = self.state["round"]
        candidates = sorted(candidates)
        eligible_voters = [pid for pid in self.get_alive_players() if pid not in candidates]
        self.send_feishu(
            f"⚖️ {', '.join(map(str, candidates))}号平票，进入PK投票。\n"
            f"PK候选人不参与投票，可投目标：{candidates}"
        )

        if not eligible_voters:
            self._resolve_tie_break_results(candidates, {})
            return True

        human_id = self.state.get("human_player_id")
        if human_id in eligible_voters and not self.auto_mode:
            question = f"PK投票：{', '.join(map(str, candidates))}号平票，你要投几号？\n可投目标：{candidates}"
            self._ask_human(
                "tie_vote",
                question,
                {"valid_targets": candidates, "eligible_voters": eligible_voters, "candidates": candidates},
                f"🗳️ **{question}**"
            )
            return True

        death_order = self.state.get("death_order", self.state.get("night_kills", []))
        death_info = "平安夜" if not death_order else f"死亡：{death_order}"
        votes = {}
        for voter_id in eligible_voters:
            target = self._agent_vote_for_targets(voter_id, candidates, death_info)
            votes[target] = votes.get(target, 0) + 1

        self._resolve_tie_break_results(candidates, votes)
        return True

    def _eliminate_player(self, out_player: int, prefix: str = "🗳️ **投票结果**"):
        round_num = self.state["round"]
        self.state["players"][str(out_player)]["alive"] = False
        role = self.state["players"][str(out_player)]["role"]
        vote_results = [f"⚰️ {out_player}号被投票出局"]
        self.add_public_log(f"第{round_num}天，{out_player}号被投票出局")

        if role == "hunter":
            alive_after_vote = self.get_alive_players()
            if alive_after_vote:
                hunter_player = self.get_player(out_player)
                if hunter_player.is_human and not self.auto_mode:
                    result_msg = f"{prefix}\n" + "\n".join(vote_results)
                    self.send_feishu(result_msg)
                    question = f"你（猎人{out_player}号）被投票出局了！你要带走几号？\n存活目标：{alive_after_vote}\n回复数字（例如：3）"
                    self._ask_human(
                        "hunter_shoot",
                        question,
                        {"valid_targets": alive_after_vote, "after": "next_round", "hunter_id": out_player},
                        f"🔫 **{question}**"
                    )
                    return

                shoot_target = hunter_player.agent.hunter_shoot(
                    self.state["public_log"],
                    alive_after_vote,
                    "被投票出局"
                )
                self.state["players"][str(shoot_target)]["alive"] = False
                vote_results.append(f"🔫 猎人{out_player}号发动技能，带走了{shoot_target}号")
                self.add_public_log(f"猎人{out_player}号带走了{shoot_target}号")

        result_msg = f"{prefix}\n" + "\n".join(vote_results)
        self.send_feishu(result_msg)
        vote_summary = "\n".join(vote_results)
        self._advance_after_day_resolution(f"第{round_num}天投票结果：{vote_summary}")

    def _resolve_vote_results(self, votes: Dict[int, int], allow_tie_break: bool = True):
        round_num = self.state["round"]

        if votes:
            max_votes = max(votes.values())
            voted_out = [pid for pid, v in votes.items() if v == max_votes]

            if len(voted_out) == 1:
                self._eliminate_player(voted_out[0])
                return
            if allow_tie_break and self._start_tie_break(voted_out):
                return

            result_msg = f"🗳️ **投票结果**\n⚖️ {', '.join(map(str, voted_out))}号平票，无人出局"
            self.send_feishu(result_msg)
            self._advance_after_day_resolution(f"第{round_num}天平票，无人出局")
            return

        result_msg = "🗳️ **投票结果**\n⚖️ 无有效投票，无人出局"
        self.send_feishu(result_msg)
        self._advance_after_day_resolution(f"第{round_num}天无有效投票，无人出局")
    
    def run_vote_phase(self):
        """投票阶段"""
        self.state["phase"] = "vote"
        save_state(self.state)
        alive = self.get_alive_players()
        death_order = self.state.get("death_order", self.state.get("night_kills", []))
        death_info = "平安夜" if not death_order else f"死亡：{death_order}"
        
        votes = {}
        
        for voter_id in alive:
            player = self.get_player(voter_id)
            
            # 检查是否有人类玩家
            if player.is_human and not self.auto_mode:
                targets = [pid for pid in alive if pid != voter_id]
                question = f"轮到你投票了（{voter_id}号），要投几号？\n存活目标：{targets}\n回复数字（例如：3）"
                self._ask_human(
                    "vote",
                    question,
                    {"valid_targets": targets, "voter_id": voter_id},
                    f"🗳️ **{question}**"
                )
                return
            
            # Agent 投票
            vote_target = player.agent.vote(
                self.state["public_log"],
                death_info,
                self.state["speech_messages"],
                alive
            )
            votes[vote_target] = votes.get(vote_target, 0) + 1

        self._resolve_vote_results(votes)

    def _build_game_report(self, winner: str) -> Dict[str, Any]:
        """生成一份不依赖模型的结束复盘，避免游戏结束时再等待 LLM。"""
        players = self.state.get("players", {})
        roles = []
        alive = []
        dead = []
        for pid in sorted(players.keys(), key=int):
            player = players[pid]
            role = player["role"]
            status = "存活" if player.get("alive") else "死亡"
            entry = {
                "id": int(pid),
                "role": role,
                "role_cn": ROLE_CN[role],
                "role_emoji": ROLE_EMOJI[role],
                "alive": bool(player.get("alive")),
                "status": status,
            }
            roles.append(entry)
            if player.get("alive"):
                alive.append(f"{pid}号{ROLE_CN[role]}")
            else:
                dead.append(f"{pid}号{ROLE_CN[role]}")

        timeline = list(self.state.get("public_log", []))
        key_events = [
            item for item in timeline
            if "昨晚死亡" in item
            or "平安夜" in item
            or "被投票出局" in item
            or "猎人" in item
            or "平票" in item
        ]

        seer_checks = []
        medicine_notes = []
        for pid in sorted(players.keys(), key=int):
            player = players[pid]
            for info in player.get("private_memory", []):
                if "查验" in info:
                    seer_checks.append(f"{pid}号：{info}")
                if "解药" in info or "毒药" in info:
                    medicine_notes.append(f"{pid}号：{info}")

        review = []
        if winner == "狼人":
            review.append("狼人胜利通常来自好人信息没有形成统一共识，或神/民其中一边被快速清空。复盘重点看预言家信息是否被听进去、白天票型是否跟随了有效逻辑。")
        else:
            review.append("好人胜利通常来自预言家信息、发言逻辑和投票目标形成闭环。复盘重点看狼人是否暴露在对跳、票型或发言矛盾里。")
        if seer_checks:
            review.append("预言家查验线是本局最关键的信息源，后续发言和投票应优先围绕这条线验证。")
        if self.state.get("witch_antidote_used") or self.state.get("witch_poison_used"):
            review.append("女巫药使用会强烈改变轮次节奏，尤其是毒药命中身份和解药保住的信息位。")
        if any("猎人" in event for event in key_events):
            review.append("猎人开枪属于强制改票局面，枪口选择会直接影响胜负边界。")
        if not key_events:
            review.append("公开事件较少，主要应回看白天发言质量和投票理由。")

        return {
            "winner": winner,
            "rounds": self.state.get("round"),
            "roles": roles,
            "alive": alive,
            "dead": dead,
            "timeline": timeline,
            "key_events": key_events,
            "seer_checks": seer_checks,
            "medicine_notes": medicine_notes,
            "review": review,
        }
    
    def end_game(self, winner: str):
        """游戏结束"""
        self.state["phase"] = "ended"
        self.state["winner"] = winner
        self.state["final_report"] = self._build_game_report(winner)
        save_state(self.state)

        msg = f"🎉 **游戏结束**\n\n{winner}阵营胜利！"
        self.send_feishu(msg)
        
        # 显示所有玩家身份
        roles_info = []
        for pid in sorted(self.state["players"].keys(), key=int):
            p = self.state["players"][pid]
            role = p["role"]
            alive = "存活" if p["alive"] else "死亡"
            roles_info.append(f"{pid}号：{ROLE_EMOJI[role]} {ROLE_CN[role]} ({alive})")
        
        self.send_feishu("**玩家身份**：\n" + "\n".join(roles_info))

    def _complete_hunter_shoot(self, hunter_id: int, shoot_target: int, after: str):
        self.state["players"][str(shoot_target)]["alive"] = False
        if after == "day_announcement":
            if shoot_target not in self.state.setdefault("death_order", []):
                self.state["death_order"].append(shoot_target)
            self.state.setdefault("hunter_shots", []).append({
                "hunter": hunter_id,
                "target": shoot_target
            })
        else:
            self.send_feishu(f"🔫 猎人{hunter_id}号发动技能，带走了{shoot_target}号")
        self.add_public_log(f"猎人{hunter_id}号带走了{shoot_target}号")
        self.state["waiting_for_human"] = False
        self.state["pending_action"] = ""
        self.state["pending_metadata"] = {}
        save_state(self.state)

        if after == "day_announcement":
            self.run_day_announcement()
            return

        round_num = self.state["round"]
        self._advance_after_day_resolution(f"第{round_num}天猎人开枪带走了{shoot_target}号")
    
    def continue_game(self, response: str):
        """继续游戏（处理人类玩家输入）"""
        if not self.state["waiting_for_human"]:
            safe_print("错误：当前不等待人类输入")
            return
        
        pending_action = self.state["pending_action"]
        metadata = self.state.get("pending_metadata", {})
        human_id = self.state["human_player_id"]
        
        if pending_action == "observer_continue":
            self.state["observer_mode"] = True
            after = metadata.get("after", "next_round")
            self._clear_human_wait()
            save_state(self.state)

            if after == "speech":
                self.run_speech_phase()
            elif after == "next_round":
                self.state["round"] += 1
                save_state(self.state)
                self.run_night_phase()
            else:
                safe_print("已进入观战模式。")

        elif pending_action == "wolf_kill":
            valid_targets = metadata.get("valid_targets", [])
            kill_target = self._parse_target_response(response, valid_targets)
            if kill_target is None:
                self._reject_invalid_response(valid_targets)
                return

            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}
            self._resolve_wolf_votes(human_vote=kill_target)

        elif pending_action == "seer_check":
            valid_targets = metadata.get("valid_targets", [])
            seer_id = metadata.get("seer_id", human_id)
            check_target = self._parse_target_response(response, valid_targets)
            if check_target is None:
                self._reject_invalid_response(valid_targets)
                return

            result = self._record_seer_check(seer_id, check_target)
            self.send_feishu(f"🔮 你查验了{check_target}号，结果是：{result}")
            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}
            save_state(self.state)
            self.run_witch_step()

        elif pending_action == "witch_save":
            killed = metadata.get("killed")
            witch_id = metadata.get("witch_id", human_id)
            wants_save = any(word in response.lower() for word in ("yes", "y")) or "是" in response or "救" in response
            if wants_save and killed in self.state["night_kills"]:
                self.state["night_kills"].remove(killed)
                self.state["witch_antidote_used"] = True
                self._add_player_private_memory(witch_id, f"第{self.state['round']}晚，你用解药救了{killed}号")
                self.send_feishu(f"🧪 你用解药救了{killed}号")
                self.state["waiting_for_human"] = False
                self.state["pending_action"] = ""
                self.state["pending_metadata"] = {}
                save_state(self.state)
                self.run_hunter_step()
                return

            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}
            if not self.state["witch_poison_used"] and self._ask_human_witch_poison(witch_id, self.state["round"]):
                return
            save_state(self.state)
            self.run_hunter_step()

        elif pending_action == "witch_poison":
            valid_targets = metadata.get("valid_targets", [])
            allow_zero = metadata.get("allow_zero", True)
            witch_id = metadata.get("witch_id", human_id)
            poison_target = self._parse_target_response(response, valid_targets, allow_zero=allow_zero)
            if poison_target is None:
                self._reject_invalid_response(valid_targets, allow_zero=allow_zero)
                return

            if poison_target > 0:
                self._append_unique_night_kill(poison_target)
                self.state["poison_kills"].append(poison_target)
                self.state["witch_poison_used"] = True
                self._add_player_private_memory(witch_id, f"第{self.state['round']}晚，你用毒药毒了{poison_target}号")
                self.send_feishu(f"🧪 你用毒药毒了{poison_target}号")
            else:
                self.send_feishu("🧪 你没有使用毒药")

            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}
            save_state(self.state)
            self.run_hunter_step()
        
        elif pending_action == "speech":
            speech = response
            speech_entry = f"**{human_id}号**：{speech}"
            self.state["speech_messages"].append(speech_entry)
            self.add_public_log(f"第{self.state['round']}天，{human_id}号说：{speech}")
            
            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}
            self.send_feishu(speech_entry)
            
            # 继续剩余玩家的发言（修复：不再跳过直接到投票）
            speech_order = self.state.get("speech_order", [])
            next_index = self.state["speech_index"] + 1
            self._continue_speech_phase(speech_order, next_index)
        
        elif pending_action == "vote":
            valid_targets = metadata.get("valid_targets", [])
            voter_id = metadata.get("voter_id", human_id)
            vote_target = self._parse_target_response(response, valid_targets)
            if vote_target is None:
                self._reject_invalid_response(valid_targets)
                return

            self.state["votes"][human_id] = vote_target
            self.send_feishu(f"🗳️ 你投票给了{vote_target}号")
            
            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}
            
            # 继续其他玩家投票
            alive = self.get_alive_players()
            death_order = self.state.get("death_order", self.state.get("night_kills", []))
            death_info = "平安夜" if not death_order else f"死亡：{death_order}"
            votes = {vote_target: 1}
            
            for voter_id in alive:
                if voter_id != human_id:
                    player = self.get_player(voter_id)
                    vote = player.agent.vote(
                        self.state["public_log"],
                        death_info,
                        self.state["speech_messages"],
                        alive
                    )
                    votes[vote] = votes.get(vote, 0) + 1

            self._resolve_vote_results(votes)

        elif pending_action == "tie_vote":
            valid_targets = metadata.get("valid_targets", [])
            eligible_voters = metadata.get("eligible_voters", [])
            vote_target = self._parse_target_response(response, valid_targets)
            if vote_target is None:
                self._reject_invalid_response(valid_targets)
                return

            self.send_feishu(f"🗳️ 你在PK投票中投给了{vote_target}号")
            self.state["waiting_for_human"] = False
            self.state["pending_action"] = ""
            self.state["pending_metadata"] = {}

            death_order = self.state.get("death_order", self.state.get("night_kills", []))
            death_info = "平安夜" if not death_order else f"死亡：{death_order}"
            votes = {vote_target: 1}
            for voter_id in eligible_voters:
                if voter_id != human_id:
                    target = self._agent_vote_for_targets(voter_id, valid_targets, death_info)
                    votes[target] = votes.get(target, 0) + 1

            self._resolve_tie_break_results(valid_targets, votes)
        
        elif pending_action == "hunter_shoot":
            # 人类猎人选择开枪目标
            valid_targets = metadata.get("valid_targets", [])
            shoot_target = self._parse_target_response(response, valid_targets)
            if shoot_target is None:
                self._reject_invalid_response(valid_targets)
                return

            hunter_id = metadata.get("hunter_id", human_id)
            after = metadata.get("after", "next_round")
            self._complete_hunter_shoot(hunter_id, shoot_target, after)
        else:
            safe_print(f"错误：未知的等待动作 {pending_action}")

def build_parser():
    parser = argparse.ArgumentParser(description="狼人杀 Multi-Agent 游戏")
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="开始一局有人类玩家参与的游戏")
    start_parser.add_argument("player_id", nargs="?", type=int, help="人类玩家编号，省略则随机分配")
    start_parser.add_argument("--feishu", action="store_true", help="同步推送到飞书")

    auto_parser = subparsers.add_parser("auto", help="全自动模式（9 个 Agent）")
    auto_parser.add_argument("--feishu", action="store_true", help="同步推送到飞书")

    continue_parser = subparsers.add_parser("continue", help="继续处理人类玩家输入")
    continue_parser.add_argument("--feishu", action="store_true", help="本次继续时同步推送到飞书")
    continue_parser.add_argument("response", nargs=argparse.REMAINDER, help="玩家回复内容")

    return parser


def main(argv: Optional[List[str]] = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    if args.command == "start":
        runner = GameRunner(auto_mode=False, use_feishu=args.feishu)
        try:
            runner.start_game(args.player_id)
        except ValueError as exc:
            safe_print(str(exc))
    elif args.command == "auto":
        runner = GameRunner(auto_mode=True, use_feishu=args.feishu)
        runner.start_game()
    elif args.command == "continue":
        state = load_state()
        if state is None:
            safe_print("没有找到可继续的游戏状态，请先运行 start 或 auto。")
            return

        use_feishu = args.feishu or state.get("use_feishu", False)
        runner = GameRunner(auto_mode=state.get("auto_mode", False), use_feishu=use_feishu)
        runner.state = state
        runner.state["use_feishu"] = use_feishu

        response = " ".join(args.response).strip()
        if response:
            runner.continue_game(response)
        else:
            safe_print("请提供回复内容")

if __name__ == "__main__":
    main()
