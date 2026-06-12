import os
import re
import random
import time
from openai import OpenAI
from typing import List, Dict, Optional

# ============================================================
# 狼人杀策略 Skill（基于 MetaGPT + AgentScope 研究成果）
# 参考：
# - MetaGPT: "Exploring Large Language Models for Communication Games"
# - AgentScope (阿里云): agentscope-java werewolf-hitl
# - arxiv: "Language Agents with Reinforcement Learning for Strategic Play"
# ============================================================

WEREWOLF_STRATEGY = """
【狼人杀核心策略 - 9人预女猎板子】

**术语表**：
- 平安夜：昨晚没有人死亡
- 跳身份：公开宣称自己是某个身份
- 悍跳：狼人假装有某个身份（如狼人跳预言家）
- 金水：预言家验的好人
- 查杀：预言家验的狼人
- 银水：女巫救的人
- 对跳：两个人都声称自己是同一个身份

**核心原则**：
1. 发言要有逻辑链条，不要空洞
2. 不要编造不存在的信息
3. 根据公开信息推理，不要泄露私有信息
4. 投票要有理由
5. 发言结构：总结昨晚 → 分析前面发言 → 给出判断 → 表明投票意向

---

## 一、预言家（最重要！好人的信息源）

**第一晚**：验中间位置（4-6号）或发言可疑的人

**第一天白天 — 必须跳身份！**
- 格式："我是预言家，昨晚验了X号，他是好人/狼人"
- 验到狼人（查杀）→ "X号是狼人，今天全票出他"
- 验到好人（金水）→ "X号是好人，我保他"
- 态度要坚定，不要摇摆

**后续天数**：
- 继续报验人结果
- 如果有人悍跳预言家对跳 → 对比谁的逻辑更合理
- 真预言家特征：第一天就跳、验人逻辑 consistent、发言坚定

**绝对不要**：
- ❌ 不跳身份（好人没信息源就输了）
- ❌ 验到好人就隐藏
- ❌ 说"我昨晚没跳身份"这种废话

---

## 二、女巫

**解药使用**：
- 第一晚：默认不救（除非刀的是自己）
- 第二晚及以后：如果刀的是跳预言家的人 → 救！
- 留着解药救预言家比第一晚浪费更重要

**毒药使用**：
- 不要随便用！除非确定某人是狼人
- 可以用的情况：有人悍跳预言家被投票出局 → 大概率是狼人 → 毒
- 不要毒跳预言家的人（可能是真预言家）

**发言**：
- 不要第一天就跳身份
- 可以在关键时刻跳（如被怀疑时）说"我是女巫，昨晚救了X号"

---

## 三、猎人

**开枪目标**：
- 优先带走：悍跳预言家的人、发言逻辑明显是狼人的人
- 不要带走：跳预言家的人（可能是真预言家）
- 被投票出局 → 带走质疑你最凶的人

**发言**：
- 可以暗示"我是猎人，别惹我"
- 但不要直接跳身份（容易被狼人针对）

---

## 四、狼人（需要策略选择）

**策略A：悍跳预言家（激进）**
- 第一天跳预言家，报假验人
- 如果队友被查杀 → 悍跳反报对方是狼人
- 态度要坚定，指责真预言家是"悍跳狼"

**策略B：深水狼（潜伏）**
- 假装村民，发言简洁
- 不要成为焦点
- 等好人互踩时再带节奏

**杀人目标**：
- 优先杀：跳预言家的人、女巫（如果暴露了）
- 其次杀：发言好的好人（能带节奏的人）

**投票**：
- 跟队友投同一个人，制造共识
- 不要投自己的狼队友

**绝对不要**：
- ❌ 说"我们杀了X号"
- ❌ 说"我的狼队友"
- ❌ 暴露任何夜晚行动信息

---

## 五、村民

**发言**：
- 认真分析每个人的发言逻辑
- 找出矛盾点
- 如果有人对跳预言家 → 分析谁更可信

**投票**：
- 投发言最可疑的人
- 不要跟风，要有自己的判断

**绝对不要**：
- ❌ 划水（"我没信息，听你们的"）
- ❌ 乱带节奏没有理由
"""


