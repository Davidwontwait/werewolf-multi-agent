import unittest

import runner


class FakeAgent:
    def __init__(self, player_id, role, role_cn=None):
        self.player_id = player_id
        self.role = role
        self.private_memory = []
        self.reflections = []
        self.checked_players = []

    def add_private_memory(self, info):
        self.private_memory.append(info)

    def reflect(self, public_log, event):
        self.reflections.append(event)

    def wolf_kill(self, public_log, alive_non_wolves, wolf_teammates):
        return alive_non_wolves[0]

    def seer_check(self, public_log, alive_players):
        target = next(pid for pid in alive_players if pid != self.player_id)
        self.checked_players.append(target)
        return target

    def witch_save(self, public_log, killed_player, is_first_night):
        return False

    def witch_poison(self, public_log, alive_players):
        return alive_players[0] if alive_players else 0

    def hunter_shoot(self, public_log, alive_players, death_reason):
        return alive_players[0]

    def speak(self, public_log, death_info, previous_speeches, alive_players, current_day_facts=""):
        return "测试发言"

    def vote(self, public_log, death_info, speeches, alive_players):
        return next(pid for pid in alive_players if pid != self.player_id)


def make_player(pid, role, alive=True, is_human=False):
    return {
        "id": pid,
        "role": role,
        "alive": alive,
        "is_human": is_human,
        "private_memory": [],
        "reflections": [],
        "checked_players": [],
    }


