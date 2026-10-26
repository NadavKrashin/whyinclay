"""Re-cut an assembled episode so no gap between narration lines is long enough to fail QC.

finish_video.sh centres each line in its 10 s scene. A line of about 8.3 s (Bram's pace) leaves about
0.85 s of silence on each side, so where two scenes meet there is 1.5 s or more of dead air, and the
app's technical QC rejects any silence of 1.5 s or longer. This trims each scene clip to its line plus
PAD seconds on each side (taken evenly off both ends of the clip, so the first and last shots get a
little shorter), mixes the clip's own audio at the assembler's sfx_vol under the take, joins the
scenes and runs two-pass loudnorm to -16 LUFS. No generation, no credits.

Usage (inside the Higgsfield sandbox, after finish_video.sh):
    python3 trim_dead_air.py --sidecar work/output/final_clean.mp4.assembly.json \\
        --blocks-dir work/blocks --voice-dir vdir --out-dir trimmed

A per_block entry may set trim_start_s to start its cut there instead of centring it (pick a shot cut
so no shot is left as a sub-second sliver; find cuts with ffmpeg's scene filter, see recipe step 6a).

It writes OUT_DIR/work/output/final_clean.mp4 and a new sidecar next to it. Then caption with
`audio_to_captions.py ... --per-block <new sidecar> --voice-dir vdir` and run
`overlays.py ... --assembly <new sidecar>`, then `scripts/qc_episode.py N --file <final>`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

FPS = 24


def edges(wav: str) -> tuple[float, float, float]:
    """(duration, leading silence, trailing silence) of a take, at the QC's -45 dB threshold."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", wav, "-af", "silencedetect=noise=-45dB:d=0.1",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                         "csv=p=0", wav]))
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    lead = en[0] if st and st[0] < 0.01 else 0.0
    tail = dur - st[-1] if st and (len(en) < len(st) or abs(en[-1] - dur) < 0.02) else 0.0
    return dur, lead, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", required=True, help="finish_video.sh's final_clean.mp4.assembly.json")
    ap.add_argument("--blocks-dir", required=True)
    ap.add_argument("--voice-dir", required=True, help="folder with the v_000.wav... names the sidecar uses")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pad", type=float, default=0.45, help="silence kept on each side of a line (s)")
    ap.add_argument("--first-lead", type=float, default=0.35, help="silence before the first word (s)")
    ap.add_argument("--last-tail", type=float, default=0.6, help="silence after the last word (s)")
    args = ap.parse_args()

    side = json.load(open(args.sidecar))
    clip_len = float(side.get("clip_seconds", 10)) + 0.12
    seg_dir = os.path.join(args.out_dir, "seg")
    out_dir = os.path.join(args.out_dir, "work", "output")
    os.makedirs(seg_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    last = side["per_block"][-1]["n"]
    out = dict(side, out="final_clean.mp4", per_block=[])
    t, segs = 0.0, []
    for b in side["per_block"]:
        n, wav = b["n"], os.path.join(args.voice_dir, b["voice"])
        dur, lead, tail = edges(wav)
        lead_pad = max(0.0, (args.first_lead if n == 1 else args.pad) - lead)
        tail_pad = max(0.0, (args.last_tail if n == last else args.pad) - tail)
        length = lead_pad + dur + tail_pad
        if length > clip_len - 0.04:  # a long line: give up lead-in before running past the clip
            lead_pad = max(0.0, lead_pad - (length - (clip_len - 0.04)))
            length = lead_pad + dur + tail_pad
        length = round(length * FPS) / FPS
        start = max(0.0, (clip_len - length) / 2)
        if "trim_start_s" in b:  # chosen by hand, e.g. on a shot cut so no shot is left as a sliver
            start = min(float(b["trim_start_s"]), clip_len - length)
        start = round(max(0.0, start) * FPS) / FPS
        seg = os.path.join(seg_dir, f"s{n}.mkv")
        fc = (f"[0:v]trim=start={start}:duration={length},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[v];"
              f"[0:a]atrim=start={start}:duration={length},asetpts=PTS-STARTPTS,"
              f"aformat=sample_rates=48000:channel_layouts=stereo,volume={side.get('sfx_vol', 0.12)}[s];"
              f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={int(lead_pad * 1000)}:all=1[n];"
              f"[s][n]amix=inputs=2:normalize=0:duration=first,apad,atrim=0:{length}[a]")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", os.path.join(args.blocks_dir, b["clip"]), "-i", wav,
                        "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "16",
                        "-preset", "medium", "-c:a", "pcm_s16le", seg], check=True)
        segs.append(seg)
        # audio_to_captions.py skips blocks without speech_s > 0; a hand-made sidecar has none
        out["per_block"].append(dict(b, clip_s=length, speech_abs_s=round(t + lead_pad, 3), lead_silence_s=0.0,
                                     speech_s=b.get("speech_s") or round(dur, 3),
                                     trim_start_s=start, voice_offset_s=round(lead_pad, 3)))
        print(f"block {n}: {length:.2f} s from {start:.2f} s, line at +{lead_pad:.2f} s", flush=True)
        t += length
    lst = os.path.join(seg_dir, "list.txt")
    open(lst, "w").write("".join(f"file '{os.path.basename(s)}'\n" for s in segs))
    joined = os.path.join(seg_dir, "joined.mkv")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined],
                   check=True)
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", joined, "-af",
                          "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = json.loads(err[err.rindex("{"):err.rindex("}") + 1])
    ln = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
          f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
          ":linear=true,aresample=48000,aformat=channel_layouts=stereo")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", joined, "-c:v", "copy", "-af", ln, "-c:a", "aac", "-b:a",
                    "192k", "-movflags", "+faststart", os.path.join(out_dir, "final_clean.mp4")], check=True)
    out.update(actual_s=t, total_s=round(t, 3),
               gate=f"trim_dead_air.py: clips trimmed to each line +{args.pad} s; 2-pass linear loudnorm -16")
    json.dump(out, open(os.path.join(out_dir, "final_clean.mp4.assembly.json"), "w"), indent=1)
    print(f"total {t:.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
