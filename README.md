# Claude Code video editing skill

Let Claude edit your talking-head videos. You hand it the raw clips, it
gives you back the video **without the silences** and **its transcript**.
One script, three settings, nothing else. Runs on your own computer
(macOS, Windows, Linux).

```
you:     edit my video, the clips are in Downloads
claude:  joined footage: 327.5s, 1 clip(s), 29.97 fps
         50 segments kept, 327.5s -> 101.2s (-226.3s)
         -> edited.mp4, edited.txt, edited.srt
```

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
3. **Renders** an .mp4 ready to post, video and audio aligned to the frame.
4. **Transcribes** with whisper.cpp, locally. Nothing leaves your machine.

## Why it is so small

I post one video a day, edited by Claude, since August 2026. My real
pipeline is 1,400 lines of instructions and thirty scripts: word-level
subtitles, title cards, covers, a TikTok and an Instagram render, automatic
posting. It is far too personal to be useful to anyone else as is.

This repo is the foundation I started from: **get the audio, remove the
dead air**. It works right away, and it is meant for you to iterate on with
Claude, the way you shoot.

## The next steps are yours

Ask Claude, one video at a time, in the order you miss them:

1. "burn the subtitles into the video"
2. "cut the uh's"
3. "when I repeat a sentence, keep the last take"
4. a cover, a title, music: everyone has their own style.

That is exactly how my version grew.

## Settings

| Setting | Default | When to touch it |
|---|---|---|
| `--min-sil` | 0.40 s | it cuts breaths: raise to 0.6. It leaves gaps: lower to 0.3. |
| `--pad` | 0.05 s | clipped words: raise to 0.10. Too much air at the joins: lower to 0.03. |
| `--noise` | 32 dB | background noise (street, fan) and nothing gets cut: lower to 25. |

`--lang fr` for French (or any whisper language), `--protect 12.5:14.0` to
keep a deliberate pause, `--no-transcript` to skip whisper, `--model small`
on a PC without a GPU.

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