class LLMAgent:
    # 信息泄露关键词模式（用于检测发言中是否暴露了私有信息）
    _LEAK_PATTERNS = [
        r"狼队友",
        r"我们[昨今]晚杀",
        r"我[昨今]晚杀了",
        r"我们狼人",
        r"我是狼人.*队友",
    ]
    
    # 安全替换发言（轮换使用，避免重复暴露异常）
    _SAFE_SPEECHES = [
        "我觉得目前局势还不太明朗，大家需要仔细分析每个人的发言。",
        "我暂时没有确切的信息，但我认为我们应该理性分析每个人的行为逻辑。",
        "目前形势比较复杂，我建议大家结合前几轮的信息综合判断。",
        "我认为我们需要更多信息才能做出准确判断，先听听其他人的看法。",
        "从目前的发言来看，有些人的逻辑确实存在矛盾，大家注意甄别。",
    ]

    def __init__(self, player_id: int, role: str, role_cn: str):
        self.player_id = player_id
        self.role = role
        self.role_cn = role_cn
        self.private_memory: List[str] = []
        self.reflections: List[str] = []  # 反思记录
        self.checked_players: List[int] = []  # 预言家已验过的玩家
        
        self.client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    
    def add_private_memory(self, info: str):
        if info:
            self.private_memory.append(info)
    
    def add_reflection(self, reflection: str):
        """添加反思（MetaGPT 风格）"""
        if reflection:
            self.reflections.append(reflection)
            # 只保留最近5条反思
            if len(self.reflections) > 5:
                self.reflections = self.reflections[-5:]
    
    def _sanitize_speech(self, text: str) -> str:
        """检测并过滤发言中可能泄露私有信息的内容"""
        for pattern in self._LEAK_PATTERNS:
            if re.search(pattern, text):
                # 替换为安全的通用发言（轮换使用）
                return random.choice(self._SAFE_SPEECHES)
        return text
    
    def _get_role_specific_instruction(self) -> str:
        """根据角色生成专属指令"""
        if self.role == "wolf":
            teammates = [m for m in self.private_memory if "狼队友" in m]
            teammate_info = teammates[-1] if teammates else "未知"
            return f"""【当前角色指令 - 狼人】
{teammate_info}
你的策略选择：
- 策略A（悍跳）：如果真预言家跳了且查杀了你队友，你可以悍跳预言家反指对方
- 策略B（深水）：假装村民，发言简洁，不成为焦点，等好人互踩时再带节奏
- 杀人时优先杀跳预言家的人或发言好的好人
- 投票时跟队友投同一个人
- 绝对不要泄露夜晚行动信息"""

        elif self.role == "seer":
            checks = [m for m in self.private_memory if "查验" in m]
            check_info = "\n".join(checks) if checks else "还没有验过人"
            return f"""【当前角色指令 - 预言家】
你的验人记录：
{check_info}
- 如果你还没跳过身份，第一天必须跳！
- 报出你的验人结果，格式："我是预言家，昨晚验了X号，他是好人/狼人"
- 如果有人跟你对跳预言家，坚定指出对方是悍跳
- 好人是你的金水，要保他们"""

        elif self.role == "witch":
            antidote = "已用" if "用解药救" in str(self.private_memory) else "可用"
            poison = "已用" if "用毒药毒" in str(self.private_memory) else "可用"
            return f"""【当前角色指令 - 女巫】
解药状态：{antidote}
毒药状态：{poison}
- 不要随便暴露身份
- 毒药只在确定对方是狼人时才用
- 可以在关键时刻跳身份报银水"""

        elif self.role == "hunter":
            return f"""【当前角色指令 - 猎人】
- 如果你死了，可以带走一个人
- 优先带走悍跳预言家的人或发言最可疑的人
- 可以暗示自己是猎人，但不要直接跳身份"""

        else:  # villager
            return f"""【当前角色指令 - 村民】
- 你没有特殊技能，但你的分析能力是好人阵营的武器
- 认真分析每个人的发言逻辑
- 找出矛盾点，投出你认为最可疑的人"""

    def _build_system_prompt(self, public_log: List[str]) -> str:
        public_info = "\n".join(public_log[-20:]) if public_log else "游戏刚开始"
        private_info = "\n".join(self.private_memory) if self.private_memory else "暂无"
        reflection_info = "\n".join(self.reflections[-3:]) if self.reflections else "暂无"
        role_instruction = self._get_role_specific_instruction()
        
        return f"""你是一个狼人杀玩家，编号{self.player_id}号，身份是{self.role_cn}。

{WEREWOLF_STRATEGY}

{role_instruction}

【公开信息】（所有玩家都能看到）
{public_info}

【你的私有信息】（只有你知道，绝对不要泄露！）
{private_info}

【你的反思记录】
{reflection_info}

【发言要求】
- 用自然语言发言，像真人玩家
- 2-3句话，不要重复自己的编号
- 不要泄露私有信息
- 发言要有逻辑链条：总结昨晚 → 分析前面发言 → 给出判断 → 表明投票意向"""
    
    def chat(self, system_prompt: str, user_message: str, max_tokens: int = 300, max_retries: int = 2) -> str:
        """调用 LLM，支持自动重试"""
        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model="qwen-plus",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7,
                    max_tokens=max_tokens
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(1 * (attempt + 1))  # 递增等待
                    continue
                return ""  # 返回空字符串而非错误信息，避免泄露到公开日志
    
    def reflect(self, public_log: List[str], event: str):
        """反思当前局势（MetaGPT 风格）"""
        system_prompt = self._build_system_prompt(public_log)
        prompt = f"""刚才发生了：{event}

请用1-2句话反思当前局势：
1. 谁的行为可疑？为什么？
2. 你接下来应该怎么做？

只回复反思内容，不要其他废话："""
        
        reflection = self.chat(system_prompt, prompt, max_tokens=150)
        self.add_reflection(reflection)
    
    def speak(self, public_log: List[str], death_info: str, previous_speeches: List[str], alive_players: List[int]) -> str:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"当前存活玩家：{', '.join(map(str, alive_players))}\n"
        context += f"昨晚情况：{death_info}\n"
        if previous_speeches:
            context += "前面玩家的发言：\n" + "\n".join(previous_speeches)
        else:
            context += "你是第一个发言的。\n"
        
        prompt = f"""现在是白天发言阶段。你是{self.player_id}号玩家。
{context}

请发表你的发言（2-3句话，不要重复自己的编号，直接说内容）："""
        
        response = self.chat(system_prompt, prompt)
        # LLM 失败或返回空时，使用安全发言
        if not response:
            return random.choice(self._SAFE_SPEECHES)
        pattern = rf'^{self.player_id}号[：:]\s*'
        response = re.sub(pattern, '', response)
        # 过滤可能泄露私有信息的发言
        response = self._sanitize_speech(response)
        return response
    
    def vote(self, public_log: List[str], death_info: str, speeches: List[str], alive_players: List[int]) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"存活玩家：{alive_players}\n"
        context += f"昨晚情况：{death_info}\n"
        if speeches:
            context += "发言阶段记录：\n" + "\n".join(speeches)
        
        prompt = f"""现在是投票阶段。
{context}

你要投票给几号玩家？只回复数字（例如：3）："""
        
        response = self.chat(system_prompt, prompt)
        match = re.search(r'\d+', response)
        if match:
            vote_target = int(match.group())
            if vote_target in alive_players and vote_target != self.player_id:
                return vote_target
        
        targets = [p for p in alive_players if p != self.player_id]
        return random.choice(targets) if targets else self.player_id
    
    def wolf_kill(self, public_log: List[str], alive_non_wolves: List[int], wolf_teammates: List[int]) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"存活非狼人玩家：{alive_non_wolves}\n"
        context += f"你的狼队友：{wolf_teammates}\n"
        context += "策略：优先杀跳预言家的人、女巫（如果暴露了）、或发言好的好人"
        
        prompt = f"""现在是狼人杀人阶段。
{context}

你要杀几号玩家？只回复数字（例如：3）："""
        
        response = self.chat(system_prompt, prompt)
        match = re.search(r'\d+', response)
        if match:
            kill_target = int(match.group())
            if kill_target in alive_non_wolves:
                return kill_target
        
        return random.choice(alive_non_wolves) if alive_non_wolves else 1
    
    def seer_check(self, public_log: List[str], alive_players: List[int]) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        # 排除已验过的玩家
        unchecked = [p for p in alive_players if p != self.player_id and p not in self.checked_players]
        if not unchecked:
            # 所有人都验过了，从存活玩家中重新选（排除自己）
            unchecked = [p for p in alive_players if p != self.player_id]
        
        context = f"存活玩家：{alive_players}\n"
        if self.checked_players:
            context += f"你已经验过的玩家（不要重复验）：{self.checked_players}\n"
        context += f"可选查验目标：{unchecked}\n"
        context += "策略：优先验中间位置（4-6号）或发言可疑的人"
        
        prompt = f"""现在是预言家查验阶段。
{context}

你要查验几号玩家？只回复数字（例如：3）："""
        
        response = self.chat(system_prompt, prompt)
        match = re.search(r'\d+', response)
        if match:
            check_target = int(match.group())
            if check_target in unchecked:
                self.checked_players.append(check_target)
                return check_target
        
        target = random.choice(unchecked) if unchecked else random.choice([p for p in alive_players if p != self.player_id])
        self.checked_players.append(target)
        return target
    
    def witch_save(self, public_log: List[str], killed_player: int, is_first_night: bool) -> bool:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"{killed_player}号玩家被狼人杀了。\n"
        context += f"这是第{'1' if is_first_night else '多'}晚。\n"
        if is_first_night:
            context += "策略建议：第一晚通常不救，留着解药救预言家。除非刀的是你自己。"
        else:
            context += "策略建议：如果刀的是跳预言家的人，应该救。"
        
        prompt = f"""现在是女巫救人阶段。
{context}

你要用解药救他吗？回复 yes 或 no："""
        
        response = self.chat(system_prompt, prompt).lower()
        return "yes" in response or "是" in response or "救" in response
    
    def witch_poison(self, public_log: List[str], alive_players: List[int]) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"存活玩家：{alive_players}\n"
        context += "策略：不要随便用，除非确定某人是狼人（如悍跳预言家被投票出局的人）"
        
        prompt = f"""现在是女巫毒人阶段。
{context}

你要用毒药毒几号玩家？回复数字（例如：3），或者回复 0 不用毒："""
        
        response = self.chat(system_prompt, prompt)
        match = re.search(r'\d+', response)
        if match:
            poison_target = int(match.group())
            if poison_target == 0:
                return 0
            if poison_target in alive_players and poison_target != self.player_id:
                return poison_target
        
        return 0
    
    def hunter_shoot(self, public_log: List[str], alive_players: List[int], death_reason: str) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"存活玩家：{alive_players}\n"
        context += f"你死亡原因：{death_reason}\n"
        context += "策略：带走悍跳预言家的人，或发言最可疑的人"
        
        prompt = f"""你是猎人，现在你死了。
{context}

你要带走几号玩家？只回复数字（例如：3）："""
        
        response = self.chat(system_prompt, prompt)
        match = re.search(r'\d+', response)
        if match:
            shoot_target = int(match.group())
            if shoot_target in alive_players:
                return shoot_target
        
        return random.choice(alive_players) if alive_players else 1
