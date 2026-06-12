"""
狼人杀游戏 - 公共配置模块
"""

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

# 角色中文名
ROLE_CN = {
    "wolf": "狼人",
    "villager": "村民",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人"
}

# 角色 Emoji
ROLE_EMOJI = {
    "wolf": "🐺",
    "villager": "👤",
    "seer": "🔮",
    "witch": "🧪",
    "hunter": "🔫"
}
