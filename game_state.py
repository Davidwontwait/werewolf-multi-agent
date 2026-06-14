import json
import os
from typing import Dict, Any, Optional
from pathlib import Path

DEFAULT_STATE_DIR = Path(os.getenv("WEREWOLF_STATE_DIR", Path.home() / ".werewolf"))
STATE_FILE = os.getenv("WEREWOLF_STATE_FILE", str(DEFAULT_STATE_DIR / "game_state.json"))

def save_state(state: Dict[str, Any]):
    """保存游戏状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_state() -> Optional[Dict[str, Any]]:
    """加载游戏状态"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def clear_state():
    """清除游戏状态"""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
