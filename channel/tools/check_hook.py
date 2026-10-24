#!/usr/bin/env python3
"""Hook and retention gate for a Why in Clay script, run before any credits are spent.

    python3 channel/tools/check_hook.py channel/episodes/NNN-slug/script_manifest.json

Episodes 1 and 2 kept only 43% and 46% of viewers past the first seconds (Shorts that keep growing
usually hold 60-70%). Both opened with a 22-word statement of a fact, no text on screen for the
first seconds, and no reason to stay to the end. This checks the structure that fixes that (see
"Hook and retention" in channel/why-in-clay.md):

  1. The first sentence is a short punch: at most 10 words, said in the first ~3 seconds.
  2. Scene 1 carries a promise of the ending (`promise`, said word for word in its `vo_line`) that
     names a concrete thing the viewer gets by staying, not "wait for it".
  3. Scene 1 has a card on screen from the first words, so a muted viewer sees the hook at once.
  4. The payoff scene says how it delivers the promise (`delivers_promise`) and its last sentence
     comes back to the hook's words, so the end loops into the start.
  5. The demo or answer the promise points at is not given away before the payoff scene.
  6. The 30-second shape (owner, 2026-10-24): 3-4 scenes, at most 20 words a scene, 75 in all.
  7. The payoff ends on a `comment_question` card: a question viewers want to answer.

The yt-script hook score is printed as advice only: it rewards words like "never" and "lose" and,
by its own notes, barely separates a channel's hits from its misses.
Exit code 0 when every check passes, 1 otherwise. Standard library only.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

MAX_FIRST_WORDS = 10
SCENES = (3, 4)
MAX_SCENE_WORDS = 20
MAX_TOTAL_WORDS = 75
END_WORDS = re.compile(r"\b(end|last|stay|stick around|by the end|finish|final)\b", re.I)
VAGUE_PROMISE = re.compile(r"\b(wait for it|you won't believe|something crazy|something amazing|"
                           r"mind[- ]?blowing|insane)\b", re.I)
STOP = set("""a an the and or but so to of in on at by for with from is are was were be been it its
it's this that these those there there's here here's you you're your yours i i'll we our they them he
she his her what why how when where who just very really all any one each every no not don't can't
can will would could do does did have has had about into over under than then now right""".split())
HOOKSCORE = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "yt-script" / "hookscore.py"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def content(text: str) -> set[str]:
    return {w.rstrip("s") for w in words(text) if w not in STOP and len(w) > 2}


def card_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("*", "")).strip().lower()


def check(manifest: dict) -> list[tuple[bool, str]]:
    blocks = manifest.get("blocks") or []
    if not blocks:
        return [(False, "no blocks in the manifest")]
    first = blocks[0]
    vo = first.get("vo_line", "")
    sents = sentences(vo)
    hook = sents[0] if sents else ""
    results: list[tuple[bool, str]] = []

    results.append((SCENES[0] <= len(blocks) <= SCENES[1],
                    f"{len(blocks)} scenes (the 30-second format has {SCENES[0]}-{SCENES[1]}; 4 is the default)"))
    counts = [len(words(b.get("vo_line", ""))) for b in blocks]
    long = [f"scene {b.get('n', i + 1)}: {c}" for i, (b, c) in enumerate(zip(blocks, counts)) if c > MAX_SCENE_WORDS]
    results.append((not long, f"every scene is at most {MAX_SCENE_WORDS} words" if not long else
                    f"too many words (max {MAX_SCENE_WORDS} a scene, one idea each): {', '.join(long)}"))
    results.append((sum(counts) <= MAX_TOTAL_WORDS,
                    f"{sum(counts)} words in all (max {MAX_TOTAL_WORDS}, about 30 seconds)"))

    n = len(words(hook))
    results.append((0 < n <= MAX_FIRST_WORDS,
                    f"first sentence is {n} words (max {MAX_FIRST_WORDS}): \"{hook}\""))

    promise = (first.get("promise") or "").strip()
    if not promise:
        results.append((False, "scene 1 has no `promise` (the line telling the viewer what the end gives them)"))
    else:
        ok = promise.lower() in vo.lower() and promise.lower() != hook.lower()
        results.append((ok, "promise is said in scene 1 after the first sentence" if ok else
                        f"`promise` must appear word for word in scene 1's vo_line, after the first sentence: \"{promise}\""))
        ok = bool(END_WORDS.search(promise)) and len(content(promise)) >= 3 and not VAGUE_PROMISE.search(promise)
        results.append((ok, "promise points at the end and names something concrete" if ok else
                        f"promise must point at the end (\"stay to the end\", \"at the end\") and name what the viewer "
                        f"gets, never \"wait for it\": \"{promise}\""))

    hook_words = words(hook)[:4]
    early = [o for o in first.get("overlays") or []
             if o.get("type", "card") == "card" and o.get("at")
             and words(o["at"]) and words(o["at"])[0] in hook_words]
    results.append((bool(early), "a card appears on the first words" if early else
                    f"scene 1 needs a card whose `at` starts within the first four words ({' '.join(hook_words)})"))

    payoff_i = next((i for i, b in enumerate(blocks) if b.get("arc_role") == "payoff"), len(blocks) - 1)
    payoff = blocks[payoff_i]
    results.append((bool((payoff.get("delivers_promise") or "").strip()),
                    "payoff scene says how it delivers the promise" if payoff.get("delivers_promise") else
                    "the payoff scene needs `delivers_promise`: what the viewer sees or does there that the promise named"))
    last = (sentences(payoff.get("vo_line", "")) or [""])[-1]
    shared = content(hook) & content(last)
    results.append((bool(shared), f"last line loops back to the hook ({', '.join(sorted(shared))})" if shared else
                    f"the last sentence should come back to the hook's words so the end loops into the start: \"{last}\""))

    question = (payoff.get("comment_question") or "").strip()
    cards = [o for o in payoff.get("overlays") or [] if o.get("type", "card") == "card"]
    shown = bool(question) and bool(cards) and card_text(cards[-1].get("text")) == card_text(question)
    results.append((question.endswith("?") and shown,
                    "payoff ends on the comment question card" if question.endswith("?") and shown else
                    "the payoff needs `comment_question` (a question viewers want to answer, ending in \"?\") "
                    f"and its last card must show that text: \"{question}\""))

    early_demo = [b.get("n", i + 1) for i, b in enumerate(blocks[:payoff_i])
                  if re.match(r"\s*(try it|try this|do it now)\b", b.get("vo_line", ""), re.I)]
    results.append((not early_demo, "the demo is saved for the payoff" if not early_demo else
                    f"scene {early_demo[0]} gives the viewer the demo before the payoff; move it to the payoff scene"))
    return results


def advisory_score(vo_line: str) -> str:
    if not HOOKSCORE.exists():
        return ""
    r = subprocess.run([sys.executable, str(HOOKSCORE), "--json", "--hook", vo_line], capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)[0]
        return f"advice: hookscore {s['verdict']} {s['band']} ({s['formula']})"
    except (ValueError, IndexError, KeyError):
        return ""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    manifest = json.loads(Path(argv[0]).read_text())
    results = check(manifest)
    for ok, msg in results:
        print(f"  {'ok ' if ok else 'FIX'}  {msg}")
    tip = advisory_score((manifest.get("blocks") or [{}])[0].get("vo_line", ""))
    if tip:
        print(f"       {tip}")
    failed = sum(1 for ok, _ in results if not ok)
    print("hook check passed" if not failed else f"hook check FAILED: {failed} to fix before narration")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
