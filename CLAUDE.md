# Why in Clay (repo: NadavKrashin/whyinclay, checked out as `daily-shorts`)

**Start here:** read `HANDOFF.md` for the current state, open items and where to pick up. Update it at
the end of any session that changes the state.

An automated YouTube Shorts studio. Videos are produced by scheduled Claude runs with the
Higgsfield connector, following `channel/why-in-clay.md`. The `waitwhy` app (FastAPI + Postgres)
handles approvals, publishing, analytics and reports.

## Standing instructions from the owner

The owner wants this to run automatically. Do not stop to ask for approval inside these limits:

- Produce episodes and spend Higgsfield credits per `channel/why-in-clay.md` (about 100 credits per 4-scene episode since 2026-10-24; was about 150 for 6 scenes;
  episode, hard cap 200 per episode, pause when the balance is under 200).
- Pick topics, write scripts, retry failed takes and scenes, and choose titles and thumbnails.
- Commit and push work to the working branch.
- Fix any problem the owner reports, in that episode and in the recipe, even if the fix takes the
  episode past its 200-credit cap (the 200-credit balance floor still applies).
- Make judgement calls yourself and report what you decided. Do not end a report with "tell me if
  you want X" or "should I...?" when X is inside these limits: just do it.

Still the owner's call (say so once, plainly, and carry on with everything else):

- Anything that costs real money outside the existing Higgsfield credits (hosting, a plan upgrade,
  buying credits, paid APIs).
- Creating or connecting accounts (YouTube, Instagram, Facebook, TikTok, hosting). Only the owner can
  log in and grant access.
- Sponsorship deals and outreach emails.

Never fabricate facts, sources, analytics, revenue or test results, and never claim something is
published or deployed without checking.

## Skills

`.claude/skills/yt-*` is the MIT-licensed YouTube agent skill pack
(github.com/Jakeschincariol/youtube-agent-skill). Before using it, copy `channel/voice.md` to
`~/.claude/youtube/voice.md`. In automated runs, skip each skill's closing "ship it, or change it?"
question.

## Layout

- `channel/`: the channel recipe, voice file, style formula, episode log and per-episode manifests.
- `config/company.yaml`: business config (autonomous mode, budgets, schedules).
- `waitwhy/`: the app. Tests: `SKIP_SLOW=1 pytest`.
- `docs/`: architecture, setup, deployment, runbook, compliance.

## Branches

`main` is the only branch (the owner's choice, 2026-10-16). Commit and push directly to `main`; don't
create other branches. The app on the owner's Mac mini runs from `main` and pulls it every 15 minutes.
Never force-push `main`.
