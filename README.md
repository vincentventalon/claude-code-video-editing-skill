# Claude Code video editing skill — automatic rough cut of your raw footage

Let Claude edit your talking-head videos. You hand it the raw clips, it
gives you back the rough cut: **silences removed, false starts removed,
only the last take of each sentence kept, no word cut in half**, plus
**the transcript**. One script, a handful of settings, nothing else. Runs
on your own computer (macOS, Windows, Linux), nothing is uploaded
anywhere, no account, no API key.

```
you:     edit my video, the clips are in Downloads
claude:  joined footage: 538.0s, 1 clip(s), 29.97 fps
         islands of sound: 71 (silences >= 0.22s at -32 dB)
           cut   24.17 ->   25.09  retake  "La plupart des gens..."
           cut  250.48 ->  253.03  retake  "Si tu as encore de plus en plus d'utilisateurs sur ton application,"
           cut  254.11 ->  255.63  retake  "si tu as encore de plus en plus"
           ...
         kept 54 segments: 538.0s -> 117.8s (22 retakes and 3 islands without speech dropped)
         -> edited.mp4, edited.txt, edited.srt, edited.takes.tsv
```

A 9 min raw take became a 1 min 58 video, in about two minutes
of compute on a Mac.

## Install

1. Put this folder in your Claude Code skills:
   - macOS / Linux: `~/.claude/skills/video-editing/`
   - Windows: `C:\Users\<you>\.claude\skills\video-editing\`

   ```sh
   git clone https://github.com/vincentventalon/claude-code-video-editing-skill ~/.claude/skills/video-editing
   ```

2. Open Claude Code and say: **"edit my video, the clips are in Downloads"**.

That's it. If a tool is missing (ffmpeg, whisper), Claude installs it: the
skill tells it how. The transcription model downloads itself the first time.

## Which model for your computer

| your computer | say to Claude | download |
|---|---|---|
| recent Mac (M1 or later), PC with a GPU | nothing, it is the default (`large-v3-turbo`) | 1.6 GB |
| little disk space, 8 GB of RAM | "use the model large-v3-turbo-q5_0" | 0.57 GB, almost as good |
| PC without a GPU, or it is too slow | "use the small model" | 0.49 GB, several times faster, catches fewer retakes |

`medium` is not worth it: as heavy as the default and slower.

## What you get

`edited.mp4` (the rough cut), `edited.txt` (the text), `edited.srt`
(subtitles with timings) and `edited.takes.tsv` (every piece of your
footage, kept or cut, with what you said in it).

## How it cuts

1. **Joins your clips**, in the order you give them, without re-encoding.
2. **The sound decides where to cut.** The audio is split into islands of
   sound, whatever lies between two silences. A cut can only fall in a
   silence: never in the middle of a word.
3. **Each island is transcribed on its own** (whisper.cpp, locally).
   Transcribed in one go, whisper glues two takes into one sentence and
   quietly writes the repeat only once; island by island, it cannot. An
   island with no word in it (a breath, a click, a lone "um") goes.
4. **The last take wins.** When an island is the beginning of what you say
   right after, it was a false start: it goes, the last take stays. Every
   island is also re-split on its short inner pauses and each piece is read
   again on its own: that is where the "and so you, and so now you have"
   that whisper had swallowed come out. Shoot the way you talk: say it
   again until it is right, and move on.
5. **Renders** an .mp4 ready to post, picture and sound in sync to the
   frame, a 10 ms fade at each join so you never hear a click.
6. **Claude reads the takes** like an editor: a sentence you abandoned and
   restarted *in other words* is something only a reader sees. It cuts it
   with one more command, which re-renders without re-transcribing.

## What it does not do (yet)

No burned-in subtitles, no cover on frame 0, no music, no b-roll. I have
all of that in my own pipeline; if you want one of them here, open an issue
or say so under the video, and I will add the ones people ask for.

## Why it is so small

I post one video a day, edited by Claude, since August 2026. My real
pipeline is 1,400 lines of instructions and thirty scripts: word-level
subtitles, title cards, covers, a TikTok and an Instagram render, automatic
posting. It is far too personal to be useful to anyone else as is.

This repo is its cutting engine, simplified: **get the audio, remove the
dead air and the retakes**. It works right away, and it is meant for you to
iterate on with Claude, the way you shoot.

## The next steps are yours

Ask Claude, one video at a time, in the order you miss them: "burn the
subtitles into the video", "put a title on the first three seconds", "add
music under my voice". It edits this script. That is exactly how my version
grew.

## Settings

| Setting | Default | When to touch it |
|---|---|---|
| `--min-sil` | 0.22 s | the edit feels breathless: 0.35. Pauses left between sentences: 0.18. |
| `--noise` | 32 dB | background noise (street, fan) and nothing gets cut: 25. |
| `--model` | large-v3-turbo | see "Which model" above. |

`--lang fr` for French (or any whisper language), `--cut 12.5:14.0` to
remove a window and `--protect 12.5:14.0` to keep one (times of the joined
footage, as in `edited.takes.tsv`), `--pad 0.08` for more air around each
island, `--keep-retakes` / `--keep-fillers` to leave them in,
`--no-transcript` to skip whisper (silences only).

## For the maintainer

`dev/` is not part of the skill. `dev/check_edit.py` measures an edit
(duration, A/V desync, words cut at the joins, repeats left).
`dev/sync_from_private.py` carries the cutting improvements of my private
pipeline over to this repo and tests them on a real rush — read its header.
It never commits nor pushes.

---

## 🇫🇷 En français

Tu clones le dossier dans tes skills Claude Code (`~/.claude/skills/video-editing/`
sur Mac, `C:\Users\<toi>\.claude\skills\video-editing\` sur Windows), tu
ouvres Claude Code et tu lui dis **« monte ma vidéo, les rushes sont dans
Téléchargements »**. S'il manque un outil, c'est lui qui l'installe. Il
coupe les blancs, les faux départs et les reprises (il garde toujours ta
**dernière** prise), sans jamais couper un mot en deux, et te rend la
transcription. Tout tourne sur ta machine, sans compte ni clé d'API.

**Ordinateur modeste ?** Le modèle par défaut pèse 1,6 Go. Sur un PC sans
carte graphique, dis-lui « prends le modèle small » (0,49 Go, plusieurs
fois plus rapide, rate un peu plus de reprises) ; si c'est la place ou la
mémoire qui manque (8 Go), « prends large-v3-turbo-q5_0 » (0,57 Go,
presque aussi bon). `medium` ne vaut pas le coup : aussi lourd, plus lent.

Vidéo, contexte et la version française de cette page : [deviensdev.fr/claude-code-montage](https://deviensdev.fr/claude-code-montage).

## License

MIT — Vincent Ventalon.
