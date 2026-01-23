import json
import glob
import os
import pandas as pd
from datetime import timedelta

# PATHS
INPUT_DIR = "/Users/joe/Projects/final_fact/input/Jostes_depo/video/staging/transcript_segments"
STAGING_DIR = "/Users/joe/Projects/final_fact/input/Jostes_depo/video/staging"
TRANSCRIPT_OUT = os.path.join(STAGING_DIR, "transcripts")
INDEX_OUT = os.path.join(STAGING_DIR, "index")

def seconds_to_srt(seconds):
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    ms = int(td.microseconds / 1000)
    return f"{total_seconds//3600:02}:{(total_seconds%3600)//60:02}:{total_seconds%60:02},{ms:03}"

def main():
    os.makedirs(TRANSCRIPT_OUT, exist_ok=True)
    os.makedirs(INDEX_OUT, exist_ok=True)

    # 1. Group files by Video ID
    files = glob.glob(os.path.join(INPUT_DIR, "*.json"))
    video_groups = {}

    for f in files:
        fname = os.path.basename(f)
        # Extract ID (e.g., MVI_0030)
        vid_id = fname.split('_chunk')[0].replace('.json','').replace('.MP4','')
        if vid_id not in video_groups: video_groups[vid_id] = []
        video_groups[vid_id].append(f)

    master_index = []

    # 2. Process groups
    for vid_id, chunks in video_groups.items():
        chunks.sort() # Ensure chunk001 comes before chunk002

        srt_lines = []
        global_offset = 0.0
        counter = 1

        print(f"Processing {vid_id} with {len(chunks)} chunks...")

        for chunk_file in chunks:
            with open(chunk_file) as f:
                data = json.load(f)

            # Use 'segments' (usually holds the sentences)
            for seg in data.get('segments', []):
                # Handle speaker segments if available for better resolution
                sub_segs = seg.get('speaker_segments', [seg])

                for sub in sub_segs:
                    # Calculate absolute time
                    start = sub['start'] + global_offset if 'start' in sub else seg['start_time'] + global_offset
                    end = sub['end'] + global_offset if 'end' in sub else seg['end_time'] + global_offset
                    text = sub['text'].strip()
                    speaker = sub.get('speaker', '')

                    # SRT Formatting
                    display_text = f"<font color='#FFFF00'><b>{speaker}:</b></font> {text}" if speaker else text
                    srt_lines.append(f"{counter}\n{seconds_to_srt(start)} --> {seconds_to_srt(end)}\n{display_text}\n\n")
                    counter += 1

                    # Indexing for Search
                    master_index.append({
                        "video_id": vid_id,
                        "start": start,
                        "end": end,
                        "text": text
                    })

            # Update Offset
            if 'total_duration_seconds' in data:
                global_offset += data['total_duration_seconds']
            elif data.get('segments'):
                global_offset = data['segments'][-1]['end_time'] # Fallback

        # Save SRT
        with open(os.path.join(TRANSCRIPT_OUT, f"{vid_id}.srt"), "w") as f:
            f.writelines(srt_lines)

    # Save Master Index
    pd.DataFrame(master_index).to_csv(os.path.join(INDEX_OUT, "master_index.csv"), index=False)

if __name__ == "__main__":
    main()
