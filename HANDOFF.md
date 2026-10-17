# Handoff: where to pick up

Read this first in any new session, then `CLAUDE.md` and `channel/why-in-clay.md`. Last updated 2026-10-17.

## State right now

- **Episode 2 is finished (v3):** "Why You Never Notice Your Blind Spot" (slug
  `why-your-brain-fills-in-your-blind-spot`, status `produced_not_published`), made 2026-10-16 on the
  owner's request and reworked the same day after the owner's review (captions too small and low,
  cards templated, narration stiff, hook not understandable). 185.2 credits in total (170.05 + 15.15
  for the rework).
  - Video: https://d2ol7oe51mr4n9.cloudfront.net/user_3GwgNHZqxuXDkDZnfXEEDAP3y0F/5092e338-1cff-4f8e-bb3c-6758ed3e41ee.mp4
    (v3, 2026-10-17, 54.5 s; superseded: v2 .../55ccc4f6-3d7a-4d2c-a6bc-2ba59b495906.mp4, v1 .../77b23ae6-5293-4435-aaef-df1041b4203c.mp4)
  - v3 fixes the Mac's hold on v2 (1.59 s of silence between scenes 1 and 2) at 0 credits: each scene
    clip is trimmed to its line plus about 0.45 s each side (`channel/tools/trim_dead_air.py`, recipe
    step 6a), then captions and overlays are redone (`overlays.py --assembly`). Longest silence is
    0.99 s. `scripts/qc_episode.py 2` on the hosted file: "would be approved and posted
    automatically (score 95.5)". The Mac picks up the new `video_url` on its next import.
  - **New narrator: Bram** (owner's pick after an audition, 2026-10-16). Kevin read plain wording at
    3.1-3.8 words/s and could not fill the 10-second scenes; Bram reads it at about 2.6 words/s.
  - Files: `channel/episodes/002-blind-spot/` (manifest + assets). Sandbox working files: `~/ep2/`.
  - New overlay diagram `field` in `channel/tools/overlays.py`: one eye's visual field drawn to scale
    (blind spot 15 degrees out, about 5.5 x 7.5 degrees; moon 0.5 degrees).
- **Episode 1 is live on YouTube, public** since its 2026-10-16 19:00 Israel slot (reported by the
  owner). TikTok is the owner's manual post; Instagram is off while the account appeal is open.
  "Why Traffic Jams Appear Out of Nowhere", v5.
  - Video: https://d2ol7oe51mr4n9.cloudfront.net/user_3GwgNHZqxuXDkDZnfXEEDAP3y0F/e3fa913d-9646-4721-9e23-5613ac164da4.mp4
  - Older cuts and the reasons for each fix are listed in `channel/episodes.json`.
  - All four problems the owner reported are fixed: spoken words at 0:11 and 0:31, a red dot at 0:17
    and a reversing car at 0:37.
  - v5 adds 14 on-screen text and diagram overlays (owner request: "more text and explanatory animations").
- **Production is automatic.** The scheduled task `trig_01CEgLKfbqhP4NayT7eajnhN` ("Why in Clay
  episode") runs Mon/Wed/Fri at 08:58 Asia/Jerusalem; first run Mon 2026-10-19.
  - It fires into the production session `session_01DtafAJxfTY1uP7XuuBwz3G` ("Why in Clay: episode
    production", tag `why-in-clay:production`, Auto mode, checkout `/home/user/whyinclay` on `main`).
    Created 2026-10-16 18:40 UTC. Checked then: Higgsfield `balance` and a sandbox command both ran
    **without a permission prompt** (the owner had set the Higgsfield connector's tools to "Always
    allow", and the repo's `.claude/settings.json` allows them).
  - Why it was replaced: the first production session (`session_019RDtGY8g3sTANrfbpeBBTg`, now titled
    "old production session (retired)") started before those settings existed and kept asking the owner
    to approve every Higgsfield sandbox command. Its task `trig_0182qs4pQ7PAjPxr7pJdhums` is disabled.
    Connector and settings changes only reach sessions started after them.
  - Each run follows `channel/why-in-clay.md`, which is the source of truth for voice, captions and cards.
  - Why a dedicated session: scheduled tasks that start a fresh session can't attach connectors on
    this account, so a fresh session would have no Higgsfield.
  - If the production session is archived, the task stops. To fix it, create a new session from the
    repo with `create_session` (permission_mode auto), confirm Higgsfield `balance` and a sandbox
    command run there without a prompt, then point a new task at it with `create_trigger` and
    `persistent_session_id`, reusing the prompt (`list_triggers`), and disable the old task.
- **Credits:** 400.7 on the Higgsfield Plus plan after episode 2's rework (2026-10-16), enough for about two
  more episodes before the 200 floor pauses runs. An episode costs about 150, and runs
  pause by themselves under 200. Buying credits or changing the plan is the owner's call.
- **App: running on the owner's Mac mini** (reported by the owner 2026-10-16; this cloud session can't
  reach the Mac, so those details are as reported, not checked from here).
  - Dashboard: https://atlass-mac-mini-2.tailf9f0e7.ts.net. Reachable only on the owner's tailnet
    (Tailscale Serve; Funnel off). Login is user `ceo`; the password is in
    `~/.why-in-clay-dashboard-password` on the Mac.
  - It runs **natively, not in Docker**:
    - Code: `~/daily-shorts`, on branch **`main`**.
    - Postgres: a Homebrew service that only accepts connections from the Mac itself.
    - Three launchd services start at login and restart if they crash: dashboard (listens on localhost
      only; Tailscale forwards to it), worker and scheduler.
    - Code updates deploy themselves: every 15 minutes `scripts/mac-mini-update.sh` pulls `main` and,
      if anything besides episodes or docs changed, migrates and restarts the services. A push to
      `main` is live on the Mac within about 15 minutes. Details: `docs/deploy-mac-mini.md`.
    - Logs: `~/daily-shorts/logs/`.
  - A separate `whyinclay` folder on the Mac is an older copy on the other branch; it isn't used.
  - The owner's Cloudflare tunnel and studio.animoment.co.il are separate and must stay untouched.
  - Config: `production_source: claude_runs`. Every 30 minutes the `import_episodes` job turns
    `channel/episodes.json` entries into videos, runs QC, then auto-approves and schedules them.
  - Episode 1 is imported (QC 95.5) and scheduled.
  - `dry_run_mode` is **off** (owner, 2026-10-16 afternoon): posts are real. Episode 1 was scheduled
    while dry-run was on; `publish()` now re-files such jobs under the current mode, so its posts are
    recorded as real ones.
- **Repo: `NadavKrashin/whyinclay`, one branch: `main`** (owner's choices, 2026-10-16).
  - Everything, including the production runs, commits and pushes straight to `main`, and the Mac
    pulls it every 15 minutes. Never force-push `main`.
  - The repo was renamed from `daily-shorts`; GitHub redirects the old URL. Local checkouts keep the
    folder name `daily-shorts`: `/home/user/daily-shorts` in cloud sessions, `~/daily-shorts` on the
    Mac, whose launchd services use that path.
  - The old `claude/happy-cannon-dzuzwj` branch is deleted, and `main` is the default branch
    (checked 2026-10-16).
  - The scheduled task's prompt now says `main` (applied 2026-10-16 on the owner's word).
- **Next scheduled run:** Mon 2026-10-19 08:58 makes episode 3 (next topic by score:
  `why-airplanes-fly-curved-routes`). Pushed episodes reach the Mac's import within about 45 minutes
  (15-minute pull + 30-minute import).

- **Dashboard redesign for phones (2026-10-17, owner request: "not UX at all, especially on phone";
  wants to see when the data last came in and from where; graphs where possible).**
  - Phone layout: bottom tab bar (Home, Analytics, Calendar, Approvals, More), compact header, every
    table turns into one card per row under 760 px, 16 px inputs (no iOS zoom), no horizontal scroll
    (checked at 390 px with Playwright in light and dark).
  - Freshness: every Home/Analytics page starts with "Views updated X ago (time) from YouTube, Instagram
    · next update in Y · Refresh". A "Where the data comes from" list (Home and Analytics `#sources`)
    shows each source (per-platform stats, new episodes, costs, revenue, health, Mac scheduler) with
    its origin, last arrival, next run, last run's errors and an up to date / late / never state.
    Logic: `waitwhy/datasources.py`. TikTok is shown as "not collected" (manual posting, no API).
  - Charts (Chart.js 4.4.1 from cdnjs, shared helpers in `web/static/charts.js`; platform colours are
    fixed: YouTube blue, Instagram orange, TikTok aqua): views over time per platform (6-hour buckets
    while history is under a week, then daily), views by video, likes per 1,000 views, average % watched,
    costs vs revenue by month, Higgsfield credits per episode, spend by provider.
  - Stats are now collected every 6 hours (was daily at 07:30), and the Refresh button re-reads posts
    whose last reading is over 15 minutes old. YouTube quota impact is tiny (about 2 units per post).
  - Not yet seen on the Mac with real data: check it from the phone after the Mac pulls `main`.
  - Agents page has a **Schedule** table (`#schedule`): every timed job from `company.yaml` in plain words,
    with next run, last run and its error, and what it does. Settings links to it from the raw config.

- **Topics (2026-10-17, owner asked whether trend fetching ever happens): it didn't.** The app's
  `trend_discovery` agent only runs in `production_source: app` mode, asks the LLM to brainstorm (no
  real trend data), and writes to the Mac's database, which the Claude runs never read. The runs pick
  from `seeds/topics.json` (36 hand-made ideas). Fix: recipe step 1 now refreshes that list on Monday
  runs, or when fewer than 10 unused topics remain, from Shorts that beat their channel's median by 2x+
  (yt-viral skill, public listings via yt-dlp, web search as fallback). New entries carry `added_on`
  and `inspired_by`. The dashboard hides the trend-discovery button in this mode and says the Pipeline
  "Add topic" form doesn't reach the runs. First refresh: Mon 2026-10-19 run; check it worked.

- **Database (2026-10-17):** Homebrew Postgres on the Mac, database `waitwhy`. Nightly `db_backup` (03:30)
  writes `pg_dump` files to `~/daily-shorts/backups/` (unless `BACKUP_DIR` is set in the Mac's `.env`) and
  keeps the newest 14. No S3/R2 bucket, so backups sit on the same disk as the database: a dead disk
  loses both. Not checked from here whether the backup job succeeds on the Mac (`pg_dump` must be on the
  worker's PATH); the Agents page Schedule table shows its last run.
  **Never just delete the database:** the importer would re-import every `produced_not_published`
  episode and post it again. Episode 1 is now `status: published` with a `posted` map in
  `episodes.json`, which the importer skips. **Episode 2: set it to `published` too once its posts
  are confirmed live** (it was due 2026-10-17 19:00 Israel; not verified from here).

## What the owner still has to do (details in `docs/setup-guide.md`)

1. Don't archive the "Why in Clay: episode production" session, and keep it on Auto mode. I can't
   change my own permissions: writing `.claude/settings.json` was blocked as self-modification. Don't
   try to work around that.
2. Decide on credits: top up or upgrade, or cut the cadence.
3. ~~Claim the accounts~~ Done 2026-10-16: YouTube, Instagram (Professional, Education) and TikTok.
   There is no Facebook Page, so Facebook publishing is off.
4. ~~Deploy the app~~ Done 2026-10-16 on the Mac mini (see "App" above). Still to confirm: the
   dashboard opens from the owner's phone over Tailscale.
5. Platform credentials: YouTube and Instagram connected 2026-10-16 (see "Platform accounts").
   Still open:
   - restart the services and confirm Settings shows youtube ✓ and instagram ✓
   - get Google **Publish app** to work, then rerun `scripts/youtube_auth.py` (until then the token
     lapses every 7 days)
   - ~~apply for the YouTube API audit~~ Submitted 2026-10-16; waiting for Google
   - TikTok stays a manual handoff
   No R2 bucket is needed.
6. ~~Turn off `dry_run_mode`~~ Done 2026-10-16 (as reported by the owner).

When the owner reports one of these done, help verify it: run the health check and look at the
dashboard Agents page. Never claim it is live without checking.

## Platform accounts (2026-10-16)

- **Instagram restored (2026-10-16 evening):** the suspension appeal succeeded and
  `platforms.instagram.enabled` is true again. Videos that skipped Instagram while it was off (episodes
  1 and 2) are queued by `publication.service.catch_up_platforms`, which runs with every
  `import_episodes` job and gives each its own next free slot. If the post fails with an auth error, the
  access token died with the suspension: generate a new one in the Meta app and put it in `.env`.
  `scripts/check_instagram.py` (run on the Mac) checks the token without posting. Owner ran it after the
  restore (2026-10-16): "All good", so the token survived the suspension.
- Alerts: `notifications.channels` is `[log, telegram]`. Telegram works once the owner runs
  `scripts/telegram_setup.py` on the Mac (until then the telegram channel just logs "not configured").
  TikTok "Action needed" alerts link to `dashboard_url`/calendar.
- **Held episodes:** the Mac's import check is `importer.evaluate`; `scripts/qc_episode.py` runs the same
  check anywhere. A failed check holds the episode (NEEDS_REVISION, never posted) and, for episodes from
  the production runs, raises a high alert ("Episode held, not posted"). Production runs check before
  pushing (recipe step 7b) and fix held episodes before making new ones (step 0). Episode 2 v2 was held
  2026-10-16 for 1.6 s of silence at 9.3-10.9 s; v3 (2026-10-17) passes the check.
- **Instagram video link (fixed 2026-10-17):** episode 1's first Instagram post failed because
  `PUBLIC_BASE_URL` on the Mac held a LAN address, which the app offered to Instagram. The owner's Mac
  session cleared it and retried; the Reel is live (instagram.com/reel/Dek_itADRNh). The code now prefers
  the episode's HTTPS CDN link and never offers a non-HTTPS link; the setup script leaves the variable empty.
- **Tokens in logs (fixed 2026-10-17):** httpx logged every request URL, including Instagram's
  `access_token`. Logging now masks token parameters and keeps httpx at WARNING. Older lines in
  `~/daily-shorts/logs/` on the Mac still contain the token (local only; `logs/` is git-ignored).
- **Rescheduling from a cloud session:** set `publish_at` (ISO time with offset) on the episode in
  `channel/episodes.json` and push. The Mac's next import moves that episode's waiting posts to that
  time, once per value (`importer.apply_publish_at`). Episode 2 was moved this way to Sun 2026-10-18
  00:00 Israel (21:00 UTC Sat) after weekend slots were turned on.
- Captions: `publishing.adapters.post_text` builds every platform's caption: tags already in the
  caption are merged, duplicates dropped, at most 5 tags, `#shorts` only on YouTube. (Before
  2026-10-16 the TikTok package and Instagram doubled the tags.) The TikTok package's `cover.jpg` is a
  1080x1920 JPEG: the episode's `cover_url` if the run made one, else the landscape thumbnail
  letterboxed on a blurred copy (`publishing/cover.py`).
- TikTok: the owner posts by hand from the dashboard's download package (owner's choice,
  2026-10-16). Automatic posting via Upload-Post (Basic plan, $24/mo then) is the chosen future option
  once the channel earns money. The comparison and switch steps are in `docs/setup-guide.md` → TikTok.
  Don't build the adapter until the owner asks.
- The owner created the YouTube, TikTok and Instagram accounts for Why in Clay. There is no Facebook
  Page, so `platforms.facebook.enabled: false`.
- Connecting them is the owner's part (`docs/setup-guide.md` step 6). YouTube uses
  `scripts/youtube_auth.py`.
- Instagram: connected 2026-10-16 through a Meta app with no business portfolio ("Why In Clay-IG"),
  with @whyinclay as an Instagram Tester. The 60-day token is renewed every Monday by the
  `instagram_token_refresh` job (`waitwhy/publishing/tokens.py`). The renewed token lives in
  `data/state/instagram_token.json` (mode 600), never in the database, because the Settings page shows
  every DB setting. Its expiry date is in the `instagram_token_status` setting.
- Instagram fetches each video from a public URL. For imported episodes that is the Higgsfield CDN
  link in the version manifest (`source_url`): the same bytes that passed QC. See
  `publishing.service.public_video_url`. No R2 bucket is needed.
- YouTube: connected 2026-10-16 with `scripts/youtube_auth.py` (channel "Why In Clay", a brand
  account). The Google app was still in "Testing", so the refresh token lapses after 7 days until the
  owner gets **Publish app** to work and reruns the script. Episode 1's upload came out public
  before the audit was approved (see the audit section).

## YouTube API audit (submitted 2026-10-16)

- The owner submitted Google's YouTube API Services compliance audit form on 2026-10-16. The first
  attempt hung while loading; the second (new tab, small files, optional uploads skipped) showed
  "Your email has been sent. Thank you for submitting the YouTube API Services Form."
- Waiting for Google's reply (it and any follow-up questions go to whyinclay@gmail.com). Reviews
  usually take days to weeks.
- Google says unaudited projects' uploads are forced to private, but episode 1 came out **public** on
  2026-10-16 (owner report). The adapter reads the real status back, so a later private upload would be
  recorded as `private_uploaded` with a "make public in YouTube Studio" task.
- The form answers are in a Google Doc in krashin23's Drive ("Audit form answers").
- Materials:
  - privacy policy and terms of service: Google Docs in krashin23's Drive, published to the web; the
    privacy policy is also in `docs/privacy-policy.md`
  - diagrams: `docs/audit/`
- What the form declared, which the app must stay within:
  - client "Why in Clay Publisher": internal, single user, only the Why In Clay channel
  - endpoints: `videos.insert` (at most 1 a day), `videos.list`, `channels.list`, Analytics `reports.query`
  - default 10,000 units/day quota; no `search.list`
- Any change to that use (other channels, new endpoints, other users) must be reported to YouTube
  and approved first.
- Promised in the privacy policy: if the owner revokes access, stored YouTube statistics are deleted
  within 30 days. This is a manual step today.
- When Google replies, draft answers for the owner from this section. Never invent capabilities or
  numbers.

## Open quality items (fix in future episodes, not urgent)

- **Hooks are now a hard gate (owner, 2026-10-18).** YouTube Studio showed only 43% (episode 1) and
  46% (episode 2) of viewers staying past the first seconds, against 60-70% for Shorts that keep
  growing. Every new script follows "Hook and retention" in `channel/why-in-clay.md`: a punch of at most
  10 words, then a spoken promise of what the end shows ("Stay to the end and you'll find yours in five
  seconds"), the promised demo or answer held back until scene 6, a re-hook in scene 4 or 5, text on
  screen from the first word, and a last line that loops to the first.
  `python3 channel/tools/check_hook.py <script_manifest.json>` must pass before narration; episodes 1
  and 2 both fail it as shipped.

- Episode 1's thumbnail text is 5 words (limit 3).
- The red strip on the scene-5 chart is never named by the narration.
- The `ring`/`wave` overlay diagrams are traffic-specific. For a new topic, add a diagram type to
  `channel/tools/overlays.py` drawn from a real model or real numbers, or use cards and chains.

## How things work (gotchas learned the hard way)

- **Higgsfield sandbox:**
  - It refuses pasted base64. Move files with `media_upload` + curl PUT (header `If-None-Match: *`)
    + `media_confirm`, then curl the CDN URL.
  - Foreground commands time out at 60 s; use `background: true` and poll.
  - Episode 1's working files are in the sandbox under `~/clay/` (they may expire).
- **Narration:** use the plain `[curious]` tag only. Descriptive tags get spoken aloud.
  - The narrator is Bram (`549ff70a-...`); he fits 20-23 plain words into a 10-second scene. Long
    lines (23 words) can run over 9.5 s: trim them, don't pad. Never use textbook words to fix pace.
  - Captions: `--profile default` (the faceless profile pins captions low), 3 words / 16 characters
    a cue so one long word can't shrink every caption. Exact flags in the recipe.
  - Moving the manifest into the sandbox: a plain `cat > file <<'EOF'` heredoc or a small python
    patch in the command works fine (only base64 is refused). Keep the local and sandbox copies'
    md5 equal.
  - `channel/tools/check_takes.py` is the real check; the workflow's `verify_takes.py` missed bad takes.
- **Overlays:** `python3 overlays.py manifest captions.json in.mp4 out.mp4 --still T` renders previews.
  - Run it without `--still` for the full render, about 2 minutes in the background.
  - Timing comes from the `at`/`until` phrases looked up in `final.words.json`.
- **Tests:** Postgres data lives in `/var/lib/postgresql/wwdata`.
  - Start it: `su postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D /var/lib/postgresql/wwdata -l /var/lib/postgresql/wwdata/log start"`.
  - Run: `SKIP_SLOW=1 .venv/bin/python -m pytest -q`.
  - Databases: `waitwhy`, `waitwhy_test`, `waitwhy_mig` (scratch). A fresh container may need Postgres
    and the venv reinstalled.
- **Times:** the Mac's Postgres runs on Israel time; `db.get_engine` forces UTC sessions so labels
  saying UTC are true. The Calendar shows owner time (`timezone` in config) and UTC side by side.
- **Docker image:** it installs the package into site-packages, so it relies on `WAITWHY_ROOT=/app`.
  The compose file mounts `./channel` read-only.

## Recent commits (`main`)

- `6e73cb6`: overlays, episode importer, Docker root fix, config-copy fix, setup guide.
- `cc49ae9`: episode 1 v4 (red dots removed).
- `fd7c68c`: narration fixes + `check_takes.py`.
- `0aadee6`: rebrand to Why in Clay, autonomous mode, recipe, yt skill pack.
