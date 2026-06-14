import os
import re
import random
import time
from typing import List, Dict, Optional

try:
    from openai import OpenAI
except ImportError:  # 允许无 OpenAI SDK 时以本地随机兜底逻辑运行
    OpenAI = None

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

WEREWOLF_PLAYBOOK = """
【狼人杀 Agent Skill - 每次行动都必须执行】

一、读局顺序
1. 先整理硬信息：死亡、平安夜、投票出局、公开跳身份、公开报验人、猎人开枪。
2. 再整理软信息：谁只附和没有理由、谁的票和发言不一致、谁在回避预言家线。
3. 最后给出行动：发言必须有明确怀疑对象或保护对象；投票必须投给最符合狼面的存活玩家。

二、发言硬要求
- 不能说“没信息”“先听后面”作为主要内容，除非你是第一天第一个发言且没有任何公开信息。
- 当前轮次的死亡公告是最高优先级事实；如果本轮有公开死亡，绝对不能说“昨晚平安夜”“狼空刀”“没有新死亡”。
- 如果有人跳预言家，所有角色都要回应这条线：信谁、疑谁、为什么。
- 如果有查杀，今天优先讨论查杀和预言家可信度，不要泛泛聊位置。
- 每次发言至少包含一个玩家编号和一个可检验理由。
- 本局白天出局不翻身份，投票出局的人不能被说成“已坐实狼人”或“两狼已清”，除非公开查验已经证明。

三、投票硬要求
- 只根据公开信息和自己的合法私有信息推理，不要随机跟票。
- 优先投：被可信预言家查杀的人、发言与票型矛盾的人、没有回应关键问题的人。
- 狼人投票要兼顾团队收益：能出真预言家/神职就推进，不能时保护队友并制造替罪目标。

四、常见错误禁止
- 不要泄露私有身份信息、狼队友、夜晚行动原话。
- 不要重复上一位玩家的观点而不新增判断。
- 不要把已死亡玩家当作投票对象。
- 不要在好人身份下无理由攻击跳明神职的人。
"""


