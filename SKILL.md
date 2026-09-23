---
name: video-editing
description: Rough-cut a talking-head video (TikTok, Reels, Shorts, YouTube) in one command - joins the raw clips, cuts the silences, drops the false starts and the retakes (only the last take of a sentence is kept), never cuts inside a word, transcribes. macOS, Windows, Linux, all local. Use when the user says "edit my video", "cut the silences", "remove the dead air", "remove my retakes", "transcribe my video", "monte ma vidéo", "coupe les blancs", "enlève mes reprises", or drops raw clips to edit.
---

# Video editing

One command does everything:

```sh
python scripts/edit_video.py clip1.MP4 clip2.MP4 -o edited.mp4 --lang fr
```

(`python3` on macOS / Linux if `python` is missing.) It joins the clips in
the order given, splits the sound into islands (whatever lies between two
silences), transcribes each island on its own, drops the islands with no
word in them and the **false starts** (when a sentence is said several
times, only the **last** take is kept), renders `edited.mp4`, and writes
`edited.txt` + `edited.srt` (the transcript) and `edited.takes.tsv` (every
island, kept or not, with its text). **Always pass `--lang`** with the
language the user speaks (en, fr, es, de...).

## First time — YOU install the tools, not the user

The user just unzipped this skill. Check both tools, install what is
missing, without asking them to do it themselves:

| tool | check | macOS | Windows | Linux |
|---|---|---|---|---|
| ffmpeg + ffprobe | `ffmpeg -version` | `brew install ffmpeg` | `winget install Gyan.FFmpeg` (then reopen the terminal) | `sudo apt install ffmpeg` |
| whisper-cli (whisper.cpp) | `whisper-cli --help` | `brew install whisper-cpp` | download `whisper-bin-x64.zip` from https://github.com/ggml-org/whisper.cpp/releases (latest release), unzip, add the folder to the PATH | `sudo apt install whisper-cpp` or build https://github.com/ggml-org/whisper.cpp |

The model downloads itself on the first run, into `~/.cache/whisper-cpp/`:

| machine | pass | download | note |
|---|---|---|---|
| recent Mac (M1+) or PC with a GPU | nothing (`large-v3-turbo`) | 1.6 GB | the best; ~2-3 min for 10 min of rushes on a Mac M-series |
| little disk space or RAM (8 GB) | `--model large-v3-turbo-q5_0` | 0.57 GB | almost as good |
| PC without a GPU, or it is too slow | `--model small` | 0.49 GB | several times faster, catches fewer retakes |

`medium` is not a good middle ground: as heavy as `large-v3-turbo` and slower.

## What to do

1. Find the clips (usually the newest files in `~/Downloads`) and run the
   command. The first run on a 10 min rush takes a few minutes.
2. Read what the script prints: duration before / after, the retakes it cut
   (each quotes the words), and the `to check at 12.3s` lines (a repeat it
   saw but could not cut: no silence to cut in).
3. **Read the takes, like an editor.** Open `edited.takes.tsv` and read the
   `kept` lines in order, as a script. The script only catches a retake that
   starts like the next one. Look for what it cannot see: a sentence
   abandoned and said again **in other words** just after ("let me show you
   the 5 steps" ... "in fact there are 5 ways, let me show you"), a lone
   fragment ("So..."). If you find one, run again with `--cut A:B` (the
   times of the abandoned lines, straight from the file) and the same `-o`: it re-transcribes
   nothing, it only renders again. **In doubt, keep**: a repeat left costs a
   second pass, a sentence lost costs the video. Never cut something just
   because it is off topic, a joke or an aside.
4. Hand back the path of the video, what you cut and why, and the `to
   check` times if any.

## Settings

| Setting | Default | When to touch it |
|---|---|---|
| `--min-sil` | 0.22 s | the edit feels breathless → 0.35; pauses left between sentences → 0.18 |
| `--noise` | 32 dB | background noise (street, fan) and nothing gets cut → 25 |
| `--model` | large-v3-turbo | see the table above |

`--cut A:B` removes a window, `--protect A:B` keeps one (a comedic pause):
times of the joined footage, as in `edited.takes.tsv`. `--pad 0.08` keeps
more air around each island (a word's ending sounds clipped).
`--keep-retakes` keeps every take (a deliberate repetition, a chorus),
`--keep-fillers` keeps the lone "um"s, `--no-transcript` skips whisper
(silences only).

## When it fails

- `ffmpeg` or `whisper-cli` not found → install (table above), reopen the
  terminal. Without whisper the edit still comes out: silences only.
- A 0 s video or a `concat` error → the clips do not share the same format
  (resolution, fps); edit each clip alone, or re-encode them first.
- `nothing kept` → very quiet recording: `--noise 25`.

## What comes next

This is the rough cut. When the user asks for more, add it right here, in
this script: burned-in subtitles from the `.srt`, a cover on frame 0, music
under the voice.
