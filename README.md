# 狼人杀 Multi-Agent 游戏

9人狼人杀 AI 对战框架，基于 LLM 驱动的 multi-agent 系统。

## 特性

- **三层信息隔离**：public_log（公开信息）、private_memory（私有信息）、reflections（反思记录）
- **角色策略**：预言家、女巫、猎人、狼人、村民各有独立策略
- **反思机制**：每轮结束后 Agent 自动反思局势，更新怀疑对象
- **飞书推送**：支持将游戏过程推送到飞书群

## 角色配置

- 3 狼人
- 1 预言家
- 1 女巫
- 1 猎人
- 3 村民

## 运行方式

```bash
# 纯本地运行（无飞书）
python runner.py

# 飞书交互模式
python game_feishu.py
```

## 核心文件

- `agent.py` — Agent 类，处理发言、投票、反思
- `runner.py` — 游戏主循环，日夜阶段切换
- `state.py` — 游戏状态管理
- `game_state.py` — 状态持久化
- `feishu_bot.py` — 飞书机器人接口

## 架构

```
runner.py (游戏主循环)
  ├── agent.py (Agent 决策)
  │   ├── speak() — 发言
  │   ├── vote() — 投票
  │   └── reflect() — 反思
  ├── state.py (状态管理)
  └── feishu_bot.py (飞书推送)
```

## 研究来源

- MetaGPT — 反思 + 经验学习机制
- AgentScope — 角色策略 A/B 选择
- arxiv 论文 — 强化学习驱动的狼人杀策略

## License

MIT
