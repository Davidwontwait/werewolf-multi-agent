# 狼人杀 Multi-Agent 游戏

9 人狼人杀 AI 对战框架，基于 LLM 驱动的 multi-agent 系统。

## 特性

- **三层信息隔离**：`public_log`（公开信息）、`private_memory`（私有信息）、`reflections`（反思记录）
- **角色策略**：预言家、女巫、猎人、狼人、村民各有独立策略
- **反思机制**：每轮结束后 Agent 自动反思局势，更新怀疑对象
- **可选飞书推送**：默认只在本地输出，传入 `--feishu` 后推送到飞书群

## 安装

```bash
pip install -r requirements.txt
```

LLM 默认使用 OpenAI 兼容接口：

```bash
set OPENAI_API_KEY=你的 API Key
```

可选环境变量：

- `OPENAI_BASE_URL`：默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `DASHSCOPE_API_KEY`：兼容旧配置；未设置 `OPENAI_API_KEY` 时会读取它
- `WEREWOLF_MODEL`：默认 `deepseek-v4-pro`
- `WEREWOLF_STATE_DIR`：状态文件目录，默认 `~/.werewolf`
- `WEREWOLF_STATE_FILE`：完整状态文件路径，优先级高于 `WEREWOLF_STATE_DIR`

## 运行方式

```bash
# 全自动模式，9 个 Agent 对战
python runner.py auto

# 有人类玩家参与，指定你是 3 号
python runner.py start 3

# 有人类玩家参与，随机分配你的编号
python runner.py start

# 根据提示继续游戏
python runner.py continue 你的回复内容

# 本地 Web UI
python web_app.py

# 同步推送到飞书
python runner.py auto --feishu
python runner.py start 3 --feishu
```

飞书模式需要额外配置：

```bash
set FEISHU_APP_ID=你的 App ID
set FEISHU_APP_SECRET=你的 App Secret
set FEISHU_HOME_CHANNEL=目标群 chat_id
```

## 角色配置

- 3 狼人
- 1 预言家
- 1 女巫
- 1 猎人
- 3 村民

## 当前规则口径

- 采用 9 人预女猎屠边规则：狼人全灭则好人胜利；村民全灭或神职全灭则狼人胜利。
- 白天投票出局不公开身份，游戏结束后统一公开所有身份。
- 白天平票会进入一轮 PK 投票，PK 候选人不参与投票；PK 再平票则无人出局。
- 狼人夜间由所有存活狼人分别选择刀口，多数决；最高票平票时随机选择一个最高票目标。
- 夜间多死按事件发生顺序记录，白天发言从第一个夜间死亡玩家的下家开始。
- 人类玩家死亡后会暂停并提示进入观战，回复“观战”或在 Web UI 点击进入观战后继续自动推进。

## 核心文件

- `agent.py`：Agent 类，处理发言、投票、夜间技能和反思
- `runner.py`：游戏主循环，日夜阶段切换，处理人类输入
- `game_state.py`：状态持久化
- `feishu_bot.py`：飞书机器人接口

## 测试 API

```bash
python test_api.py
```

该脚本会检查 `DASHSCOPE_API_KEY` 并调用一次模型接口。

## License

MIT
