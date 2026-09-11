---
name: video-editing
description: Edit a talking-head video (TikTok, Reels, Shorts, YouTube) in one command - joins the raw clips, cuts the silences and the filler words, keeps only the last take of repeated sentences, transcribes. macOS, Windows, Linux. Use when the user says "edit my video", "cut the silences", "remove the dead air", "transcribe my video", "monte ma vidéo", "coupe les blancs", or drops raw clips to edit.
---

# Video editing

One command does everything:

```sh
python scripts/edit_video.py clip1.MP4 clip2.MP4 -o edited.mp4
```

(`python3` on macOS / Linux if `python` is missing.) It joins the clips in
the order given, cuts the silences, cuts the filler words ("um", "uh",
"euh"...), drops the false starts (when a sentence is said several times,
only the **last** take is kept), renders `edited.mp4`, then writes the
transcript next to it: `edited.txt` (text) and `edited.srt` (with timings).
**Pass `--lang fr` (or es, de...) when the user speaks another language**:
the filler words and the transcript depend on it.

## First time — YOU install the tools, not the user

The user just unzipped this skill. Check both tools, install what is
missing, without asking them to do it themselves:

| tool | check | macOS | Windows | Linux |
|---|---|---|---|---|
| ffmpeg + ffprobe | `ffmpeg -version` | `brew install ffmpeg` | `winget install Gyan.FFmpeg` (then reopen the terminal) | `sudo apt install ffmpeg` |
| whisper-cli (whisper.cpp) | `whisper-cli --help` | `brew install whisper-cpp` | download `whisper-bin-x64.zip` from https://github.com/ggml-org/whisper.cpp/releases (latest release), unzip, add the folder to the PATH | `sudo apt install whisper-cpp` or build https://github.com/ggml-org/whisper.cpp |

The transcription model (~1.5 GB) downloads itself on the first run, into
`~/.cache/whisper-cpp/`. On a PC without a GPU, if transcription is too
slow, pass `--model small` (less accurate, 6× lighter).

## What to do

1. Find the clips (usually the newest files in `~/Downloads`) and run the
   command. It takes a while: about the length of the video, plus the model
   download the first time.
2. Read what the script prints: duration before / after, and the list of
   retakes it dropped (each line quotes the repeated words). Mention that
   list to the user: it is the only thing worth a glance.
3. Hand back the path of the video and a summary of the transcript. Do not
   re-read, do not verify, do not redo.

## Three settings, no more

| Setting | Default | When to touch it |
|---|---|---|
| `--min-sil` | 0.40 s | it cuts breaths → raise to 0.6; it leaves gaps → lower to 0.3 |
| `--pad` | 0.05 s | clipped words → raise to 0.10; too much air at the joins → lower to 0.03 |
| `--noise` | 32 dB | background noise (street, fan) and nothing gets cut → lower to 25 |

`--protect 12.5:14.0` keeps a deliberate pause (a comedic beat, say): the
times are those of the joined footage, before cuts.

`--keep-retakes` keeps every take (a deliberate repetition, a chorus);
`--keep-fillers` keeps the "um"s; `--min-match 6` asks for longer matches
before two takes count as a repeat (default 4 words). `--no-transcript`
skips whisper entirely: silences only.

## When it fails

- `ffmpeg` or `whisper-cli` not found → install (table above), reopen the
  terminal. Without whisper the edit still comes out; only the transcript
  is missing.
- A 0 s video or a `concat` error → the clips do not share the same format
  (resolution, fps); edit each clip alone, or re-encode them first.

## What comes next

This is the foundation. When the user asks for more, add it right here, in
this script: burned-in subtitles from the `.srt`, a cover on frame 0, music
under the voice, a split screen.
