# Why in Clay: production recipe

The channel's locked look, voice and format, and the exact steps a scheduled run follows to make
one episode with no human in the loop. Episode 1 (`channel/episodes/001-traffic-jams/`) is the
worked example: copy its file shapes.

## Channel DNA (locked; change only when the owner asks)

| | |
|---|---|
| Name | Why in Clay (handle `@whyinclay`) |
| Promise | One everyday mystery, explained in 30 seconds of handmade clay |
| Format | 9:16, **4 scenes** (owner, 2026-10-24; was 6) generated as 10 s clips, five hard-cut shots per scene (cuts at 2/4/6/8 s); each clip is trimmed to its line (step 6a), so a finished episode runs **about 30 s** (25-35 s) |
| Look | Higgsfield explainer preset **Claymotion** (`1de0f39e-c602-4b00-b54a-38440c7f63f7`). Style key image job `313e8a54-0203-4435-9f21-af07936fc570`. Style formula: `channel/style.txt`, pasted verbatim into every image and video prompt |
| Motion token | `smooth simple handcrafted motion, subtle stop-motion feel` (dimensional style: no "3D render" in negatives) |
| Palette | sky blue, grass green, warm sand, cream; ONE signal-red accent reserved for the episode's through-line prop and warning marks |
| Narrator | **Bram** (owner's pick, 2026-10-16), `voice_id 549ff70a-3ee7-4f04-a4d9-89a24fab7709`, `voice_type preset`, model `text2speech_v2` variant `elevenlabs`. Episode 1 used Kevin (`f1373f24-...`), who read plain wording too fast for the 10-second scenes |
| Prompt format (every line) | `[curious] {line}`: one plain tag, nothing else (`[excited]` made Kevin rush past the rate limit). Descriptive brackets and per-line moods can get SPOKEN aloud (episode 1: "Matter 2008", "Supposed to you, here's the surprise") |
| Captions | large and raised clear of the Shorts UI (owner, 2026-10-16: the old ones were too small and too low), sentence case, max 3 words and 16 characters a cue: `audio_to_captions.py ... --max-words 3 --max-chars 16`, then `subtitle_paper_burn.py --style bold --no-caps --font-key montserrat --stroke-frac 0.045 --profile default --single-line --fontsize-frac 0.040 --bottom-frac 0.32 --maxw-frac 0.72`. Use `--profile default`: the `faceless` profile pins captions at 83% height whatever `--bottom-frac` says. The tool picks ONE size for the whole video that fits the longest cue, so one long word ("photoreceptors") shrinks every caption; that is why cues are capped at 16 characters |
| On-screen text + diagrams | `channel/tools/overlays.py`: torn-paper scraps with a wobbly edge and a slight tilt (not vector boxes), sentence case, ink brown with one signal-red key word; count-up stats, cause-and-effect chains and animated diagrams, all in the upper third and timed to the spoken words. About one per scene. The clay scenes themselves stay text-free (video models garble letters) |
| Thumbnail | 16:9, `nano_banana_pro` 4k, clay medium, people-free, hook text 3-4 words baked in and checked letter for letter |

## Writing rules

- **Plain, spoken words (owner, 2026-10-16).** Write the way you'd explain it to a friend. Never
  reach for textbook or thesaurus words ("photoreceptors", "compensates", "considerably",
  "positioned rightward") to slow the narrator down: episode 2's first cut sounded AI-written because of them.
  Numbers are written as words.
- **Pace and length (owner, 2026-10-24).** 15-19 plain words per scene (Bram reads 2.6-2.8
  words/second, so about 6-7 s a scene once trimmed) and **at most 75 words in the whole episode**.
  Each scene says ONE thing. If a line needs a second idea, it belongs in another episode. (Kevin, the
  episode-1 voice, ran 3.1-3.8 words/second; that is why the narrator changed.)
- **Why 30 seconds.** Measured 2026-10-24 on episodes 1-4: on YouTube, viewers were down to 54% by
  0:11 and 38% by 0:16 (episode 2), only 10% of episode 1's viewers reached its end, and YouTube rated
  its retention at about 0.4 of similar Shorts through the middle. Instagram gave every Reel one test
  batch of about 110 people, who watched 6-15 s of 55. Episodes 3 and 4 passed the hook check and did
  no better: people leave during the explanation, not at the first line. A 30 s Short that is watched
  to the end and replayed is what both platforms push.
- **Show, don't lecture.** The clay does the explaining; the voice points at it. Every build line
  names something the viewer SEES happen in that scene ("The metal spoon pulls the heat out of your
  finger"), never a textbook step with nothing on screen ("Inside stars, small atoms get squeezed
  into bigger ones"). No numbers or names the picture doesn't show. Something visibly changes on
  every cut.
- **Hook and retention (owner, 2026-10-18).** Episodes 1 and 2 kept only 43% and 46% of viewers
  past the first seconds; Shorts that keep growing hold 60-70%. Both opened with a 22-word fact
  ("Each of your eyes has a blind spot. There's an area...") that gave no reason to stay. Every
  episode now follows this shape, and `python3 channel/tools/check_hook.py script_manifest.json`
  must pass before narration (step 2):
  - **First sentence: a punch, max 10 words, said in the first 3 seconds.** A claim that clashes
    with what the viewer believes, said straight at them, about them or their world right now:
    "You're blind in one spot right now." / "This traffic jam has no cause." Never a textbook
    fact, a definition, a date or a name. A first-time viewer must get it on one listen (episode
    2's "wider than ten moons" confused the owner).
  - **Second sentence: the promise of the ending**, recorded as the block's `promise` and said word
    for word: "Stay to the end and you'll find yours in five seconds." / "Stay to the end and you'll
    see how one driver can stop it." It names a concrete thing the viewer gets at the end: a test
    they can do on themselves, a reveal they can see, the one move that fixes it. Never vague bait
    ("wait for it", "you won't believe"). Breaking a promise teaches viewers to swipe, so only
    promise what scene 4 really shows. Keep the promise short (about 8-10 words) so scene 1 stays
    under 20 words.
  - **Hold the promised thing back until scene 4.** Scene 2 makes the question sharper, it doesn't
    answer it: no history or names unless they are the surprise (episode 2's "Edme Mariotte found
    it" was a detour), and no "Try it" before the payoff (episode 2 handed over its blind-spot test
    in scene 4 of 6, so nobody needed the ending).
  - **Twist in scene 3:** one line that turns the question around before the answer ("But that's
    not the weird part." / "So why don't you see a black hole?").
  - **Payoff (scene 4) delivers the promise on screen** (record how in the block's
    `delivers_promise`), and its last sentence comes back to the hook's words so the end flows into
    the start and rewatches loop.
  - **End on a question people want to answer**, recorded as the payoff block's
    `comment_question` and shown as its last card (on screen, not spoken, so it costs no time):
    a quick guess or a personal check, never "like and subscribe" ("Did yours vanish too?" / "Which
    one did you think was colder?"). It is also the first line of the `caption` and `description`
    (step 8). Episodes 1-4 got zero comments, shares or saves on every platform.
  - **Text from frame one:** scene 1's first card starts on the first words (its `at` is in the
    first four words), in different words from the voice, so muted viewers get the hook at once.
    Shot 1 opens on the most striking image already moving: no establishing shot, no slow push-in.
  - Write five candidate hook pairs (punch + promise), read them out loud, and pick the clearest.
    `python3 .claude/skills/yt-script/hookscore.py hooks.txt` is a second opinion only: it rewards
    words like "never" and "lose" and rated every hook above WEAK, including the good ones.
- **Through-line:** one signal-red element that changes state in every scene and resolves in the
  payoff. It must be something the viewer already understands (brake lights, a warning sign, a
  thermometer) or something the narration names. Abstract symbols the voice never explains read as
  random (episode 1's lone red clay dot at 0:17 confused the owner).
  The script validator requires `through_line.asset` in every block's `assets_used`, so make it a
  prop that is naturally in every scene (episode 1's final through-line is the brake lights on the
  sand car).
- **Direction of travel:** for anything that moves, state which way it faces and moves in the shot
  text, and put the reverse motion in the negatives (episode 1 had a car reversing at 0:37).
- **Arc (4 scenes):** hook + promise (1), build (2), twist (3), payoff (4). The payoff answers the
  hook, keeps the promise, loops back to the first line and ends on the `comment_question` card.
  Use `arc_role` values `hook`, `build`, `turn`, `payoff`.
- **On-screen text and diagrams (owner request, every episode):** give every block an `overlays`
  list (format in the `overlays.py` docstring; episode 2 is the worked example). About ONE per
  scene; a card has to earn its place (owner, 2026-10-16: two or three echo cards per scene looked
  templated and AI-made):
  - the hook names the mystery in plain words (`card`);
  - a number the voice says gets a `stat`;
  - a mechanism gets a diagram or a `chain`, at least once per episode;
  - the payoff restates the answer, then the `comment_question` card closes the episode.
  Keep each `chain` step to about 12 characters ("Heat *leaves*", "+ neutrons"): the three boxes share
  one row and shrink to fit, so a longer step comes out too small to read on a phone (episodes 3 and 4
  both had to be cut down after the preview).
  Skip cards that only echo the voice ("HERE'S WHY", "HERE'S THE SURPRISE"). Write cards in sentence
  case, in words a person would say ("No light sensors, so it's blind", not "ZERO LIGHT
  DETECTORS"), at most 2 short lines, one red key word. Text never adds a new claim.
  `ring` and `wave` are traffic-specific; for another topic, add a diagram type to `overlays.py` that
  is drawn from a real model or real numbers, or use cards and chains.
- **Explanatory clay shots:** in build and turn blocks, use at least one diagram-like clay shot
  (a clay chart board, a cutaway, arrows stamped in clay) as in episode 1's scene 5, with no letters.
- **Facts:** every claim traces to a primary or reputable source found this run. Put the URLs in
  the manifest's `sources`. Prefer "roughly" over a false-precise number. Never invent a figure,
  study or quote. Skip topics with any `risk_flags`.
- **Title and thumbnail:** run `python3 .claude/skills/yt-package/title.py --title "..." --thumb "..."`
  and fix every `x` it reports when you can. The thumbnail must not repeat the title's words.
- Use the yt-* skills' rules and tools, but skip their closing "ship it, or change it?" question.
  Scheduled runs never stop to ask.

## Run steps

Each step names the Higgsfield workflow script to use. Load `get_workflow_instructions` for
`faceless-video`, `narration`, `video-montage` and `thumbnail-generation` at the start of a run and
follow them, except where this file says otherwise.

0. **Held episodes first.** Run `python3 scripts/qc_episode.py --all` (needs `pip install -e .` once,
   and ffmpeg). It runs the exact check the owner's Mac runs on import. Any episode it reports as HELD
   was never posted: fix that one first (re-edit in the sandbox where possible, which costs no
   credits), check it again, update its `video_url`, and push, before starting a new episode.
   **Credit guard.** Call `balance`. If below 200 credits, stop: make nothing new and report
   "paused: N credits left". A 4-scene episode should cost about 100 credits (6-scene episodes cost
   about 150); record the real figure. Never buy credits or change the plan.
1. **Topic.** Take the highest-scoring topic in `seeds/topics.json` whose slug is not in
   `channel/episodes.json` and has no `risk_flags`. Score = the weighted sum of its `scores` using
   `topic_scoring_weights` in `config/company.yaml`.
   **Topic refresh first, on Monday runs or when fewer than 10 unused unflagged topics remain:** find
   what is working right now and add 5-8 new topics to `seeds/topics.json` before picking.
   - Use the yt-viral skill: collect the latest 15-30 Shorts from 4-6 public science/explainer Shorts
     channels (`yt-dlp --flat-playlist -J <channel>/shorts`, public listings only; if yt-dlp can't
     reach YouTube, use web search for recent popular explainer Shorts), run `swipe.py --min 2.0`,
     and note which ideas beat their own channel's median by 2x or more.
   - Turn those into topics in our format and voice (one surprising mechanism, showable in clay, no
     people, settled science). Never copy a video: take the question, find our own angle.
   - Same shape as the existing entries (slug, title, category from `content_categories`, angle,
     summary, keywords, risk_flags, the seven scores, reasoning), plus `added_on` (YYYY-MM-DD) and
     `inspired_by` (the video URL and its multiple, or the search that led to it). Skip near-duplicates
     of existing topics. Scores stay editorial judgements; say so in `reasoning`.
   - Commit the list change with the episode. If nothing beat 2x, add nothing and say so in the report.
2. **Research + script.** Search the web, fact-check, and write `channel/episodes/NNN-slug/script_manifest.json`
   in episode 1's shape: blocks with `vo_line`, five `shots` (vary size and angle on every cut, no
   OTS, no people), `assets_used` (max 7: location first), `through_line_state` and `audio`
   (2-4 diegetic clay SFX cues). Validate with
   `validate_motion_script.py --script script_manifest.json --duration-seconds 40 --duration-retry-blocks 1,2,3,4`
   until `valid: true`. The Higgsfield validator is built for 10-second lines of 20-23 words; its
   `--duration-retry-blocks` allowance is what accepts 17-19 words, and every other check still runs
   (episode 5, 2026-10-26). Write 17-19 words a scene: it rejects 15-16.
   Then run `python3 channel/tools/check_hook.py channel/episodes/NNN-slug/script_manifest.json`
   until it prints "hook check passed" (no credits; see "Hook and retention"). It also checks the
   30-second shape: 4 scenes, at most 20 words a scene and 75 in all. Scene 1 needs `promise`, the
   payoff scene `delivers_promise` and `comment_question` (shown as its last card).
3. **Narration first** (cheap; it proves the script fits before the roughly 80-credit video spend). One
   `generate_audio_batch` with all four lines in the format
   `[curious] {line}` (this overrides the narration workflow's timecode format, which leaked words).
   Convert with the narration workflow's reverse-trim recipe, then measure each take with
   `bash $HF_WORKFLOWS/narration/scripts/speech_metrics.sh work/voices/voiceNN.wav --text '<line>'`:
   it must show `rate=ok` (at most 2.9 words/s) and `pauses=0`, and 17-19 words come out at about
   6-7.5 s. (`measure_narration_takes.py` still gates on the old 7.8-9.5 s window for 10-second lines,
   so it calls every 30-second take too short; don't use it.) Then run `python3 check_takes.py script_manifest.json work/voices`
   (upload `channel/tools/check_takes.py` to the sandbox). It fails any take containing words that are
   not in the script. The workflow's own `verify_takes.py` is NOT enough: it passed all three bad
   takes in episode 1. The captions show script words, so they hide spoken mistakes. Regenerate only
   failing lines (max 3 attempts per line; the third needs new words).
4. **Assets.** `generate_image_batch`, `seedream_v5_pro`, `1k`, style key `313e8a54-...` as
   `image_references`. Locations 9:16, empty sets, dark clay asphalt where there is a road. Props 1:1
   on a plain pale sky-blue background. Look at every image before using it and regenerate any set
   that clashes with the props (episode 1's first highway came out sand-coloured and hid the sand cars).
   Write `assets.json` (`{name: {id, desc}}`).
5. **Scenes.** `python3 channel/tools/build_blocks.py channel/episodes/NNN-slug > block_reqs.json`,
   then one `generate_video_batch` with that array. Wait with `jobs_wait`. Check each clip: audio
   stream present, about 4 cuts near 2/4/6/8 s, frames match the sets and props, no people or text.
   Look at a strip of frames every 0.5 s for each shot, not one frame per shot: reversing cars and
   stray objects only show up as motion.
   Regenerate a scene only for a named failure (wrong style, missing audio, person or text on
   screen), at most twice.
6. **Assemble + captions + upload** in background `sandbox_exec` calls: `media_upload` first, then
   the assembly in 6a (NOT `finish_video.sh`: its gate rejects any take under 7.2 s of speech, and
   30-second lines are 6-7.5 s), the caption fragment, the overlays (6b), then the PUT. Gotchas:
   - The sandbox refuses pasted base64 files. Upload the manifest with `media_upload` and curl it.
   - Presigned PUTs need the header `If-None-Match: *`.
   - Call `media_upload` for the video right before its PUT, not at the start of the run: the URL
     can fail with ExpiredToken after about 20 minutes although it says 24 h (episode 5).
   - The assembler sidecar names voices `v_000.wav`...; symlink `work/voices/voiceNN.wav` to those
     names in a separate folder and pass it as `--voice-dir` with `--per-block`.
   - Lines with numbers align badly (Whisper writes digits). Add `--minimum-similarity 0.70` after
     confirming the take says the right words.
   - Captions: the flags in Channel DNA (raised to about 68% height, large, `--profile default`).
     Check one frame per scene: the caption must sit above the Shorts title/handle area and stay
     clear of the right-hand buttons (inside the middle ~72% of the width).
   - `sandbox_exec` foreground calls time out at 60 s; run long work with `background:true` and poll.
   Inspect frames at a few cue midpoints before `media_confirm`.
6a. **Assemble with the dead-air trim** (no credits; every run). Download the four clips as
   `work/blocks/block01.mp4`... and write a small sidecar `sidecar_in.json`:
   `{"clip_seconds": 10, "sfx_vol": 0.12, "per_block": [{"n": 1, "clip": "block01.mp4", "voice": "v_000.wav"}, ...]}`.
   Run `python3 trim_dead_air.py --sidecar sidecar_in.json --blocks-dir work/blocks --voice-dir vdir
   --out-dir trimmed` (upload `channel/tools/trim_dead_air.py`). It cuts each clip to its line plus
   0.45 s each side, mixes the clip's own sound under the voice, joins the scenes and normalises to
   -16 LUFS, so no gap between lines reaches the 1.5 s the Mac holds (episode 2 v2), and writes a new
   sidecar. A 6.5-8 s line keeps only 7-8.5 s of the 10 s clip, and centring the cut would shave
   about 1.4 s off both ends, leaving the first and last shots as sub-second flashes and possibly
   cutting the scene's key moment. So find each clip's cuts
   (`ffmpeg -i blockNN.mp4 -vf "select='gt(scene,0.25)',showinfo" -f null -`) and set `trim_start_s`
   in each `per_block` entry to start on a cut (often 0, dropping the closing "settle" shot), so every
   shot left is at least about 1 s and the moment the line is about stays in. Caption the trimmed
   `final_clean.mp4` with `audio_to_captions.py ... --per-block <new sidecar> --voice-dir vdir`, and pass
   `--assembly <new sidecar>` to `overlays.py` in 6b so the scraps follow the shorter scenes. Episodes
   come out about 30 s long (25-35 s).
6b. **Overlays** (no credits): upload `channel/tools/overlays.py` and the manifest, then
   `python3 overlays.py script_manifest.json work/output/final.words.json work/output/final.mp4 final_v.mp4 --still T ...`
   writes overlay previews: composite and look at one per overlay, fix overlaps or wrong timing, then run
   it without `--still` (background, about 2 minutes) and PUT `final_v.mp4` as the episode video.
   It fails loudly if an `at`/`until` phrase is not in the captions.
7. **Thumbnail and cover.** Follow `thumbnail-generation` with the faceless Phase-8b handoff
   (non-photoreal clay medium, people-free, one variant). Verify the baked text. Upload it.
   Also make a **9:16 cover** for TikTok and Reels: same scene and hook text, composed for portrait
   (text in the upper-middle third, clear of the bottom 20% where the app's buttons sit). Export it as a
   1080x1920 JPEG under 2 MB, verify the text letter for letter, upload it, and record it as `cover_url`.
   TikTok rejected episode 1's 25 MB landscape PNG; the app's fallback letterboxes the thumbnail.
7b. **The Mac's check, before anything is pushed.** Write the episode's `channel/episodes.json` entry
   (step 8), then run `python3 scripts/qc_episode.py N --file <final video>`. It must end with "would be
   approved and posted automatically" (exit code 0). Anything else means the Mac would hold the episode
   and it would never be posted: fix the named check and run it again. Episode 2 was held for 1.6 s of
   silence between scenes (the limit is 1.5 s); keep every gap between lines under about 1 s (step 6a).
8. **Record.** Append the episode to `channel/episodes.json` in episode 1's shape: urls, credits spent
   (balance before minus after), sources, known issues, `category`, `description` and `hashtags`
   (yt-seo rules; at most 5, as TikTok allows no more; the app keeps `#shorts` for YouTube only and
   drops it elsewhere), `caption` and `description` that both open with the `comment_question`,
   `cover_url`, and `checks` with `narration_strict`, `captions` and `visual_review`
   set to `passed` only if that check really ran and passed. Use status `produced_not_published` (once an episode is
   confirmed live, a session sets it to `published` with a `posted` map of links: the importer never
   touches `published` entries, so a reset or restored database can't post it twice). The
   app's `import_episodes` job picks it up from there, runs the same check as step 7b, and publishes at
   the next free slot. Update `HANDOFF.md` (latest episode, credits left, any new
   open items), then commit `channel/` and `HANDOFF.md` and push to `main`, the only branch. The app on
   the owner's Mac pulls `main`, so an unpushed episode never gets published. If the push is rejected,
   `git pull --rebase` and push again. Never force-push.
9. **Report** in the final message: the video and thumbnail links, title, description draft
   (`yt-seo` rules), the sources, what failed and was fixed, and credits spent and remaining.

## Hard limits (never crossed, never asked about)

- Never publish anywhere from a scheduled run until the publishing app is deployed with platform
  accounts connected. Until then a run ends with links, not posts.
- Never spend more than 200 credits on one episode. If retries would cross that, ship what passes
  and report the gap. The one exception: fixing a problem the owner reported may go past 200 (the
  200-credit balance floor still applies).
- Never fabricate analytics, facts, sources or test results. If a check could not run, say so.
- Never use a real person's likeness or voice, and never use copyrighted characters or music.
