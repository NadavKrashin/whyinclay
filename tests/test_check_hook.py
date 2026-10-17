"""channel/tools/check_hook.py: the hook and retention gate a production run passes before narration."""
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_hook", ROOT / "channel" / "tools" / "check_hook.py")
check_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_hook)

GOOD = {"blocks": [
    {"n": 1, "arc_role": "hook",
     "vo_line": "You're blind in one spot right now. Stay to the end and you'll find yours in five seconds.",
     "promise": "Stay to the end and you'll find yours in five seconds.",
     "overlays": [{"type": "card", "text": "A hole in your *vision*", "at": "You're blind"}]},
    {"n": 2, "arc_role": "build", "vo_line": "Behind each eye, the nerve to your brain leaves a patch with no light sensors."},
    {"n": 3, "arc_role": "build", "vo_line": "That patch is bigger than you'd guess, and it sits just off the middle."},
    {"n": 4, "arc_role": "build", "vo_line": "So why don't you see a black hole there all day?"},
    {"n": 5, "arc_role": "turn", "vo_line": "Your brain paints over it with whatever is around it."},
    {"n": 6, "arc_role": "payoff",
     "vo_line": "Cover your left eye, stare at the cross, lean in, and the red dot vanishes. That's your blind spot.",
     "delivers_promise": "the viewer runs the cross-and-dot test and watches the dot vanish"},
]}


def failures(manifest):
    return [msg for ok, msg in check_hook.check(manifest) if not ok]


def test_good_hook_passes():
    assert failures(GOOD) == []


def test_episode_2_as_shipped_fails_for_the_reasons_it_lost_viewers():
    ep2 = json.loads((ROOT / "channel/episodes/002-blind-spot/script_manifest.json").read_text())
    msgs = " | ".join(failures(ep2))
    assert "promise" in msgs
    assert "first four words" in msgs
    assert "scene 4 gives the viewer the demo" in msgs


def test_long_first_sentence_fails():
    m = copy.deepcopy(GOOD)
    m["blocks"][0]["vo_line"] = ("Each of your eyes has a small area in your vision where you see nothing at all. "
                                 + m["blocks"][0]["promise"])
    assert any("first sentence" in f for f in failures(m))


def test_vague_promise_fails():
    m = copy.deepcopy(GOOD)
    m["blocks"][0]["vo_line"] = "You're blind in one spot right now. Wait for it, stay to the end."
    m["blocks"][0]["promise"] = "Wait for it, stay to the end."
    assert any("never \"wait for it\"" in f for f in failures(m))


def test_promise_must_be_spoken():
    m = copy.deepcopy(GOOD)
    m["blocks"][0]["promise"] = "Stay to the end and you'll see something nobody tells you."
    assert any("word for word" in f for f in failures(m))


def test_payoff_must_loop_back_and_deliver():
    m = copy.deepcopy(GOOD)
    m["blocks"][5]["vo_line"] = "And that is how it works."
    del m["blocks"][5]["delivers_promise"]
    msgs = " | ".join(failures(m))
    assert "delivers_promise" in msgs and "loops into the start" in msgs
