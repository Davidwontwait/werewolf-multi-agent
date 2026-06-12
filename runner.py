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

import sys
import json
import random
import os
import re
from typing import Optional, List

# 加载 .env
env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                os.environ.setdefault(key, val)

from agent import LLMAgent
from feishu_bot import FeishuBot
from game_state import save_state, load_state
from config import GAME_CONFIG, ROLE_CN, ROLE_EMOJI

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
    def __init__(self, auto_mode: bool = False):
        self.feishu = FeishuBot()
        self.state = None
        self.auto_mode = auto_mode  # 全自动模式
    
    def send_feishu(self, message: str):
        """发送消息到飞书"""
        self.feishu.send_message(message)
        print(message)
    
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
            "day_messages": []
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
    
    def is_game_over(self) -> Optional[str]:
        """检查游戏是否结束"""
        alive = self.get_alive_players()
        wolves = [pid for pid in alive if self.state["players"][str(pid)]["role"] == "wolf"]
        villagers = [pid for pid in alive if self.state["players"][str(pid)]["role"] != "wolf"]
        
        if len(wolves) == 0:
            return "好人"
        if len(wolves) >= len(villagers):
            return "狼人"
        return None
    
    def run_night_phase(self):
        """运行夜晚阶段"""
        self.state["night_kills"] = []
        self.state["poison_kills"] = []
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
                    self.state["waiting_for_human"] = True
                    self.state["pending_action"] = "wolf_kill"
                    self.state["human_question"] = f"你是狼人，要杀几号？\n存活目标：{alive_non_wolves}\n回复数字（例如：3）"
                    self.send_feishu(f"🌙 **第{round_num}轮 - 夜晚**\n\n{self.state['human_question']}")
                    save_state(self.state)
                    return
                
                # Agent 狼人决策
                wolf_agent = self.get_player(wolves[0]).agent
                wolf_teammates = [w for w in wolves if w != wolves[0]]
                kill_target = wolf_agent.wolf_kill(
                    self.state["public_log"],
                    alive_non_wolves,
                    wolf_teammates
                )
                self.state["night_kills"].append(kill_target)
                
                # 告诉所有狼人杀了谁
                for wid in wolves:
                    if not self.state["players"][str(wid)]["is_human"]:
                        player = self.get_player(wid)
                        player.agent.add_private_memory(f"第{round_num}晚，狼队杀了{kill_target}号")
                        self._sync_player_to_state(player)
        
        save_state(self.state)
        self.run_seer_step()
    
    def run_seer_step(self):
        """预言家查验步骤"""
        round_num = self.state["round"]
        seer = [pid for pid, p in self.state["players"].items() 
                if p["role"] == "seer" and p["alive"]]
        
        if seer:
            seer_id = int(seer[0])
            if not self.state["players"][str(seer_id)]["is_human"] or self.auto_mode:
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
            if not self.state["players"][str(witch_id)]["is_human"] or self.auto_mode:
                witch_player = self.get_player(witch_id)
                
                # 解药
                if not self.state["witch_antidote_used"] and self.state["night_kills"]:
                    killed = self.state["night_kills"][0]
                    is_first_night = (round_num == 1)
                    if witch_player.agent.witch_save(self.state["public_log"], killed, is_first_night):
                        self.state["night_kills"].remove(killed)
                        self.state["witch_antidote_used"] = True
                        witch_player.agent.add_private_memory(f"第{round_num}晚，你用解药救了{killed}号")
                        self._sync_player_to_state(witch_player)
                
                # 毒药（女巫每晚只能用一瓶药，用了解药就不能用毒药）
                elif not self.state["witch_poison_used"]:
                    alive_players = self.get_alive_players()
                    poison_target = witch_player.agent.witch_poison(self.state["public_log"], alive_players)
                    if poison_target > 0:
                        self.state["night_kills"].append(poison_target)
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
                    self.add_public_log(f"猎人{killed}号被女巫毒杀，无法发动技能")
                else:
                    # 被狼人杀害的猎人可以开枪
                    hunter_player = self.get_player(killed)
                    if not hunter_player.is_human or self.auto_mode:
                        alive_others = [p for p in self.get_alive_players() if p != killed]
                        if alive_others:
                            shoot_target = hunter_player.agent.hunter_shoot(
                                self.state["public_log"],
                                alive_others,
                                "被狼人杀害"
                            )
                            self.state["players"][str(shoot_target)]["alive"] = False
                            self.add_public_log(f"猎人{killed}号发动技能，带走了{shoot_target}号")
        
        self.run_day_announcement()
    
    def run_day_announcement(self):
        """白天公告（此时猎人开枪已在 run_hunter_step 处理完毕）"""
        round_num = self.state["round"]
        night_kills = self.state["night_kills"]
        
        if night_kills:
            death_msg = f"☀️ **第{round_num}轮 - 白天**\n💀 昨晚死亡：{', '.join(map(str, night_kills))}号"
            for killed in night_kills:
                self.state["players"][str(killed)]["alive"] = False
        else:
            death_msg = f"☀️ **第{round_num}轮 - 白天**\n🌅 昨晚是平安夜"
        
        self.add_public_log(death_msg)
        self.send_feishu(death_msg)
        save_state(self.state)
        
        # 检查游戏是否结束
        winner = self.is_game_over()
        if winner:
            self.end_game(winner)
            return
        
        self.run_speech_phase()
    
    def run_speech_phase(self):
        """发言阶段"""
        round_num = self.state["round"]
        alive = self.get_alive_players()
        
        # 确定发言顺序
        if self.state["night_kills"]:
            # 非平安夜，从死者右边第一个存活玩家开始（座位环形）
            first_dead = min(self.state["night_kills"])
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
        death_info = "平安夜" if not self.state["night_kills"] else f"死亡：{self.state['night_kills']}"
        
        # 保存发言顺序到 state，供断点续传使用
        self.state["speech_order"] = speech_order
        self.state["death_info"] = death_info
        
        self._continue_speech_phase(speech_order, 0)
    
    def _continue_speech_phase(self, speech_order: List[int], start_index: int):
        """从指定位置继续发言阶段"""
        round_num = self.state["round"]
        alive = self.get_alive_players()
        death_info = self.state.get("death_info", "")
        
        for i in range(start_index, len(speech_order)):
            speaker_id = speech_order[i]
            
            # 跳过已死亡的玩家
            if speaker_id not in alive:
                continue
            
            player = self.get_player(speaker_id)
            
            # 检查是否有人类玩家
            if player.is_human and not self.auto_mode:
                self.state["waiting_for_human"] = True
                self.state["pending_action"] = "speech"
                self.state["speech_index"] = i  # 记录当前在 speech_order 中的索引
                self.state["human_question"] = f"轮到你发言了（{speaker_id}号），请说2-3句话"
                
                context_msg = f"📋 **昨晚情况**：{death_info}\n\n"
                if self.state["speech_messages"]:
                    context_msg += "💬 **前面玩家的发言**\n" + "\n".join(self.state["speech_messages"]) + "\n\n"
                context_msg += f"🎤 **{self.state['human_question']}**"
                
                self.send_feishu(context_msg)
                save_state(self.state)
                return
            
            # Agent 发言
            speech = player.agent.speak(
                self.state["public_log"],
                death_info,
                self.state["speech_messages"],
                alive
            )
            
            speech_entry = f"**{speaker_id}号**：{speech}"
            self.state["speech_messages"].append(speech_entry)
            self.add_public_log(f"第{round_num}天，{speaker_id}号说：{speech}")
            
            self.send_feishu(speech_entry)
        
        self.run_vote_phase()
    
    def run_vote_phase(self):
        """投票阶段"""
        round_num = self.state["round"]
        alive = self.get_alive_players()
        death_info = "平安夜" if not self.state["night_kills"] else f"死亡：{self.state['night_kills']}"
        
        votes = {}
        
        for voter_id in alive:
            player = self.get_player(voter_id)
            
            # 检查是否有人类玩家
            if player.is_human and not self.auto_mode:
                self.state["waiting_for_human"] = True
                self.state["pending_action"] = "vote"
                self.state["human_question"] = f"轮到你投票了（{voter_id}号），要投几号？\n存活目标：{alive}\n回复数字（例如：3）"
                self.send_feishu(f"🗳️ **{self.state['human_question']}**")
                return
            
            # Agent 投票
            vote_target = player.agent.vote(
                self.state["public_log"],
                death_info,
                self.state["speech_messages"],
                alive
            )
            votes[vote_target] = votes.get(vote_target, 0) + 1
        
        # 统计投票结果
        vote_results = []
        if votes:
            max_votes = max(votes.values())
            voted_out = [pid for pid, v in votes.items() if v == max_votes]
            
            if len(voted_out) == 1:
                out_player = voted_out[0]
                self.state["players"][str(out_player)]["alive"] = False
                role = self.state["players"][str(out_player)]["role"]
                vote_results.append(f"⚰️ {out_player}号被投票出局，身份是{ROLE_EMOJI[role]} {ROLE_CN[role]}")
                self.add_public_log(f"第{round_num}天，{out_player}号被投票出局，身份是{ROLE_CN[role]}")
                
                # 猎人开枪
                if role == "hunter":
                    hunter_player = self.get_player(out_player)
                    if not hunter_player.is_human or self.auto_mode:
                        alive_after_vote = self.get_alive_players()
                        shoot_target = hunter_player.agent.hunter_shoot(
                            self.state["public_log"],
                            alive_after_vote,
                            "被投票出局"
                        )
                        self.state["players"][str(shoot_target)]["alive"] = False
                        shoot_role = self.state["players"][str(shoot_target)]["role"]
                        vote_results.append(f"🔫 猎人{out_player}号发动技能，带走了{shoot_target}号")
                        self.add_public_log(f"猎人{out_player}号带走了{shoot_target}号")
                    else:
                        # 人类猎人需要选择开枪目标
                        result_msg = "🗳️ **投票结果**\n" + "\n".join(vote_results)
                        self.send_feishu(result_msg)
                        alive_after_vote = self.get_alive_players()
                        self.state["waiting_for_human"] = True
                        self.state["pending_action"] = "hunter_shoot"
                        self.state["human_question"] = f"你（猎人{out_player}号）被投票出局了！你要带走几号？\n存活目标：{alive_after_vote}\n回复数字（例如：3）"
                        self.send_feishu(f"🔫 **{self.state['human_question']}**")
                        save_state(self.state)
                        return
            else:
                vote_results.append("⚖️ 平票，无人出局")
        
        result_msg = "🗳️ **投票结果**\n" + "\n".join(vote_results)
        self.send_feishu(result_msg)
        
        # 所有存活 Agent 反思本轮（MetaGPT 风格）
        vote_summary = "\n".join(vote_results)
        for pid in alive:
            player = self.get_player(pid)
            if not player.is_human:
                player.agent.reflect(
                    self.state["public_log"],
                    f"第{round_num}天投票结果：{vote_summary}"
                )
                self._sync_player_to_state(player)
        
        # 检查游戏是否结束
        winner = self.is_game_over()
        if winner:
            self.end_game(winner)
            return
        
        # 进入下一轮
        self.state["round"] += 1
        save_state(self.state)
        self.run_night_phase()
    
    def end_game(self, winner: str):
        """游戏结束"""
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
    
    def continue_game(self, response: str):
        """继续游戏（处理人类玩家输入）"""
        if not self.state["waiting_for_human"]:
            print("错误：当前不等待人类输入")
            return
        
        pending_action = self.state["pending_action"]
        human_id = self.state["human_player_id"]
        
        if pending_action == "wolf_kill":
            match = re.search(r'\d+', response)
            kill_target = int(match.group()) if match else 1
            self.state["night_kills"].append(kill_target)
            
            wolves = self.get_wolves()
            for wid in wolves:
                if not self.state["players"][str(wid)]["is_human"]:
                    player = self.get_player(wid)
                    player.agent.add_private_memory(f"第{self.state['round']}晚，狼队杀了{kill_target}号")
                    self._sync_player_to_state(player)
            
            self.state["waiting_for_human"] = False
            self.run_seer_step()
        
        elif pending_action == "speech":
            speech = response
            speech_entry = f"**{human_id}号**：{speech}"
            self.state["speech_messages"].append(speech_entry)
            self.add_public_log(f"第{self.state['round']}天，{human_id}号说：{speech}")
            
            self.state["waiting_for_human"] = False
            self.send_feishu(speech_entry)
            
            # 继续剩余玩家的发言（修复：不再跳过直接到投票）
            speech_order = self.state.get("speech_order", [])
            next_index = self.state["speech_index"] + 1
            self._continue_speech_phase(speech_order, next_index)
        
        elif pending_action == "vote":
            match = re.search(r'\d+', response)
            vote_target = int(match.group()) if match else 1
            self.state["votes"][human_id] = vote_target
            self.send_feishu(f"🗳️ 你投票给了{vote_target}号")
            
            self.state["waiting_for_human"] = False
            
            # 继续其他玩家投票
            alive = self.get_alive_players()
            death_info = "平安夜" if not self.state["night_kills"] else f"死亡：{self.state['night_kills']}"
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
            
            # 统计结果
            vote_results = []
            max_votes = max(votes.values())
            voted_out = [pid for pid, v in votes.items() if v == max_votes]
            
            if len(voted_out) == 1:
                out_player = voted_out[0]
                self.state["players"][str(out_player)]["alive"] = False
                role = self.state["players"][str(out_player)]["role"]
                vote_results.append(f"⚰️ {out_player}号被投票出局，身份是{ROLE_EMOJI[role]} {ROLE_CN[role]}")
                self.add_public_log(f"第{self.state['round']}天，{out_player}号被投票出局，身份是{ROLE_CN[role]}")
                
                # 猎人被投票出局可以开枪（不是被毒杀）
                if role == "hunter":
                    hunter_player = self.get_player(out_player)
                    if not hunter_player.is_human or self.auto_mode:
                        alive_after_vote = self.get_alive_players()
                        if alive_after_vote:
                            shoot_target = hunter_player.agent.hunter_shoot(
                                self.state["public_log"],
                                alive_after_vote,
                                "被投票出局"
                            )
                            self.state["players"][str(shoot_target)]["alive"] = False
                            vote_results.append(f"🔫 猎人{out_player}号发动技能，带走了{shoot_target}号")
                            self.add_public_log(f"猎人{out_player}号带走了{shoot_target}号")
                    else:
                        # 人类猎人需要选择开枪目标
                        result_msg = "🗳️ **投票结果**\n" + "\n".join(vote_results)
                        self.send_feishu(result_msg)
                        alive_after_vote = self.get_alive_players()
                        self.state["waiting_for_human"] = True
                        self.state["pending_action"] = "hunter_shoot"
                        self.state["human_question"] = f"你（猎人{out_player}号）被投票出局了！你要带走几号？\n存活目标：{alive_after_vote}\n回复数字（例如：3）"
                        self.send_feishu(f"🔫 **{self.state['human_question']}**")
                        save_state(self.state)
                        return
            else:
                vote_results.append("⚖️ 平票，无人出局")
            
            result_msg = "🗳️ **投票结果**\n" + "\n".join(vote_results)
            self.send_feishu(result_msg)
            
            # 反思本轮
            round_num = self.state["round"]
            vote_summary = "\n".join(vote_results)
            for pid in alive:
                player = self.get_player(pid)
                if not player.is_human:
                    player.agent.reflect(
                        self.state["public_log"],
                        f"第{round_num}天投票结果：{vote_summary}"
                    )
                    self._sync_player_to_state(player)
            
            winner = self.is_game_over()
            if winner:
                self.end_game(winner)
                return
            
            self.state["round"] += 1
            self.run_night_phase()
        
        elif pending_action == "hunter_shoot":
            # 人类猎人选择开枪目标
            match = re.search(r'\d+', response)
            shoot_target = int(match.group()) if match else None
            alive = self.get_alive_players()
            
            if shoot_target and shoot_target in alive:
                self.state["players"][str(shoot_target)]["alive"] = False
                self.send_feishu(f"🔫 猎人发动技能，带走了{shoot_target}号")
                self.add_public_log(f"猎人{human_id}号带走了{shoot_target}号")
            else:
                # 无效目标，随机选一个
                if alive:
                    shoot_target = random.choice(alive)
                    self.state["players"][str(shoot_target)]["alive"] = False
                    self.send_feishu(f"🔫 猎人发动技能，带走了{shoot_target}号")
                    self.add_public_log(f"猎人{human_id}号带走了{shoot_target}号")
            
            self.state["waiting_for_human"] = False
            
            # 反思本轮
            round_num = self.state["round"]
            alive_after = self.get_alive_players()
            for pid in alive_after:
                player = self.get_player(pid)
                if not player.is_human:
                    player.agent.reflect(
                        self.state["public_log"],
                        f"第{round_num}天猎人开枪带走了{shoot_target}号"
                    )
                    self._sync_player_to_state(player)
            
            winner = self.is_game_over()
            if winner:
                self.end_game(winner)
                return
            
            self.state["round"] += 1
            save_state(self.state)
            self.run_night_phase()

def main():
    if len(sys.argv) < 2:
        print("用法：")
        print("  python3 runner.py start [player_id]  # 开始游戏（玩家参与）")
        print("  python3 runner.py auto               # 全自动模式（9个Agent）")
        print("  python3 runner.py continue <response>  # 继续游戏")
        return
    
    runner = GameRunner()
    
    if sys.argv[1] == "start":
        human_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        runner.start_game(human_id)
    elif sys.argv[1] == "auto":
        runner = GameRunner(auto_mode=True)
        runner.start_game()
    elif sys.argv[1] == "continue":
        from game_state import load_state
        runner.state = load_state()
        if len(sys.argv) > 2:
            response = " ".join(sys.argv[2:])
            runner.continue_game(response)
        else:
            print("请提供回复内容")

if __name__ == "__main__":
    main()