class LLMAgent:
    # 信息泄露关键词模式（用于检测发言中是否暴露了私有信息）
    _LEAK_PATTERNS = [
        r"狼队友",
        r"我们[昨今]晚杀",
        r"我[昨今]晚杀了",
        r"我们狼人",
        r"我是狼人.*队友",
        r"私有信息",
        r"私有记忆",
        r"private_memory",
        r"从私有信息来看",
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
        
        self.client = None
        if OpenAI is not None:
            self.client = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
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
        text = self._strip_thinking(text)
        for pattern in self._LEAK_PATTERNS:
            if re.search(pattern, text):
                # 替换为安全的通用发言（轮换使用）
                return random.choice(self._SAFE_SPEECHES)
        return text

    def _speech_fact_issues(self, text: str, death_info: str) -> List[str]:
        issues = []
        compact = re.sub(r"\s+", "", text)
        if death_info and death_info != "平安夜":
            death_numbers = set(map(int, re.findall(r"\d+", death_info)))
            contradiction_patterns = [
                r"昨晚(是)?平安夜",
                r"昨夜(是)?平安夜",
                r"狼空刀",
                r"没有新伤亡",
                r"没造成新伤亡",
                r"没有新死亡",
                r"无新死亡",
                r"没死人",
                r"狼刀没造成",
            ]
            if any(re.search(pattern, compact) for pattern in contradiction_patterns):
                issues.append(f"本轮昨晚情况是{death_info}，不能说平安夜、空刀或没有新死亡。")

            for number_text in re.findall(r"昨晚.*?(\d+)号单死", compact):
                if int(number_text) not in death_numbers:
                    issues.append(f"本轮昨晚情况是{death_info}，不能把其他轮次的{number_text}号单死当成当前事实。")

        hard_role_claim_patterns = [
            r"两狼已清",
            r"\d+、\d+两狼",
            r"已清.*狼",
            r"坐实.*狼",
            r"铁狼",
            r"明狼",
            r"全票狼出",
        ]
        has_public_proof_language = any(word in text for word in ("查杀", "验出", "查验", "预言家报"))
        if not has_public_proof_language and any(re.search(pattern, compact) for pattern in hard_role_claim_patterns):
            issues.append("本局出局不翻身份；没有公开查验时，不能说玩家已坐实狼人或两狼已清。")

        return issues

    def _fallback_speech(self, death_info: str, alive_players: List[int]) -> str:
        targets = [pid for pid in alive_players if pid != self.player_id]
        focus = random.choice(targets) if targets else self.player_id
        if death_info == "平安夜":
            return f"昨晚是平安夜，说明夜里没有公开死亡，但这不等于一定有人被救或狼空刀。现在我重点听{focus}号的发言和票型，他如果回避关键信息，我会优先考虑投他。"
        return f"昨晚公开情况是{death_info}，这不是平安夜，先把死亡链和公开技能事件分清。现在我重点看{focus}号是否能回应前面发言里的矛盾，如果表水不清，我会优先考虑投他。"

    def _strip_thinking(self, text: str) -> str:
        """移除模型可能输出的隐藏推理标签。"""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE).strip()
        return text
    
    def _get_role_specific_instruction(self) -> str:
        """根据角色生成专属指令"""
        if self.role == "wolf":
            teammates = [m for m in self.private_memory if "狼队友" in m]
            teammate_info = teammates[-1] if teammates else "未知"
            return f"""【当前角色指令 - 狼人】
{teammate_info}
你的策略选择：
- 如果真预言家查杀你或队友，优先考虑悍跳预言家、反打对方是悍跳狼，给出一条假的验人线。
- 如果没人查杀狼队，优先深水发言：承认公开事实，轻踩一个好人，别急着把队友推出去。
- 夜晚优先刀：可信预言家 > 暴露女巫 > 强逻辑好人 > 猎人嫌疑低的人。
- 投票时优先制造能出局的共识票；不要无理由投狼队友。
- 绝对不要说出狼队友、狼刀目标、夜晚投票这类私有信息。"""

        elif self.role == "seer":
            checks = [m for m in self.private_memory if "查验" in m]
            check_info = "\n".join(checks) if checks else "还没有验过人"
            return f"""【当前角色指令 - 预言家】
你的验人记录：
{check_info}
- 第一天白天必须跳身份并报验人结果，不要隐藏信息。
- 发言格式要清楚："我是预言家，昨晚验了X号，结果是好人/狼人"。
- 查杀优先推动当天出局；金水要明确保护并让他参与归票。
- 如果有人对跳，比较双方验人线、发言时机和投票收益，坚定打对方狼面。
- 每轮都要说明今晚想验谁，以及为什么。"""

        elif self.role == "witch":
            antidote = "已用" if "用解药救" in str(self.private_memory) else "可用"
            poison = "已用" if "用毒药毒" in str(self.private_memory) else "可用"
            return f"""【当前角色指令 - 女巫】
解药状态：{antidote}
毒药状态：{poison}
- 前期不要轻易跳身份；如果局面混乱、自己被抗推、或需要证明银水时再跳。
- 解药优先保可信预言家或自己；第一晚通常不救，除非收益很高。
- 毒药只毒高狼面目标：悍跳狼、明显票型冲锋狼、逻辑爆炸且难以白天推出的人。
- 发言可暗示药状态，但不要无意义暴露完整药况。"""

        elif self.role == "hunter":
            return f"""【当前角色指令 - 猎人】
- 活着时不要轻易明跳，但被强推时可以拍身份防止好人误票。
- 开枪优先带走：高狼面对跳预言家、带错节奏的冲锋位、票型最脏的人。
- 不要带走可信预言家、明确金水、或明显被狼人诱导攻击的人。
- 发言要给出枪口威慑和怀疑对象，避免划水。"""

        else:  # villager
            return f"""【当前角色指令 - 村民】
- 你的任务是帮好人建立公开逻辑，不要划水。
- 优先分析预言家线、查杀线、票型和发言矛盾。
- 不要乱跳神职，不要挡刀式编造身份。
- 投票必须给出理由，尽量跟随可信信息位归票。"""

    def _build_system_prompt(self, public_log: List[str]) -> str:
        public_info = "\n".join(public_log[-20:]) if public_log else "游戏刚开始"
        private_info = "\n".join(self.private_memory) if self.private_memory else "暂无"
        reflection_info = "\n".join(self.reflections[-3:]) if self.reflections else "暂无"
        role_instruction = self._get_role_specific_instruction()
        
        return f"""你是一个狼人杀玩家，编号{self.player_id}号，身份是{self.role_cn}。

{WEREWOLF_STRATEGY}

{WEREWOLF_PLAYBOOK}

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
        if self.client is None:
            return ""

        for attempt in range(max_retries + 1):
            try:
                timeout = float(os.getenv("WEREWOLF_LLM_TIMEOUT", "25"))
                response = self.client.chat.completions.create(
                    model=os.getenv("WEREWOLF_MODEL", "deepseek-v4-pro"),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7,
                    max_tokens=max_tokens,
                    timeout=timeout
                )
                return self._strip_thinking(response.choices[0].message.content.strip())
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
    
    def speak(
        self,
        public_log: List[str],
        death_info: str,
        previous_speeches: List[str],
        alive_players: List[int],
        current_day_facts: str = ""
    ) -> str:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"当前存活玩家：{', '.join(map(str, alive_players))}\n"
        context += f"昨晚情况：{death_info}\n"
        if current_day_facts:
            context += f"本轮不可违背事实：\n{current_day_facts}\n"
        if previous_speeches:
            context += "前面玩家的发言：\n" + "\n".join(previous_speeches)
        else:
            context += "你是第一个发言的。\n"
        
        prompt = f"""现在是白天发言阶段。你是{self.player_id}号玩家。
{context}

