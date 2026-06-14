import os
import threading
from pathlib import Path
from traceback import format_exc
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("WEREWOLF_STATE_FILE", str(BASE_DIR / "web_game_state.json"))

from flask import Flask, jsonify, request, send_from_directory

from config import ROLE_CN, ROLE_EMOJI
from game_state import load_state, save_state
from runner import GameRunner


class WebGameRunner(GameRunner):
    def __init__(self, auto_mode: bool = False):
        super().__init__(auto_mode=auto_mode, use_feishu=False)
        self.messages = []

    def send_feishu(self, message: str):
        self.messages.append(message)
        if self.state is not None:
            self.state.setdefault("web_messages", []).append(message)
            save_state(self.state)


app = Flask(__name__, static_folder=str(BASE_DIR / "web"), static_url_path="/web")
JOB_LOCK = threading.Lock()
JOB_STATE = {
    "running": False,
    "error": "",
}


def _job_snapshot():
    with JOB_LOCK:
        return dict(JOB_STATE)


def _set_job(running: bool, error: str = ""):
    with JOB_LOCK:
        JOB_STATE["running"] = running
        JOB_STATE["error"] = error


def _append_web_error(message: str):
    state = load_state()
    if not state:
        return
    state.setdefault("web_messages", []).append(message)
    save_state(state)


def _run_background(fn):
    with JOB_LOCK:
        if JOB_STATE["running"]:
            return False
        JOB_STATE["running"] = True
        JOB_STATE["error"] = ""

    def worker():
        try:
            fn()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _set_job(False, error)
            _append_web_error(f"后端任务出错：{error}")
            app.logger.error("Background game task failed:\n%s", format_exc())
            return
        _set_job(False, "")

    threading.Thread(target=worker, daemon=True).start()
    return True


def _sort_players(players: Dict[str, Dict[str, Any]]):
    return sorted(players.items(), key=lambda item: int(item[0]))


def _final_report_for_state(state: Dict[str, Any]):
    report = state.get("final_report", {})
    if report or state.get("phase") != "ended" or not state.get("winner"):
        return report
    runner = WebGameRunner(auto_mode=bool(state.get("auto_mode", False)))
    runner.state = state
    return runner._build_game_report(state["winner"])


def serialize_state(state: Optional[Dict[str, Any]], messages=None):
    messages = messages or []
    job = _job_snapshot()
    if not state:
        return {
            "has_state": False,
            "model": os.getenv("WEREWOLF_MODEL", "deepseek-v4-pro"),
            "messages": messages,
            "job_running": job["running"],
            "job_error": job["error"],
        }

    ended = state.get("phase") == "ended"
    human_id = state.get("human_player_id")
    players = []

    for pid, player in _sort_players(state.get("players", {})):
        pid_int = int(pid)
        role_visible = ended or (human_id == pid_int)
        role = player.get("role")
        players.append({
            "id": pid_int,
            "alive": player.get("alive", False),
            "is_human": player.get("is_human", False),
            "role": role if role_visible else None,
            "role_cn": ROLE_CN.get(role, "未知") if role_visible else "未知",
            "role_emoji": ROLE_EMOJI.get(role, "？") if role_visible else "？",
        })

    pending_metadata = state.get("pending_metadata", {})
    return {
        "has_state": True,
        "phase": state.get("phase"),
        "round": state.get("round"),
        "winner": state.get("winner"),
        "waiting_for_human": state.get("waiting_for_human", False),
        "pending_action": state.get("pending_action", ""),
        "pending_metadata": {
            "valid_targets": pending_metadata.get("valid_targets", []),
            "allow_zero": pending_metadata.get("allow_zero", False),
            "after": pending_metadata.get("after", ""),
        },
        "human_question": state.get("human_question", ""),
        "human_player_id": human_id,
        "observer_mode": state.get("observer_mode", False),
        "public_log": state.get("public_log", []),
        "speech_messages": state.get("speech_messages", []),
        "death_order": state.get("death_order", []),
        "final_report": _final_report_for_state(state),
        "players": players,
        "model": os.getenv("WEREWOLF_MODEL", "deepseek-v4-pro"),
        "messages": state.get("web_messages", []) + messages,
        "job_running": job["running"],
        "job_error": job["error"],
    }


def _runner_from_state(state: Optional[Dict[str, Any]] = None):
    runner = WebGameRunner(auto_mode=bool(state.get("auto_mode", False)) if state else False)
    runner.state = state
    return runner


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def api_state():
    return jsonify(serialize_state(load_state()))


@app.post("/api/start")
def api_start():
    data = request.get_json(silent=True) or {}
    if _job_snapshot()["running"]:
        return jsonify({"error": "游戏正在推进中，请稍后", **serialize_state(load_state())}), 409

    auto_mode = bool(data.get("auto_mode", False))
    player_id = data.get("player_id")
    if player_id in ("", None, "random"):
        player_id = None
    else:
        try:
            player_id = int(player_id)
        except (TypeError, ValueError):
            return jsonify({"error": "玩家编号无效", **serialize_state(load_state())}), 400

    if not auto_mode and player_id is not None and not 1 <= player_id <= 9:
        return jsonify({"error": "玩家编号必须在 1-9 之间", **serialize_state(load_state())}), 400

    def task():
        runner = WebGameRunner(auto_mode=auto_mode)
        runner.start_game(player_id)

    if not _run_background(task):
        return jsonify({"error": "游戏正在推进中，请稍后", **serialize_state(load_state())}), 409
    return jsonify(serialize_state(load_state(), ["游戏已开始，模型正在后台行动。"]))


@app.post("/api/continue")
def api_continue():
    data = request.get_json(silent=True) or {}
    if _job_snapshot()["running"]:
        return jsonify({"error": "游戏正在推进中，请稍后", **serialize_state(load_state())}), 409

    response = str(data.get("response", "")).strip()
    state = load_state()
    if not state:
        return jsonify({"error": "没有可继续的游戏", **serialize_state(None)}), 400
    if not response:
        return jsonify({"error": "请输入内容", **serialize_state(state)}), 400

    def task():
        latest = load_state()
        runner = _runner_from_state(latest)
        runner.continue_game(response)

    if not _run_background(task):
        return jsonify({"error": "游戏正在推进中，请稍后", **serialize_state(load_state())}), 409
    return jsonify(serialize_state(state, ["已提交，模型正在后台继续行动。"]))


@app.post("/api/observe")
def api_observe():
    if _job_snapshot()["running"]:
        return jsonify({"error": "游戏正在推进中，请稍后", **serialize_state(load_state())}), 409

    state = load_state()
    if not state:
        return jsonify({"error": "没有可继续的游戏", **serialize_state(None)}), 400

    def task():
        latest = load_state()
        runner = _runner_from_state(latest)
        runner.continue_game("观战")

    if not _run_background(task):
        return jsonify({"error": "游戏正在推进中，请稍后", **serialize_state(load_state())}), 409
    return jsonify(serialize_state(state, ["已进入观战，模型正在后台继续行动。"]))


if __name__ == "__main__":
    port = int(os.getenv("WEREWOLF_WEB_PORT", "7860"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
