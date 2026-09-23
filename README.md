# Podcast Transcriber

Automatically transcribes new episodes of a fixed list of podcasts, with
speaker labels, by polling each show's RSS feed on a schedule.

## How it works

1. Polls each RSS feed in `feeds.json`.
2. Compares episode GUIDs against `processed_episodes.json` to find new ones.
3. Downloads the audio for new episodes.
4. Sends audio to Deepgram for transcription with diarization (speaker labels).
5. Saves the transcript to `transcripts/<show>/<episode>.txt`.
6. Deletes the temporary audio file and updates the state file.

Running the script once processes whatever is new *right now* — it does not
poll continuously. Schedule it (cron, Task Scheduler, GitHub Actions on a
schedule, etc.) for genuinely automatic behavior.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your Deepgram API key
```

## Configure shows

Edit `feeds.json`:

```json
{
  "show-slug": "https://feed-url-here"
}
```

Add or remove shows here — no code changes needed.

## Run

```bash
python podcast_transcriber.py
```

## Notes

- `processed_episodes.json` is the pipeline's memory. Don't delete it once
  populated, or the next run will re-download and re-transcribe (and
  re-bill) every back-episode in every feed.
- Deepgram is a paid API, billed per minute of audio transcribed. There's
  no meaningful free tier for ongoing use.
- `transcripts/` and `audio_tmp/` are git-ignored — they're generated
  output, not source.
