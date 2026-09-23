#!/usr/bin/env python3
"""check_edit.py — measure an edit, for the maintainer (not part of the skill).

    python dev/check_edit.py edited.mp4 --source rush.MP4 --segments segs.tsv --lang fr

`segs.tsv` = the kept segments (start<TAB>end, joined-footage time), written
by `EDIT_VIDEO_SEGMENTS=segs.tsv python scripts/edit_video.py ...`.
Single-clip rush only for --source (the joined footage = the clip).

It prints four numbers, and the evidence behind each:
  1. duration of the edit;
  2. A/V desync: video stream duration - audio stream duration (ffprobe);
  3. words cut at the joins: for each join, the SOURCE audio just past the
     cut (the 60 ms after a segment ends, the 60 ms before the next one
     starts) — sound there (> -32 dB) means the cut fell inside a word.
     Each flagged join is re-transcribed alone so a human can judge;
  4. repeats left: the edit is re-split on its own short silences, each
     piece transcribed alone (whisper swallows repeats in long chunks),
     then scanned for the same words said twice within a few words.
"""
import argparse, math, os, re, shutil, struct, subprocess, sys, tempfile, unicodedata, wave

ap = argparse.ArgumentParser()
ap.add_argument('video')
ap.add_argument('--source', help='the single rush the edit was cut from')
ap.add_argument('--segments', help='start<TAB>end kept segments, joined-footage time')
ap.add_argument('--lang', default='fr')
ap.add_argument('--model', default=os.path.join(os.path.expanduser('~'), '.cache', 'whisper-cpp',
                                                'ggml-large-v3-turbo.bin'))
ap.add_argument('--noise', type=float, default=32)
args = ap.parse_args()
FF = os.environ.get('FFMPEG', 'ffmpeg')
FP = os.environ.get('FFPROBE', 'ffprobe')
work = tempfile.mkdtemp(prefix='check-')


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def wav_of(src, dst):
    run([FF, '-v', 'error', '-y', '-i', src, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', dst])
    return dst


def cut(wav, a, b, dst, tempo=None):
    cmd = [FF, '-v', 'error', '-y', '-ss', f'{max(0, a)}', '-to', f'{b}', '-i', wav]
    if tempo:
        cmd += ['-af', f'atempo={tempo}']
    run(cmd + ['-ac', '1', '-ar', '16000', dst])
    return dst


def whisper_many(files):
    for n in range(0, len(files), 150):
        run(['whisper-cli', '-m', args.model, '-l', args.lang, '-np', '-otxt'] + files[n:n + 150])
    return [' '.join(open(f + '.txt', encoding='utf-8').read().split()) if os.path.exists(f + '.txt') else ''
            for f in files]


def peak_db(wav, a, b):
    with wave.open(wav) as w:
        sr = w.getframerate()
        w.setpos(max(0, int(a * sr)))
        fr = w.readframes(max(1, int((b - a) * sr)))
    xs = struct.unpack(f'<{len(fr) // 2}h', fr)
    if not xs:
        return -99.0
    rms = math.sqrt(sum(x * x for x in xs) / len(xs))
    return 20 * math.log10(max(rms, 1) / 32768)


def norm(w):
    w = unicodedata.normalize('NFD', w.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in w if unicodedata.category(c) != 'Mn'))


# 1-2. duration + desync ---------------------------------------------------------
v = float(run([FP, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=duration',
               '-of', 'csv=p=0', args.video]).strip())
a = float(run([FP, '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=duration',
               '-of', 'csv=p=0', args.video]).strip())
print(f'duration: {v:.2f}s video, {a:.2f}s audio -> desync {abs(v - a) * 1000:.0f} ms')

# 3. words cut at the joins ------------------------------------------------------
if args.source and args.segments:
    segs = [tuple(map(float, l.split('\t')[:2])) for l in open(args.segments) if l.strip()]
    src = wav_of(args.source, f'{work}/src.wav')
    flagged, cum = [], 0.0
    for k, (sa, sb) in enumerate(segs):
        cum += sb - sa
        if k + 1 == len(segs):
            break
        na = segs[k + 1][0]
        after, before = peak_db(src, sb, sb + 0.06), peak_db(src, na - 0.06, na)
        if after > -args.noise or before > -args.noise:
            flagged.append((cum, sb, na, after, before))
    print(f'joins: {len(segs) - 1}, cut into sound (> -{args.noise:g} dB within 60 ms): {len(flagged)}')
    if flagged:
        outw = wav_of(args.video, f'{work}/out.wav')
        files = [cut(outw, t - 1.2, t + 1.2, f'{work}/j{n}.wav', tempo=0.7) for n, (t, *_r) in enumerate(flagged)]
        for (t, sb, na, x, y), txt in zip(flagged, whisper_many(files)):
            print(f'  {t:7.2f}s in the edit (source {sb:.2f} | {na:.2f}; {x:.0f} dB after, {y:.0f} dB before): "{txt}"')

# 4. repeats left ----------------------------------------------------------------
outw = f'{work}/out.wav'
if not os.path.exists(outw):
    wav_of(args.video, outw)
det = subprocess.run([FF, '-hide_banner', '-i', outw, '-af', 'silencedetect=noise=-30dB:d=0.06',
                      '-f', 'null', '-'], capture_output=True, text=True).stderr
ss = [float(x) for x in re.findall(r'silence_start:\s*([-\d.]+)', det)]
se = [float(x) for x in re.findall(r'silence_end:\s*([-\d.]+)', det)]
pieces, cur = [], 0.0
for s, e in zip(ss, se + [a] * (len(ss) - len(se))):
    if s - cur > 0.12:
        pieces.append((cur, s))
    cur = e
if a - cur > 0.12:
    pieces.append((cur, a))
files = [cut(outw, max(0, p0 - 0.03), p1 + 0.03, f'{work}/p{n}.wav') for n, (p0, p1) in enumerate(pieces)]
texts = whisper_many(files)
words = []                                                  # (time, token, raw)
for (p0, p1), t in zip(pieces, texts):
    ws = [w for w in re.split(r"[\s'’\-]+", re.sub(r'[\[(*][^\])*]*[\])*]', ' ', t)) if norm(w)]
    for n, w in enumerate(ws):
        words.append((p0 + (p1 - p0) * n / max(1, len(ws)), norm(w), w))
open(os.path.splitext(args.video)[0] + '.check.txt', 'w', encoding='utf-8').write(
    '\n'.join(f'{p0:7.2f} {t}' for (p0, _p1), t in zip(pieces, texts)) + '\n')
reps, i = [], 0
T = [w[1] for w in words]
while i < len(T):
    hit = None
    for n in range(6, 1, -1):                               # n words said again right after
        g = T[i:i + n]
        if len(g) < n or len(''.join(g)) < 8:
            continue
        for j in range(i + n, min(len(T) - n + 1, i + n + 4)):
            if T[j:j + n] == g:
                hit = (n, j)
                break
        if hit:
            break
    if hit:
        n, j = hit
        reps.append((words[i][0], ' '.join(w[2] for w in words[i:j + n])))
        i = j + n
    else:
        i += 1
print(f'repeats left (same >= 2 words, >= 8 letters, said again within 3 words): {len(reps)}')
for t, s in reps:
    print(f'  {int(t // 60)}:{t % 60:05.2f}  "{s}"')
print(f'pieces transcribed alone: {len(pieces)} -> {os.path.splitext(args.video)[0]}.check.txt')
shutil.rmtree(work, ignore_errors=True)