请按 Agent Skill 发言：
0. 必须严格服从“本轮不可违背事实”，不要把上一轮死亡或上一轮发言当成昨晚情况。
1. 先回应昨晚死亡/平安夜或前置位关键发言。
2. 点名至少一个你怀疑或保护的玩家编号，并给出理由。
3. 给出当前投票倾向或今晚关注对象。

回复 2-3 句话，不要重复自己的编号，直接说内容："""
        
        response = self.chat(system_prompt, prompt)
        # LLM 失败或返回空时，使用安全发言
        if not response:
            return self._fallback_speech(death_info, alive_players)
        pattern = rf'^{self.player_id}号[：:]\s*'
        response = re.sub(pattern, '', response)
        # 过滤可能泄露私有信息的发言
        response = self._sanitize_speech(response)
        issues = self._speech_fact_issues(response, death_info)
        if issues:
            repair_prompt = f"""你的上一版发言违反了公开事实，不能使用：
上一版发言：{response}
问题：
{chr(10).join(f"- {issue}" for issue in issues)}

请基于以下事实重写发言，2-3句话，点名至少一个玩家编号，不要再出现上述错误：
{context}"""
            repaired = self.chat(system_prompt, repair_prompt)
            if repaired:
                repaired = re.sub(pattern, '', repaired)
                repaired = self._sanitize_speech(repaired)
                if not self._speech_fact_issues(repaired, death_info):
                    response = repaired
                else:
                    response = self._fallback_speech(death_info, alive_players)
            else:
                response = self._fallback_speech(death_info, alive_players)
        return response
    
    def vote(self, public_log: List[str], death_info: str, speeches: List[str], alive_players: List[int]) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"存活玩家：{alive_players}\n"
        context += f"昨晚情况：{death_info}\n"
        if speeches:
            context += "发言阶段记录：\n" + "\n".join(speeches)
        
        prompt = f"""现在是投票阶段。
{context}

请按 Agent Skill 投票：优先考虑查杀、对跳可信度、发言矛盾和票型收益。
你要投票给几号玩家？只回复一个数字（例如：3），不要解释："""
        
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

请按狼人 Skill 选择刀口：优先刀可信预言家、暴露女巫或强逻辑好人，避免刀明显会触发负收益的猎人。
你要杀几号玩家？只回复一个数字（例如：3），不要解释："""
        
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

请按预言家 Skill 查验：优先验发言关键、票型可疑、能定义多人关系的位置，避免重复验。
你要查验几号玩家？只回复一个数字（例如：3），不要解释："""
        
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

请按女巫 Skill 判断救人收益：救可信信息位或自己，不为低价值刀口轻易交药。
你要用解药救他吗？只回复 yes 或 no："""
        
        response = self.chat(system_prompt, prompt).lower()
        return "yes" in response or "是" in response or "救" in response
    
    def witch_poison(self, public_log: List[str], alive_players: List[int]) -> int:
        system_prompt = self._build_system_prompt(public_log)
        
        context = f"存活玩家：{alive_players}\n"
        context += "策略：不要随便用，除非确定某人是狼人（如悍跳预言家被投票出局的人）"
        
        prompt = f"""现在是女巫毒人阶段。
{context}

请按女巫 Skill 判断毒药收益：只毒高狼面目标，不确定就留毒。
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

请按猎人 Skill 开枪：优先带走高狼面、冲锋位、悍跳位；不要带走可信预言家或明确金水。
你要带走几号玩家？只回复一个数字（例如：3），不要解释："""
        
        response = self.chat(system_prompt, prompt)
        match = re.search(r'\d+', response)
        if match:
            shoot_target = int(match.group())
            if shoot_target in alive_players:
                return shoot_target
        
        return random.choice(alive_players) if alive_players else 1
