# Claude Code video editing skill — automatic rough cut of your raw footage

Let Claude edit your talking-head videos. You hand it the raw clips, it
gives you back the rough cut: **silences removed, filler words removed,
only the last take of each sentence kept**, plus **the transcript**. One
script, a handful of settings, nothing else. Runs on your own computer
(macOS, Windows, Linux), nothing is uploaded anywhere.

```
you:     edit my video, the clips are in Downloads
claude:  joined footage: 327.5s, 1 clip(s), 29.97 fps
         silences: 50 segments kept, 327.5s -> 101.2s (-226.3s)
           cut    1.98 ->    4.08  retake "C'est le nouvel emploi le plus sexy de la tech."
           cut   13.02 ->   15.36  retake "C'est un métier qui explose avec l'IA et"
           ...
         fillers + retakes: 7 cuts, 45 segments kept, now 81.7s
         -> edited.mp4, edited.txt, edited.srt
```

A 5 min 27 raw take became a 1 min 22 video, in about a minute of compute
on a Mac.

## Install

1. Put this folder in your Claude Code skills:
   - macOS / Linux: `~/.claude/skills/video-editing/`
   - Windows: `C:\Users\<you>\.claude\skills\video-editing\`

   ```sh
   git clone https://github.com/vincentventalon/claude-code-video-editing-skill ~/.claude/skills/video-editing
   ```

2. Open Claude Code and say: **"edit my video, the clips are in Downloads"**.

That's it. If a tool is missing (ffmpeg, whisper), Claude installs it: the
skill tells it how. The transcription model downloads itself the first time
(1.5 GB).

## What you get

`edited.mp4` (the video without the dead air), `edited.txt` (the text) and
`edited.srt` (subtitles with timings).

## What it does

1. **Joins your clips**, in the order you give them, without re-encoding.
2. **Cuts the silences** with ffmpeg, keeping a small margin so no word is clipped.
3. **Cuts the filler words** ("um", "uh", "euh"...): whisper.cpp transcribes
   word by word with a prompt that makes it write them down instead of
   politely erasing them.
4. **Drops the false starts**: when the same words come back a few seconds
   later, the first attempt is cut and **the last take is kept**. Shoot the
   way you talk: say it again until it is right, and move on.
5. **Renders** an .mp4 ready to post, video and audio aligned to the frame.
6. **Transcribes** the result, locally. Nothing leaves your machine.

## What it does not do (yet)

No burned-in subtitles, no cover on frame 0, no music, no split screen. I
have all of that in my own pipeline; if you want one of them here, open an
issue or say so under the video, and I will add the ones people ask for.

## Why it is so small

I post one video a day, edited by Claude, since August 2026. My real
pipeline is 1,400 lines of instructions and thirty scripts: word-level
subtitles, title cards, covers, a TikTok and an Instagram render, automatic
posting. It is far too personal to be useful to anyone else as is.

This repo is the foundation I started from: **get the audio, remove the
dead air**. It works right away, and it is meant for you to iterate on with
Claude, the way you shoot.

## The next steps are yours

Ask Claude, one video at a time, in the order you miss them: "burn the
subtitles into the video", "put a title on the first three seconds", "add
music under my voice". It edits this script. That is exactly how my version
grew.

## Settings

| Setting | Default | When to touch it |
|---|---|---|
| `--min-sil` | 0.40 s | it cuts breaths: raise to 0.6. It leaves gaps: lower to 0.3. |
| `--pad` | 0.05 s | clipped words: raise to 0.10. Too much air at the joins: lower to 0.03. |
| `--noise` | 32 dB | background noise (street, fan) and nothing gets cut: lower to 25. |

`--lang fr` for French (or any whisper language: it drives the filler words
and the transcript), `--protect 12.5:14.0` to keep a deliberate pause,
`--keep-retakes` / `--keep-fillers` to leave them in, `--min-match 6` for
stricter retake detection (default: 4 words in a row), `--no-transcript`
to skip whisper, `--model small` on a PC without a GPU.

---

## 🇫🇷 En français

Tu dézippes le dossier dans tes skills Claude Code (`~/.claude/skills/video-editing/`
sur Mac, `C:\Users\<toi>\.claude\skills\video-editing\` sur Windows), tu
ouvres Claude Code et tu lui dis **« monte ma vidéo, les rushes sont dans
Téléchargements »**. S'il manque un outil, c'est lui qui l'installe. Pour la
transcription en français, il passe `--lang fr` tout seul quand tu lui
parles français ; sinon dis-le-lui.

Vidéo, contexte et la version française de cette page : [deviensdev.fr/claude-code-montage](https://deviensdev.fr/claude-code-montage).

## License

MIT — Vincent Ventalon.
