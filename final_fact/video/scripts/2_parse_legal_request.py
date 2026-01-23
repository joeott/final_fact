import re
import pandas as pd
import json
import os
from fuzzywuzzy import fuzz

LETTER_PATH = "/Users/joe/Projects/final_fact/final_fact/video/resources/demand_letter.txt"
INDEX_PATH = "/Users/joe/Projects/final_fact/input/Jostes_depo/video/staging/index/master_index.csv"
OUTPUT_JSON = "/Users/joe/Projects/final_fact/input/Jostes_depo/video/staging/cut_list.json"

def parse_time(t_str):
    # Convert HH:MM:SS to seconds
    parts = list(map(int, t_str.split(':')))
    if len(parts) == 2: return parts[0]*60 + parts[1]
    return parts[0]*3600 + parts[1]*60 + parts[2]

def main():
    with open(LETTER_PATH, 'r') as f:
        text = f.read()

    df = pd.read_csv(INDEX_PATH)
    cuts = []

    # PATTERN 1: Explicit Video Citations (MVI_XXXX ... HH:MM:SS)
    # Regex captures: Filename, Start, End
    regex_explicit = r"(MVI_\d+)[^\s]*\.(?:MP4|mp4)\s+(\d{2}:\d{2}:\d{2})\u2013(\d{2}:\d{2}:\d{2})"
    matches = re.findall(regex_explicit, text)

    for m in matches:
        vid_id = m[0]
        start = parse_time(m[1])
        end = parse_time(m[2])
        cuts.append({
            "video_id": vid_id,
            "start": max(0, start - 10),
            "end": end + 10,
            "label": f"Explicit_{m[1]}"
        })

    # PATTERN 2: Wall Clock / Quote Search (3:13 PM)
    # We look for the time pattern, then extract the Quote text immediately following it
    regex_wall = r"\(Jostes Dep\. (\d{1,2}:\d{2}\s*(?:AM|PM))\)\s*\n\n\u201c([^\u201d]+)\u201d"
    matches_wall = re.findall(regex_wall, text)

    for m in matches_wall:
        time_label = m[0]
        quote_snippet = m[1][:100] # Take first 100 chars of quote

        # Fuzzy Search in Index
        # We search the whole index to find best text match
        df['score'] = df['text'].apply(lambda x: fuzz.partial_ratio(quote_snippet, str(x)))
        best = df.loc[df['score'].idxmax()]

        if best['score'] > 80:
            print(f"Found match for {time_label}: {best['video_id']} at {best['start']}s")
            cuts.append({
                "video_id": best['video_id'],
                "start": max(0, best['start'] - 10),
                "end": best['end'] + 10,
                "label": f"Context_{time_label.replace(' ','_').replace(':','')}"
            })
        else:
            print(f"WARNING: Could not locate quote for {time_label}")

    with open(OUTPUT_JSON, 'w') as f:
        json.dump(cuts, f, indent=2)

if __name__ == "__main__":
    main()
