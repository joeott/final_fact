import json
import os
import subprocess

# CONFIG
STAGING_DIR = "/Users/joe/Projects/final_fact/input/Jostes_depo/video/staging"
VIDEO_ROOT = "/Users/joe/Projects/final_fact/input/Jostes_depo/video/Dave Jostes (1)"
CUT_LIST = os.path.join(STAGING_DIR, "cut_list.json")
OUTPUT_DIR = os.path.join(STAGING_DIR, "clips")
FINAL_OUT = os.path.join(STAGING_DIR, "Combined_Evidence.mp4")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(CUT_LIST) as f:
        cuts = json.load(f)

    for i, cut in enumerate(cuts):
        vid_filename = cut['video_id'] + ".MP4"
        vid_path = os.path.join(VIDEO_ROOT, vid_filename)
        srt_path = os.path.join(STAGING_DIR, "transcripts", cut['video_id'] + ".srt")

        out_name = f"{i+1:02d}_{cut['video_id']}_{cut['label']}.mp4"
        out_path = os.path.join(OUTPUT_DIR, out_name)

        start = cut['start']
        duration = cut['end'] - start

        print(f"Rendering {out_name}...")

        # Calculate timecode string for start (e.g. 00:05:20:00)
        h = int(start // 3600)
        m = int((start % 3600) // 60)
        s = int(start % 60)
        tc_str = f"{h:02}:{m:02}:{s:02}:00"

        # Escape SRT path for FFmpeg
        srt_esc = srt_path.replace(":", "\\:").replace("\\", "/")

        vf = (
            f"subtitles='{srt_esc}',"
            f"drawtext=timecode='{tc_str}':r=30:x=(w-tw)/2:y=h-60:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.6"
        )

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", vid_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:a", "aac",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            out_path
        ]

        subprocess.run(cmd, check=True)

    # Consolidate
    list_path = os.path.join(OUTPUT_DIR, "file_list.txt")
    with open(list_path, "w") as f:
        for file in sorted(os.listdir(OUTPUT_DIR)):
            if file.endswith(".mp4"):
                f.write(f"file '{os.path.join(OUTPUT_DIR, file)}'\n")

    print("Consolidating clips...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy",
        FINAL_OUT
    ])
    print(f"DONE: {FINAL_OUT}")

if __name__ == "__main__":
    main()
