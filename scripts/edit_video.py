#!/usr/bin/env python3
"""edit_video.py — edit a talking-head video in one command.

    python scripts/edit_video.py clip1.MP4 [clip2.MP4 ...] -o edited.mp4

What it does, in order:
  1. joins the clips back to back without re-encoding (and drops the
     thumbnail stream some cameras, DJI for instance, hide in the file);
  2. detects silences (ffmpeg silencedetect) and cuts them, keeping a small
     margin on each side;
  3. transcribes word by word (whisper.cpp) and cuts the filler words
     ("um", "uh", "euh"...) and the false starts: when a sentence is said
     several times, only the LAST take is kept;
  4. renders the edited video;
  5. transcribes the result -> edited.txt + edited.srt.

Nothing else. No burned-in subtitles, no checks, no cover: this is the
foundation, meant to grow.

Dependencies: ffmpeg + ffprobe on the PATH, whisper-cli (whisper.cpp).
The model downloads itself the first time (~/.cache/whisper-cpp/).
Without whisper-cli the edit still comes out, just without a transcript.
macOS, Windows, Linux.
"""
import argparse, csv, math, os, re, shutil, subprocess, sys, tempfile, unicodedata, urllib.request

for _s in (sys.stdout, sys.stderr):          # non-ASCII on the Windows console
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(errors='replace')

FF = os.environ.get('FFMPEG', 'ffmpeg')
FP = os.environ.get('FFPROBE', 'ffprobe')
MODELS_DIR = os.path.join(os.path.expanduser('~'), '.cache', 'whisper-cpp')
MODELS_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/'

ap = argparse.ArgumentParser(description='Cut the silences and transcribe.')
ap.add_argument('rushes', nargs='+', help='video files, in order')
ap.add_argument('-o', '--out', default='edited.mp4', help='output video')
ap.add_argument('--min-sil', type=float, default=0.40,
                help='minimum silence length to cut, in s (0.40)')
ap.add_argument('--pad', type=float, default=0.05,
                help='margin kept on each side of a cut, in s (0.05)')
ap.add_argument('--noise', type=float, default=32,
                help='silence threshold in dB below 0 (32; raise if it cuts too much)')
ap.add_argument('--protect', nargs='*', default=[], metavar='A:B',
                help='A:B windows (in s, on the joined footage) never to cut')
ap.add_argument('--lang', default='en', help='language for whisper (en); fr, es, de...')
ap.add_argument('--model', default='large-v3-turbo',
                help='whisper model: a name (large-v3-turbo, small, base) downloaded '
                     'automatically, or the path to a ggml-*.bin file')
ap.add_argument('--no-transcript', action='store_true', help='skip whisper entirely')
ap.add_argument('--keep-fillers', action='store_true', help='do not cut the "um"/"euh"')
ap.add_argument('--keep-retakes', action='store_true',
                help='do not cut repeated takes (by default only the last take is kept)')
ap.add_argument('--min-match', type=int, default=4,
                help='words in common for two takes to count as a repeat (4)')
args = ap.parse_args()

