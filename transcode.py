#!/usr/bin/env python3
"""Transcode videos in the current folder into phone- or Resolve-friendly files.

Lists the videos in a folder, lets you pick which ones and a preset, and writes the
results next to the originals. Originals are never modified.

Presets:
    phone    H.264 + AAC .mp4, plays everywhere (phones, Drive, messengers)
    resolve  DNxHR + PCM .mov, opens in the free DaVinci Resolve on Linux

Usage:
    transcode               # videos in the current folder
    transcode ~/Videos/x    # videos in another folder
    transcode clip.mp4      # these files, skip the file list
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".mts", ".m2ts", ".avi", ".mxf", ".webm", ".wmv", ".mpg", ".mpeg"}


def phone_args(info):
    # CRF 18 looks the same as the source on a phone; yuv420p 8-bit is what phones decode in hardware.
    # Larger than 1080p (short side) is scaled down: 4K H.264 at this quality is ~80 Mbit/s and stutters.
    scale = "scale='if(gt(iw,ih),-2,min(iw,1080))':'if(gt(iw,ih),min(ih,1080),-2)'"
    return ["-vf", scale, "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]


def resolve_args(info):
    # 10-bit sources keep 10 bits (HQX); 8-bit sources use HQ. Audio becomes PCM (Resolve on Linux can't read AAC).
    ten_bit = "10" in info["pix_fmt"] or "12" in info["pix_fmt"]
    return ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx" if ten_bit else "dnxhr_hq",
            "-pix_fmt", "yuv422p10le" if ten_bit else "yuv422p", "-c:a", "pcm_s16le"]


# key -> (menu label, output suffix, extension, ffmpeg args builder, extra input args)
PRESETS = {
    "phone": ("Phone / sharing   H.264 + AAC .mp4 (small, plays everywhere)", " (phone)", ".mp4", phone_args, []),
    "resolve": ("DaVinci Resolve   DNxHR + PCM .mov (large, for editing)", " (resolve)", ".mov", resolve_args,
                ["-hwaccel", "cuda"] if shutil.which("nvidia-smi") else []),
}


# ---------------------------------------------------------------- terminal ui

def c(text, code):
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        sys.exit(1)
    return answer or (default or "")


def choose(prompt, options, default=None):
    """Numbered menu; returns the chosen index. Enter picks `default` (an index) if given."""
    print(c(prompt, "1"))
    for i, label in enumerate(options, 1):
        print(f"  {c(i, '36')}) {label}")
    while True:
        answer = ask("Choose", str(default + 1) if default is not None else None)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print(c("  Please type one of the numbers above.", "33"))


def parse_selection(text, count):
    """'1', '1,3', '2-5', 'a' -> sorted indexes, or None if invalid."""
    text = text.strip().lower()
    if text in ("a", "all"):
        return list(range(count))
    picked = set()
    for part in text.replace(" ", ",").split(","):
        if not part:
            continue
        lo, _, hi = part.partition("-")
        if not lo.isdigit() or (hi and not hi.isdigit()):
            return None
        lo, hi = int(lo), int(hi or lo)
        if not 1 <= lo <= hi <= count:
            return None
        picked.update(range(lo - 1, hi))
    return sorted(picked) or None


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def clock(seconds):
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# ---------------------------------------------------------------- video work

def probe(path):
    """Codec summary of a file, or None if ffprobe finds no video stream."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    streams = data.get("streams", [])
    # Skip cover-art / thumbnail streams (mjpeg, png) that some cameras embed.
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("codec_name") not in ("mjpeg", "png")), None)
    if not video:
        return None
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    num, _, den = video.get("r_frame_rate", "0/1").partition("/")
    return {
        "vcodec": video["codec_name"],
        "width": video.get("width", 0),
        "height": video.get("height", 0),
        "pix_fmt": video.get("pix_fmt", ""),
        "fps": float(num) / float(den or 1) if num else 0,
        "acodec": audio["codec_name"] if audio else None,
        "duration": float(data.get("format", {}).get("duration") or 0),
    }


def describe(info):
    bits = " 10-bit" if "10" in info["pix_fmt"] else ""
    audio = info["acodec"] or "no audio"
    return f"{info['vcodec']}{bits} {info['width']}x{info['height']} {info['fps']:.3g}fps, {audio}, {clock(info['duration'])}"


