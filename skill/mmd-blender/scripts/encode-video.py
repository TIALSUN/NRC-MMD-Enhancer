#!/usr/bin/env python3
"""Encode a contiguous Blender PNG sequence to a verified H.264 MP4."""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pattern", default="frame-%04d.png")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--audio")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--ffmpeg")
    return parser.parse_args()


def numbered_frames(folder, pattern):
    prefix, suffix = pattern.split("%04d", 1)
    number = re.compile("^" + re.escape(prefix) + r"(\d{4})" + re.escape(suffix) + "$")
    frames = []
    for path in sorted(folder.glob(pattern.replace("%04d", "*"))):
        match = number.match(path.name)
        if match:
            frames.append((int(match.group(1)), path))
    if not frames:
        raise SystemExit(f"No frames matched {pattern!r} in {folder}")
    numbers = [item[0] for item in frames]
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise SystemExit("Frame sequence is not contiguous")
    return frames


def main():
    args = parse_args()
    frames_dir = Path(args.frames_dir).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("FFmpeg not found; pass --ffmpeg or add it to PATH")
    frames = numbered_frames(frames_dir, args.pattern)
    start = frames[0][0]
    for number, path in frames:
        if path.name != args.pattern % number:
            raise SystemExit(f"Non-canonical frame name: {path.name}")
    if args.audio and not Path(args.audio).is_file():
        raise SystemExit(f"Audio not found: {args.audio}")
    duration = args.duration or len(frames) / args.fps
    command = [
        ffmpeg, "-y", "-framerate", str(args.fps), "-start_number", str(start),
        "-i", str(frames_dir / args.pattern),
    ]
    if args.audio:
        command += ["-i", str(Path(args.audio).resolve()), "-map", "0:v:0", "-map", "1:a:0"]
    command += [
        "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
        "-pix_fmt", "yuv420p", "-t", f"{duration:.6f}",
    ]
    if args.audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-movflags", "+faststart", str(output)]
    encoded = subprocess.run(command, capture_output=True, text=True)
    (output.parent / "encode.log").write_text(encoded.stderr, encoding="utf-8")
    if encoded.returncode:
        raise SystemExit(encoded.stderr[-4000:])
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-progress", "pipe:1", "-"],
        capture_output=True, text=True,
    )
    if decoded.returncode or decoded.stderr.strip():
        raise SystemExit(decoded.stderr or "Video decode failed")
    counts = re.findall(r"^frame=(\d+)$", decoded.stdout, re.MULTILINE)
    if not counts or int(counts[-1]) != len(frames):
        raise SystemExit(f"Decoded frame count mismatch: {counts[-1:]}, expected {len(frames)}")
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(output)], capture_output=True, text=True)
    validation = {
        "output": str(output),
        "frames": len(frames),
        "first_frame": start,
        "last_frame": frames[-1][0],
        "fps": args.fps,
        "duration_seconds": duration,
        "audio": bool(args.audio),
        "decode_errors": 0,
        "probe": [line.strip() for line in probe.stderr.splitlines() if "Video:" in line or "Audio:" in line],
    }
    (output.with_suffix(".validation.json")).write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False))


if __name__ == "__main__":
    main()