# Filler words per language, and the prompt that makes whisper write them
# (by default it politely erases them).
FILLERS = {
    'fr': ({'euh', 'heu', 'hum', 'hm', 'mmh'}, 'Euh, euh, hum, bah, ben, donc euh.'),
    'en': ({'um', 'uh', 'uhm', 'hmm', 'mm', 'erm'}, 'Um, uh, hmm, so um, like, uh.'),
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def probe(path, entries, stream=None):
    cmd = [FP, '-v', 'error']
    if stream:
        cmd += ['-select_streams', stream]
    cmd += ['-show_entries', entries, '-of', 'csv=p=0', path]
    return run(cmd).stdout.strip()


def say(msg):
    print(msg, file=sys.stderr)


work = tempfile.mkdtemp(prefix='monte-')

# 1. lossless join ---------------------------------------------------------------
clean = []
for i, r in enumerate(args.rushes):
    c = f'{work}/clip{i}.mp4'
    # 0:v:0 / 0:a:0 = first video and first audio stream; everything else
    # (mjpeg thumbnail, data tracks) is dropped.
    run([FF, '-y', '-i', r, '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', c])
    clean.append(c)
merged = f'{work}/merged.mp4'
if len(clean) == 1:
    shutil.move(clean[0], merged)
else:
    lst = f'{work}/list.txt'
    open(lst, 'w', encoding='utf-8').write(
        ''.join(f"file '{c.replace(chr(92), '/')}'\n" for c in clean))   # ffmpeg wants /
    run([FF, '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', merged])

dur = float(probe(merged, 'format=duration'))
num, den = (probe(merged, 'stream=r_frame_rate', 'v:0').split('/') + ['1'])[:2]
FRAME = float(den) / float(num)          # one frame's duration
say(f'joined footage: {dur:.1f}s, {len(args.rushes)} clip(s), {float(num)/float(den):.2f} fps')

# 2. silences -> kept segments -------------------------------------------------
det = subprocess.run([FF, '-hide_banner', '-i', merged, '-af',
                      f'silencedetect=noise=-{args.noise}dB:d={args.min_sil}',
                      '-f', 'null', '-'], capture_output=True, text=True).stderr
starts = [float(x) for x in re.findall(r'silence_start:\s*([-\d.]+)', det)]
ends = [float(x) for x in re.findall(r'silence_end:\s*([-\d.]+)', det)]
ends += [dur] * (len(starts) - len(ends))            # silence running to the end

protect = [tuple(map(float, p.split(':'))) for p in args.protect]
cuts = []
for s, e in zip(starts, ends):
    if s <= 0.01:
        a, b = 0.0, e - args.pad                     # opening silence: all of it
    elif e >= dur - 0.05:
        a, b = s + args.pad, dur                     # trailing silence: all of it
    else:
        a, b = s + args.pad, e - args.pad
    if b > a and not any(pa < b and a < pb for pa, pb in protect):
        cuts.append((a, b))

def build_segs(cuts):
    """Kept segments = what is left of [0, dur] once the cuts are removed."""
    segs, cur = [], 0.0
    for a, b in sorted(cuts):
        if a - cur > 0.15:
            segs.append((cur, a))
        cur = max(cur, b)
    if dur - cur > 0.15:
        segs.append((cur, dur))
    return [snap_in(a, b) for a, b in segs]


def snap_in(a, b):
    """Snap the bounds to the frame grid, inwards.

    `trim` cuts on a frame, `atrim` on a sample: a segment that does not
    last a whole number of frames drifts video against audio, and the drift
    adds up at every cut. So we shave at most one frame per edge.
    """
    i = math.ceil(a / FRAME + 0.5)
    j = math.floor(b / FRAME + 0.5)
    if j <= i:
        j = i + 1
    return max(0.0, (i - 0.5) * FRAME), (j - 0.5) * FRAME


segs = build_segs(cuts)
kept = sum(b - a for a, b in segs)
say(f'silences: {len(segs)} segments kept, {dur:.1f}s -> {kept:.1f}s (-{dur - kept:.1f}s)')


# 3. filler words + repeated takes ---------------------------------------------
def model_path(name):
    """An existing path, else a model name downloaded into ~/.cache/whisper-cpp/."""
    if os.path.exists(name):
        return name
    fn = f'ggml-{name}.bin'
    dest = os.path.join(MODELS_DIR, fn)
    if not os.path.exists(dest):
        os.makedirs(MODELS_DIR, exist_ok=True)
        say(f'downloading model {fn} (once; ~1.5 GB for large-v3-turbo)...')
        tmp = dest + '.part'
        urllib.request.urlretrieve(MODELS_URL + fn, tmp,
            lambda n, b, t: say(f'  {n * b / 1e6:.0f} / {t / 1e6:.0f} MB') if n % 200 == 0 else None)
        os.replace(tmp, dest)
    return dest


def norm(word):
    w = unicodedata.normalize('NFD', word.lower())
    w = ''.join(c for c in w if unicodedata.category(c) != 'Mn')
    return re.sub(r"[^a-z0-9']", '', w)


def audio_of(segs, wav):
    """The audio of the kept segments, joined (16 kHz mono, for whisper)."""
    a_ = ''.join(f'[0:a]atrim={a:.6f}:{b:.6f},asetpts=PTS-STARTPTS[a{i}];' for i, (a, b) in enumerate(segs))
    fga = f'{work}/fg_a.txt'
    open(fga, 'w', encoding='utf-8').write(
        a_ + ''.join(f'[a{i}]' for i in range(len(segs))) + f'concat=n={len(segs)}:v=0:a=1[out]')
    run([FF, '-y', '-i', merged, '-filter_complex_script', fga, '-map', '[out]',
         '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav])


def words_of(wav, model, prompt):
    """[(start, end, text, normalized)] on the wav's own timeline, via whisper."""
    cmd = [whisper, '-m', model, '-f', wav, '-l', args.lang, '-ml', '1', '-sow', '-np',
           '-ocsv', '-of', f'{work}/words']
    if prompt:
        cmd += ['--prompt', prompt]
    subprocess.run(cmd, check=True, capture_output=True)
    out = []
    for r in csv.DictReader(open(f'{work}/words.csv', encoding='utf-8')):
        t = r['text'].strip()
        n = norm(t)
        if n:
            out.append((int(r['start']) / 1000, int(r['end']) / 1000, t, n))
    return out


def to_source(t, segs):
    """A time on the joined-kept-audio timeline -> the same instant in the source."""
    cum = 0.0
    for a, b in segs:
        if t <= cum + (b - a):
            return a + (t - cum)
        cum += b - a
    return segs[-1][1]


whisper = shutil.which('whisper-cli') or shutil.which('whisper-cpp')
if args.no_transcript:
    pass
elif not whisper:
    say('whisper-cli not found: no filler/retake cuts, no transcript (see SKILL.md to install it)')
elif not (args.keep_fillers and args.keep_retakes):
    model = model_path(args.model)
    fillers, prompt = FILLERS.get(args.lang, (set().union(*(f for f, _ in FILLERS.values())), ''))
    wav = f'{work}/kept.wav'
    audio_of(segs, wav)
    W = words_of(wav, model, prompt)
    extra = []          # (start, end, why) on the kept-audio timeline
    if not args.keep_fillers:
        for a, b, t, n in W:
            if n in fillers:
                extra.append((a - 0.03, b + 0.03, f'filler "{t}"'))
    if not args.keep_retakes:
        # A take is repeated when >= min_match words in a row come back within
        # the next 60 words: everything from the first occurrence up to the
        # restart is dropped, so the LAST take is the one kept.
        i, M = 0, args.min_match
        while i < len(W):
            best = None
            for j in range(i + M, min(len(W), i + 60)):
                k = 0
                while i + k < j and j + k < len(W) and W[i + k][3] == W[j + k][3]:
                    k += 1
                if k >= M and (best is None or k > best[1]):
                    best = (j, k)
            if best:
                j, k = best
                extra.append((W[i][0], W[j][0], 'retake "' + ' '.join(w[2] for w in W[i:i + k]) + '"'))
                i = j
            else:
                i += 1
    for a, b, why in sorted(extra):
        say(f'  cut {a:7.2f} -> {b:7.2f}  {why}')
        cuts.append((to_source(a, segs), to_source(b, segs)))
    if extra:
        segs = build_segs(cuts)
        kept = sum(b - a for a, b in segs)
        say(f'fillers + retakes: {len(extra)} cuts, {len(segs)} segments kept, now {kept:.1f}s')

# 4. render --------------------------------------------------------------------
v = ''.join(f'[0:v]trim={a:.6f}:{b:.6f},setpts=PTS-STARTPTS[v{i}];' for i, (a, b) in enumerate(segs))
a_ = ''.join(f'[0:a]atrim={a:.6f}:{b:.6f},asetpts=PTS-STARTPTS[a{i}];' for i, (a, b) in enumerate(segs))
pairs = ''.join(f'[v{i}][a{i}]' for i in range(len(segs)))
fg = f'{work}/fg.txt'
open(fg, 'w', encoding='utf-8').write(v + a_ + f'{pairs}concat=n={len(segs)}:v=1:a=1[v][a]')
out = os.path.abspath(args.out)
run([FF, '-y', '-i', merged, '-filter_complex_script', fg, '-map', '[v]', '-map', '[a]',
     '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
     '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out])
say(f'-> {out}')

# 5. transcript ----------------------------------------------------------------
base = os.path.splitext(out)[0]
if not args.no_transcript and whisper:
    model = model_path(args.model)
    wav = f'{work}/out.wav'
    run([FF, '-y', '-i', out, '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav])
    run([whisper, '-m', model, '-f', wav, '-l', args.lang, '-otxt', '-osrt', '-of', base])
    say(f'-> {base}.txt + {base}.srt')

shutil.rmtree(work, ignore_errors=True)
