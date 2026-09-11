#!/usr/bin/env python3
"""edit_video.py — edit a talking-head video in one command.

    python scripts/edit_video.py clip1.MP4 [clip2.MP4 ...] -o edited.mp4

What it does, in order:
  1. joins the clips back to back without re-encoding (and drops the
     thumbnail stream some cameras, DJI for instance, hide in the file);
  2. detects silences (ffmpeg silencedetect) and cuts them, keeping a small
     margin on each side;
  3. renders the edited video;
  4. transcribes the result with whisper.cpp -> edited.txt + edited.srt.

Nothing else. No burned-in subtitles, no checks, no cover: this is the
foundation, meant to grow.

Dependencies: ffmpeg + ffprobe on the PATH, whisper-cli (whisper.cpp).
The model downloads itself the first time (~/.cache/whisper-cpp/).
Without whisper-cli the edit still comes out, just without a transcript.
macOS, Windows, Linux.
"""
import argparse, math, os, re, shutil, subprocess, sys, tempfile, urllib.request

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
ap.add_argument('--no-transcript', action='store_true', help='skip whisper')
args = ap.parse_args()


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

segs, cur = [], 0.0
for a, b in cuts:
    if a - cur > 0.15:
        segs.append((cur, a))
    cur = max(cur, b)
if dur - cur > 0.15:
    segs.append((cur, dur))


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


segs = [snap_in(a, b) for a, b in segs]
kept = sum(b - a for a, b in segs)
say(f'{len(segs)} segments kept, {dur:.1f}s -> {kept:.1f}s (-{dur - kept:.1f}s)')

# 3. render --------------------------------------------------------------------
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

# 4. transcript ----------------------------------------------------------------
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


base = os.path.splitext(out)[0]
whisper = shutil.which('whisper-cli') or shutil.which('whisper-cpp')
if args.no_transcript:
    pass
elif not whisper:
    say('whisper-cli not found: no transcript (see SKILL.md to install it)')
else:
    model = model_path(args.model)
    wav = f'{work}/out.wav'
    run([FF, '-y', '-i', out, '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav])
    run([whisper, '-m', model, '-f', wav, '-l', args.lang, '-otxt', '-osrt', '-of', base])
    say(f'-> {base}.txt + {base}.srt')

shutil.rmtree(work, ignore_errors=True)
