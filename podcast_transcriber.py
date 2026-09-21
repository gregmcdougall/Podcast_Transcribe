#!/usr/bin/env python3
"""
Automatic podcast transcript capture — demo pipeline for a fixed list of shows.

Process:
  1. Poll each show's RSS feed.
  2. Compare against a local state file to find episodes not yet processed.
  3. Download the audio for new episodes.
  4. Send audio to Deepgram for transcription WITH speaker diarization.
  5. Save the labeled transcript to disk.
  6. Update state so re-running doesn't reprocess old episodes.

Run this on a schedule (cron, Task Scheduler, or an n8n/launchd job) to make
it "automatic" — on its own it only processes whatever is new right now.

Requirements:
    pip install requests feedparser

Set your Deepgram API key as an environment variable before running:
    export DEEPGRAM_API_KEY="your_key_here"
"""

import os
import json
import time
import requests
import feedparser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---- Config: shows are loaded from an external parameter file --------------

FEEDS_FILE = Path("feeds.json")

def load_feeds() -> dict:
    if not FEEDS_FILE.exists():
        raise FileNotFoundError(
            f"{FEEDS_FILE} not found. Create it with {{\"show-name\": \"rss_url\", ...}}"
        )
    return json.loads(FEEDS_FILE.read_text())

OUTPUT_DIR = Path("transcripts")
AUDIO_TMP_DIR = Path("audio_tmp")
STATE_FILE = Path("processed_episodes.json")

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# ---- State tracking ----------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ---- Step 1 & 2: poll feed, find new episodes --------------------------------

def get_new_episodes(show_name: str, feed_url: str, state: dict) -> list:
    parsed = feedparser.parse(feed_url)
    seen_guids = set(state.get(show_name, []))
    new_episodes = []

    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link")
        if guid in seen_guids:
            continue

        audio_url = None
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio"):
                audio_url = link["href"]
                break

        if audio_url:
            new_episodes.append({
                "guid": guid,
                "title": entry.get("title", "untitled"),
                "audio_url": audio_url,
                "published": entry.get("published", ""),
            })

    return new_episodes

# ---- Step 3: download audio ---------------------------------------------------

def download_audio(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest

# ---- Step 4: transcribe with diarization --------------------------------------

def transcribe_with_speakers(audio_path: Path) -> str:
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("Set DEEPGRAM_API_KEY before running.")

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/mpeg",
    }
    params = {
        "diarize": "true",
        "punctuate": "true",
        "model": "nova-2",
    }

    with open(audio_path, "rb") as f:
        resp = requests.post(DEEPGRAM_URL, headers=headers, params=params, data=f, timeout=600)
    resp.raise_for_status()
    result = resp.json()

    words = result["results"]["channels"][0]["alternatives"][0]["words"]
    lines, current_speaker, buffer = [], None, []

    for w in words:
        speaker = w.get("speaker")
        if speaker != current_speaker:
            if buffer:
                lines.append(f"Speaker {current_speaker}: {' '.join(buffer)}")
            current_speaker = speaker
            buffer = [w["punctuated_word"]]
        else:
            buffer.append(w["punctuated_word"])
    if buffer:
        lines.append(f"Speaker {current_speaker}: {' '.join(buffer)}")

    return "\n\n".join(lines)

# ---- Step 5 & 6: save transcript, update state --------------------------------

def process_show(show_name: str, feed_url: str, state: dict) -> None:
    new_episodes = get_new_episodes(show_name, feed_url, state)
    if not new_episodes:
        print(f"[{show_name}] no new episodes")
        return

    for ep in new_episodes:
        print(f"[{show_name}] new episode: {ep['title']}")

        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in ep["title"])[:80]
        audio_path = AUDIO_TMP_DIR / show_name / f"{safe_title}.mp3"
        transcript_path = OUTPUT_DIR / show_name / f"{safe_title}.txt"

        download_audio(ep["audio_url"], audio_path)
        transcript = transcribe_with_speakers(audio_path)

        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            f"# {ep['title']}\nPublished: {ep['published']}\nSource: {ep['audio_url']}\n\n{transcript}"
        )
        print(f"[{show_name}] transcript saved -> {transcript_path}")

        audio_path.unlink(missing_ok=True)  # drop the audio once transcribed

        state.setdefault(show_name, []).append(ep["guid"])
        save_state(state)  # save after each episode, not just at the end

# ---- Main ----------------------------------------------------------------------

def main():
    state = load_state()
    feeds = load_feeds()
    for show_name, feed_url in feeds.items():
        try:
            process_show(show_name, feed_url, state)
        except Exception as e:
            print(f"[{show_name}] ERROR: {e}")

if __name__ == "__main__":
    main()