def make_state(players, **overrides):
    state = {
        "players": {str(player["id"]): player for player in players},
        "phase": "night",
        "round": 1,
        "night_kills": [],
        "poison_kills": [],
        "hunter_shots": [],
        "night_notes": [],
        "death_order": [],
        "wolf_votes": {},
        "witch_antidote_used": False,
        "witch_poison_used": False,
        "public_log": [],
        "human_player_id": None,
        "waiting_for_human": False,
        "human_question": "",
        "pending_action": "",
        "pending_metadata": {},
        "speech_index": 0,
        "speech_order": [],
        "speech_messages": [],
        "votes": {},
        "day_messages": [],
        "auto_mode": False,
        "use_feishu": False,
        "observer_mode": False,
    }
    state.update(overrides)
    return state


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.original_llm_agent = runner.LLMAgent
        self.original_save_state = runner.save_state
        runner.LLMAgent = FakeAgent
        runner.save_state = lambda state: None

    def tearDown(self):
        runner.LLMAgent = self.original_llm_agent
        runner.save_state = self.original_save_state

    def make_runner(self):
        game = runner.GameRunner()
        game.messages = []
        game.send_feishu = lambda message: game.messages.append(message)
        return game

    def test_invalid_human_wolf_target_keeps_waiting(self):
        game = self.make_runner()
        game.state = make_state(
            [make_player(1, "wolf", is_human=True), make_player(2, "villager")],
            human_player_id=1,
            waiting_for_human=True,
            pending_action="wolf_kill",
            pending_metadata={"valid_targets": [2]},
        )

        game.continue_game("999")

        self.assertTrue(game.state["waiting_for_human"])
        self.assertEqual(game.state["night_kills"], [])
        self.assertIn("输入无效", game.messages[-1])

    def test_human_seer_gets_prompt_and_result(self):
        game = self.make_runner()
        game.state = make_state(
            [make_player(1, "seer", is_human=True), make_player(2, "wolf")],
            human_player_id=1,
        )

        game.run_seer_step()
        self.assertTrue(game.state["waiting_for_human"])
        self.assertEqual(game.state["pending_action"], "seer_check")

        game.run_witch_step = lambda: setattr(game, "continued_after_seer", True)
        game.continue_game("2")

        self.assertTrue(game.continued_after_seer)
        self.assertEqual(game.state["players"]["1"]["checked_players"], [2])
        self.assertIn("结果是狼人", game.state["players"]["1"]["private_memory"][0])

    def test_witch_can_poison_after_declining_save(self):
        game = self.make_runner()
        game.state = make_state(
            [
                make_player(1, "wolf"),
                make_player(2, "witch"),
                make_player(3, "villager"),
            ],
            night_kills=[3],
        )
        game.run_hunter_step = lambda: None

        game.run_witch_step()

        self.assertEqual(game.state["night_kills"], [3, 1])
        self.assertEqual(game.state["poison_kills"], [1])
        self.assertTrue(game.state["witch_poison_used"])

    def test_human_night_hunter_shot_is_announced(self):
        game = self.make_runner()
        game.state = make_state(
            [
                make_player(1, "hunter", is_human=True),
                make_player(2, "villager"),
                make_player(3, "wolf"),
                make_player(4, "villager"),
            ],
            human_player_id=1,
            night_kills=[1],
        )

        game.run_hunter_step()
        self.assertEqual(game.state["pending_action"], "hunter_shoot")

        game.continue_game("2")

        self.assertTrue(any("猎人1号发动技能，带走了2号" in message for message in game.messages))

    def test_night_hunter_cannot_shoot_already_dying_player(self):
        game = self.make_runner()
        game.state = make_state(
            [
                make_player(1, "hunter", is_human=True),
                make_player(2, "villager"),
                make_player(3, "wolf"),
                make_player(4, "villager"),
            ],
            human_player_id=1,
            night_kills=[1, 2],
        )

        game.run_hunter_step()

        self.assertEqual(game.state["pending_action"], "hunter_shoot")
        self.assertNotIn(2, game.state["pending_metadata"]["valid_targets"])

    def test_slaughter_side_win_condition(self):
        game = self.make_runner()
        game.state = make_state([
            make_player(1, "wolf"),
            make_player(2, "seer"),
            make_player(3, "witch"),
        ])
        self.assertEqual(game.is_game_over(), "狼人")

        game.state = make_state([
            make_player(1, "wolf"),
            make_player(2, "villager"),
            make_player(3, "villager"),
        ])
        self.assertEqual(game.is_game_over(), "狼人")

        game.state = make_state([
            make_player(1, "villager"),
            make_player(2, "seer"),
        ])
        self.assertEqual(game.is_game_over(), "好人")

    def test_vote_out_does_not_reveal_role(self):
        game = self.make_runner()
        game.state = make_state([
            make_player(1, "villager"),
            make_player(2, "wolf"),
            make_player(3, "seer"),
        ])
        game._advance_after_day_resolution = lambda event: setattr(game, "advanced_event", event)

        game._resolve_vote_results({1: 2, 2: 1})

        self.assertFalse(game.state["players"]["1"]["alive"])
        self.assertTrue(any("1号被投票出局" in message for message in game.messages))
        self.assertFalse(any("身份是" in message for message in game.messages))
        self.assertFalse(any("村民" in message for message in game.messages))

    def test_tie_enters_pk_revote(self):
        game = self.make_runner()
        game.state = make_state([
            make_player(1, "villager"),
            make_player(2, "wolf"),
            make_player(3, "seer"),
            make_player(4, "witch"),
        ])
        game._advance_after_day_resolution = lambda event: setattr(game, "advanced_event", event)

        game._resolve_vote_results({1: 2, 2: 2})

        self.assertFalse(game.state["players"]["1"]["alive"])
        self.assertTrue(any("进入PK投票" in message for message in game.messages))
        self.assertTrue(any("PK投票结果" in message for message in game.messages))

    def test_human_tie_vote_waits_for_input(self):
        game = self.make_runner()
        game.state = make_state([
            make_player(1, "villager"),
            make_player(2, "wolf"),
            make_player(3, "seer", is_human=True),
            make_player(4, "witch"),
        ], human_player_id=3)

        game._resolve_vote_results({1: 2, 2: 2})

        self.assertTrue(game.state["waiting_for_human"])
        self.assertEqual(game.state["pending_action"], "tie_vote")
        self.assertEqual(game.state["pending_metadata"]["valid_targets"], [1, 2])

    def test_wolf_team_uses_plurality_vote(self):
        game = self.make_runner()
        game.state = make_state([
            make_player(1, "wolf", is_human=True),
            make_player(2, "wolf"),
            make_player(3, "wolf"),
            make_player(4, "villager"),
            make_player(5, "seer"),
        ], human_player_id=1)
        game.run_seer_step = lambda: setattr(game, "continued_after_wolves", True)

        game._resolve_wolf_votes(human_vote=5)

        self.assertEqual(game.state["night_kills"], [4])
        self.assertEqual(game.state["wolf_votes"]["1"], 5)
        self.assertEqual(game.state["wolf_votes"]["2"], 4)
        self.assertTrue(game.continued_after_wolves)

    def test_speech_order_starts_after_first_death_in_event_order(self):
        game = self.make_runner()
        players = [
            make_player(1, "wolf"),
            make_player(2, "villager", alive=False),
            make_player(3, "seer"),
            make_player(4, "witch"),
            make_player(5, "villager", alive=False),
            make_player(6, "hunter", is_human=True),
            make_player(7, "villager"),
            make_player(8, "wolf"),
            make_player(9, "wolf"),
        ]
        game.state = make_state(players, human_player_id=6, night_kills=[5, 2], death_order=[5, 2])

        game.run_speech_phase()

        self.assertEqual(game.state["speech_order"][0], 6)
        self.assertEqual(game.state["pending_action"], "speech")

    def test_speech_phase_builds_current_day_facts(self):
        game = self.make_runner()
        players = [
            make_player(1, "wolf"),
            make_player(2, "hunter", alive=False),
            make_player(3, "villager", alive=False),
            make_player(4, "seer", is_human=True),
        ]
        game.state = make_state(
            players,
            human_player_id=4,
            night_kills=[2],
            death_order=[2, 3],
            hunter_shots=[{"hunter": 2, "target": 3}],
        )

        game.run_speech_phase()

        self.assertEqual(game.state["phase"], "speech")
        self.assertIn("不是平安夜", game.state["current_day_facts"])
        self.assertIn("猎人2号发动技能", game.state["current_day_facts"])
        self.assertIn("出局不公开身份", game.state["current_day_facts"])

    def test_human_night_death_pauses_before_speech(self):
        game = self.make_runner()
        game.state = make_state(
            [
                make_player(1, "wolf"),
                make_player(2, "villager", is_human=True),
                make_player(3, "villager"),
                make_player(4, "seer"),
            ],
            human_player_id=2,
            night_kills=[2],
            death_order=[2],
        )

        game.run_day_announcement()

        self.assertTrue(game.state["waiting_for_human"])
        self.assertEqual(game.state["pending_action"], "observer_continue")
        self.assertEqual(game.state["pending_metadata"]["after"], "speech")

    def test_observer_continue_resumes_speech(self):
        game = self.make_runner()
        game.state = make_state(
            [
                make_player(1, "wolf"),
                make_player(2, "villager", alive=False, is_human=True),
                make_player(3, "villager"),
                make_player(4, "seer"),
            ],
            human_player_id=2,
            waiting_for_human=True,
            pending_action="observer_continue",
            pending_metadata={"after": "speech"},
        )
        game.run_speech_phase = lambda: setattr(game, "resumed_speech", True)

        game.continue_game("观战")

        self.assertTrue(game.state["observer_mode"])
        self.assertFalse(game.state["waiting_for_human"])
        self.assertTrue(game.resumed_speech)

    def test_end_game_builds_final_report(self):
        game = self.make_runner()
        game.state = make_state(
            [
                make_player(1, "wolf", alive=False),
                make_player(2, "villager"),
                make_player(3, "seer"),
            ],
            public_log=[
                "☀️ **第1轮 - 白天**\n💀 昨晚死亡：1号",
                "第1天，1号被投票出局",
            ],
        )

        game.end_game("好人")

        report = game.state["final_report"]
        self.assertEqual(report["winner"], "好人")
        self.assertEqual(len(report["roles"]), 3)
        self.assertTrue(report["timeline"])
        self.assertTrue(report["key_events"])
        self.assertTrue(report["review"])


if __name__ == "__main__":
    unittest.main()