def output_path(src, preset):
    _, suffix, ext, _, _ = PRESETS[preset]
    return src.with_name(src.stem + suffix + ext)


def is_output(path):
    """Files this tool wrote, so re-runs don't offer them as sources."""
    return any(path.stem.endswith(p[1]) for p in PRESETS.values()) or ".part" in path.suffixes


def transcode(src, info, preset):
    """Run ffmpeg with a live progress line. Returns True on success."""
    _, _, ext, build, input_args = PRESETS[preset]
    dst = output_path(src, preset)
    tmp = dst.with_name(dst.name + ".part" + ext)
    cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]
           + input_args + ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0"]
           + build(info) + [str(tmp)])
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit() and info["duration"]:
                done = min(int(value) / 1e6 / info["duration"], 1)
                spent = time.time() - start
                eta = clock(spent / done - spent) if done > 0.01 else "--:--"
                bar = "#" * int(done * 30)
                print(f"\r  [{bar:<30}] {done * 100:5.1f}%  ETA {eta} ", end="", flush=True)
        err = proc.stderr.read()
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        tmp.unlink(missing_ok=True)
        raise
    print()
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        print(c(f"  Failed: {err.strip().splitlines()[-1] if err.strip() else 'ffmpeg error'}", "31"))
        return False
    tmp.rename(dst)
    shutil.copystat(src, dst)  # keep the original date so files sort the same way
    took = clock(time.time() - start)
    print(c(f"  Done in {took}: {dst.name} ({human(src.stat().st_size)} -> {human(dst.stat().st_size)})", "32"))
    return True


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Transcode videos into phone- or Resolve-friendly files.")
    parser.add_argument("paths", nargs="*", help="folder to list (default: current folder) or video files")
    parser.add_argument("-p", "--preset", choices=PRESETS, help="skip the preset question")
    args = parser.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found. Install it with: sudo pacman -S ffmpeg")

    paths = [Path(p).expanduser() for p in args.paths] or [Path.cwd()]
    folder = paths[0]
    if len(paths) == 1 and paths[0].is_dir():
        folder = paths[0]
        candidates = sorted(p for p in folder.iterdir()
                            if p.is_file() and p.suffix.lower() in VIDEO_EXT and not is_output(p))
        pick_from_list = True
    else:
        missing = [p for p in paths if not p.is_file()]
        if missing:
            sys.exit(f"Not a file: {missing[0]}")
        candidates, pick_from_list = paths, False

    print(c("Transcode", "1;35"))
    videos = []
    for p in candidates:
        info = probe(p)
        if info:
            videos.append((p, info))
    if not videos:
        sys.exit(f"No videos found in {paths[0]}")

    if pick_from_list:
        print(c(f"Videos in {folder}:", "1"))
        for i, (p, info) in enumerate(videos, 1):
            print(f"  {c(i, '36')}) {p.name}  {c(human(p.stat().st_size), '2')}  {c(describe(info), '2')}")
        while True:
            answer = ask("Which ones? (e.g. 1, 1,3, 2-5, a = all)", "1" if len(videos) == 1 else None)
            picked = parse_selection(answer, len(videos))
            if picked:
                break
            print(c("  Type numbers from the list, a range like 2-5, or a for all.", "33"))
        videos = [videos[i] for i in picked]

    keys = list(PRESETS)
    preset = args.preset or keys[choose("Convert to:", [PRESETS[k][0] for k in keys], 0)]

    todo = []
    for p, info in videos:
        if output_path(p, preset).exists():
            print(c(f"  Skipping {p.name}: {output_path(p, preset).name} already exists.", "33"))
        else:
            todo.append((p, info))

    failed = 0
    for n, (p, info) in enumerate(todo, 1):
        print(c(f"[{n}/{len(todo)}] {p.name}", "1"))
        if not transcode(p, info, preset):
            failed += 1

    if todo:
        print(c(f"Finished: {len(todo) - failed} converted, {failed} failed.", "1;32" if not failed else "1;31"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(c("\nCancelled. The unfinished file was removed; originals are untouched.", "33"))
        sys.exit(130)
