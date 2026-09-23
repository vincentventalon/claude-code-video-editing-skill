#!/usr/bin/env python3
"""edit_video.py — rough cut of a talking-head video in one command.

    python scripts/edit_video.py clip1.MP4 [clip2.MP4 ...] -o edited.mp4 --lang fr

How it cuts (v1): THE SOUND DECIDES WHERE, WHISPER SAYS WHAT, THE LAST TAKE WINS.

  1. joins the clips back to back without re-encoding (and drops the
     thumbnail stream some cameras, DJI for instance, hide in the file);
  2. splits the audio into ISLANDS of sound: whatever lies between two
     silences. A cut can only ever fall in a silence, never inside a word;
  3. transcribes EACH island ON ITS OWN (whisper.cpp). Transcribed in one
     go, whisper glues two takes into one sentence and swallows the
     repeat; island by island, it cannot. An island with no word in it (a
     breath, a click, a lone "um") goes;
  4. drops the retakes: an island (or a run of islands) that is the
     beginning of what comes right after is a false start — it goes, the
     LAST take stays. An island that repeats itself inside ("the the
     server") is re-split on finer silences, each piece transcribed alone
     and judged again; no silence to cut in = kept and reported, never cut
     at a guessed timestamp;
  5. renders, with every segment a whole number of frames (picture and
     sound stay in sync) and a 10 ms fade at each join (no click);
  6. writes the transcript of the result (edited.txt, edited.srt) from the
     islands it kept, and the list of every island with what happened to it
     (edited.takes.tsv). That list doubles as a cache: running again with
     other settings re-transcribes nothing.

Dependencies: ffmpeg + ffprobe on the PATH, whisper-cli (whisper.cpp).
The model downloads itself the first time (~/.cache/whisper-cpp/).
Without whisper-cli the edit still comes out: silences only.
macOS, Windows, Linux. Nothing leaves the machine.
"""
import argparse, difflib, math, os, re, shutil, subprocess, sys, tempfile, unicodedata, urllib.request, wave

for _s in (sys.stdout, sys.stderr):          # non-ASCII on the Windows console
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(errors='replace')

FF = os.environ.get('FFMPEG', 'ffmpeg')
FP = os.environ.get('FFPROBE', 'ffprobe')
MODELS_DIR = os.path.join(os.path.expanduser('~'), '.cache', 'whisper-cpp')
MODELS_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/'

ap = argparse.ArgumentParser(description='Rough cut: silences, false starts, retakes, transcript.')
ap.add_argument('rushes', nargs='+', help='video files, in order')
ap.add_argument('-o', '--out', default='edited.mp4', help='output video')
ap.add_argument('--lang', default='en', help='spoken language for whisper (en); fr, es, de...')
ap.add_argument('--model', default='large-v3-turbo',
                help='whisper model: a name (large-v3-turbo, large-v3-turbo-q5_0, small, base) '
                     'downloaded automatically, or the path to a ggml-*.bin file')
ap.add_argument('--min-sil', type=float, default=0.22,
                help='a silence this long (s) separates two islands and is cut (0.22)')
ap.add_argument('--noise', type=float, default=32,
                help='silence threshold in dB below 0 (32; lower to 25 in a noisy room)')
ap.add_argument('--pad', type=float, default=0.05,
                help='air kept before each island, in s (0.05; after: pad + 0.02)')
ap.add_argument('--protect', nargs='*', default=[], metavar='A:B',
                help='A:B windows (s, joined footage) never to cut: a deliberate pause')
ap.add_argument('--cut', nargs='*', default=[], metavar='A:B',
                help='A:B windows (s, joined footage) to remove on top of the automatic cuts')
ap.add_argument('--keep-retakes', action='store_true', help='keep every take')
ap.add_argument('--keep-fillers', action='store_true', help='keep the islands that are only "um"')
ap.add_argument('--no-transcript', action='store_true', help='skip whisper: silences only')
args = ap.parse_args()

# Filler words per language (an island that is only these goes), and the
# lead-in words that are not part of the sentence ("So, the server..." is
# the same take as "The server...").
FILLERS = {'fr': {'euh', 'heu', 'hum', 'hm', 'mh', 'mmh', 'bah', 'ben'},
           'en': {'um', 'uh', 'uhm', 'hm', 'hmm', 'mh', 'mm', 'erm', 'er'},
           'es': {'eh', 'em', 'este', 'mmm'}, 'de': {'äh', 'ähm', 'hm', 'öh'}}
LEADINS = {'fr': {'voila', 'euh', 'heu', 'bon', 'alors', 'ben', 'bah', 'hum'},
           'en': {'um', 'uh', 'so', 'well', 'okay', 'ok', 'right'}}
# Linking words a new take often adds in front ("and", "that"): set aside only
# when comparing two neighbouring islands.
LINKS_ = {'fr': {'et', 'que', 'qu', 'mais', 'donc', 'puis'},
          'en': {'and', 'but', 'so', 'then', 'that'}}
# What whisper writes on a silence or a noise, well known.
PHANTOMS = ['soustitrage', 'soustitres', 'amaraorg', 'merci davoir regarde',
            'thanks for watching', 'thank you for watching', 'subtitles by']


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


def windows(specs):
    return [tuple(map(float, p.split(':'))) for p in specs]


work = tempfile.mkdtemp(prefix='monte-')
out = os.path.abspath(args.out)
base = os.path.splitext(out)[0]

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
for st in ('v:0', 'a:0'):          # the shorter stream sets the end: no tail of picture without sound
    try:
        dur = min(dur, float(probe(merged, 'stream=duration', st)))
    except ValueError:
        pass
num, den = (probe(merged, 'stream=r_frame_rate', 'v:0').split('/') + ['1'])[:2]
FRAME = float(den) / float(num)          # one frame's duration
say(f'joined footage: {dur:.1f}s, {len(args.rushes)} clip(s), {float(num)/float(den):.2f} fps')

WAV = f'{work}/full.wav'                 # 16 kHz mono: what whisper and the detector read
run([FF, '-y', '-i', merged, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', WAV])


# 2. islands of sound ------------------------------------------------------------
def silences(noise, d, a=0.0, b=None):
    cmd = [FF, '-hide_banner']
    if b is not None:
        cmd += ['-ss', f'{a}', '-to', f'{b}']
    det = subprocess.run(cmd + ['-i', WAV, '-af', f'silencedetect=noise=-{noise}dB:d={d}',
                                '-f', 'null', '-'], capture_output=True, text=True).stderr
    off = a if b is not None else 0.0
    ss = [float(x) + off for x in re.findall(r'silence_start:\s*([-\d.]+)', det)]
    se = [float(x) + off for x in re.findall(r'silence_end:\s*([-\d.]+)', det)]
    return list(zip(ss, se + [b if b is not None else dur] * (len(ss) - len(se))))


def islands_between(sils, a, b, min_len=0.12):
    """What is not silence between a and b, at least min_len long."""
    isl, cur = [], a
    for s, e in sorted(sils):
        if s - cur >= min_len:
            isl.append((cur, min(s, b)))
        cur = max(cur, e)
    if b - cur >= min_len:
        isl.append((cur, b))
    return isl


FINE = {}
LEVELS = [(2, 0.08), (4, 0.05)]      # dB above the island threshold, min length (s)


def fine_split(a, b, level=0):
    """An island re-split on shorter, quieter silences (a breath inside a
    sentence). Level 1 is finer still: the 50 ms between two words."""
    if level not in FINE:
        FINE[level] = silences(args.noise - LEVELS[level][0], LEVELS[level][1])
    return islands_between([(s, e) for s, e in FINE[level] if s > a and e < b], a, b)


islands = islands_between(silences(args.noise, args.min_sil), 0.0, dur)
say(f'islands of sound: {len(islands)} (silences >= {args.min_sil}s at -{args.noise:g} dB)')


# 3. whisper, island by island ---------------------------------------------------
def model_path(name):
    """An existing path, else a model name downloaded into ~/.cache/whisper-cpp/."""
    if os.path.exists(name):
        return name
    fn = f'ggml-{name}.bin'
    dest = os.path.join(MODELS_DIR, fn)
    if not os.path.exists(dest):
        os.makedirs(MODELS_DIR, exist_ok=True)
        say(f'downloading model {fn} (once; 1.6 GB for large-v3-turbo, 0.5 GB for small)...')
        tmp = dest + '.part'
        urllib.request.urlretrieve(MODELS_URL + fn, tmp,
            lambda n, b, t: say(f'  {n * b / 1e6:.0f} / {t / 1e6:.0f} MB') if n % 200 == 0 else None)
        os.replace(tmp, dest)
    return dest


def norm(word):
    w = unicodedata.normalize('NFD', word.lower())
    w = ''.join(c for c in w if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', w)


def toks(text):
    text = re.sub(r'[\[(*][^\])*]*[\])*]', ' ', text)      # [Music], (laughs), *noise*
    return [t for t in (norm(x) for x in re.split(r"[\s'’\-]+", text)) if t]


whisper = shutil.which('whisper-cli') or shutil.which('whisper-cpp')
use_whisper = whisper and not args.no_transcript
if not use_whisper and not args.no_transcript:
    say('whisper-cli not found: silences only, no retakes, no transcript (see SKILL.md to install it)')

CACHE = f'{base}.takes.tsv'
TAG = f'# model={os.path.basename(args.model)} lang={args.lang}'
cache = {}
if use_whisper and os.path.exists(CACHE):
    lines = open(CACHE, encoding='utf-8').read().splitlines()
    if lines and lines[0] == TAG:
        for l in lines[1:]:
            p = l.split('\t')
            if len(p) >= 4 and not l.startswith('#'):
                cache[(round(float(p[0]), 3), round(float(p[1]), 3))] = p[3]


def key(s):
    return (round(s[0], 3), round(s[1], 3))


def transcribe(spans):
    """[(a, b, text)] — each span transcribed ON ITS OWN, with a little air on
    each side that never reaches into the neighbouring span. One whisper-cli
    call for all of them (the model loads once)."""
    todo = [k for k, s in enumerate(spans) if key(s) not in cache]
    if todo:
        model = model_path(args.model)
        d = tempfile.mkdtemp(dir=work)
        with wave.open(WAV) as w:
            sr, params = w.getframerate(), w.getparams()
            files = []
            for k in todo:
                a, b = spans[k]
                lo = spans[k - 1][1] + 0.02 if k else 0.0
                hi = spans[k + 1][0] - 0.02 if k + 1 < len(spans) else dur
                fa, fb = max(lo, a - 0.15), min(hi, b + 0.15)
                w.setpos(max(0, int(fa * sr)))
                f = os.path.join(d, f'{k}.wav')
                with wave.open(f, 'wb') as o:
                    o.setparams(params)
                    o.writeframes(w.readframes(max(1, int((fb - fa) * sr))))
                files.append(f)
        threads = str(min(8, os.cpu_count() or 4))
        for n in range(0, len(files), 150):          # command-line length, on Windows
            batch = files[n:n + 150]
            run([whisper, '-m', model, '-l', args.lang, '-t', threads, '-np', '-otxt'] + batch)
        for k, f in zip(todo, files):
            txt = open(f + '.txt', encoding='utf-8').read() if os.path.exists(f + '.txt') else ''
            cache[key(spans[k])] = ' '.join(txt.split())
    return [(a, b, cache[key((a, b))]) for a, b in spans]


# 4. decisions: what goes ---------------------------------------------------------
LEAD = LEADINS.get(args.lang, set())
LINKS = LINKS_.get(args.lang, set())
FILL = FILLERS.get(args.lang, set().union(*FILLERS.values()))


def no_speech(text):
    t = ''.join(toks(text))
    return not t or any(p in t for p in PHANTOMS)


def only_fillers(text):
    t = toks(text)
    return bool(t) and all(x in FILL for x in t)


def strip_leadin(t):
    k = 0
    while k < len(t) - 1 and t[k] in LEAD:
        k += 1
    return t[k:]


def starts_like(abandoned, rest):
    """How much the letters of `abandoned` are the BEGINNING of `rest` (0-1).
    Letters, not words: whisper writes "GitStatus" once and "git status" the
    next time. Both must start together (first letter aligned)."""
    a, s = ''.join(abandoned), ''.join(rest)
    if len(a) < 2 or len(s) < len(a):
        return 0.0
    best = 0.0
    for k in range(-2, 3):
        m = difflib.SequenceMatcher(None, a, s[:max(1, len(a) + k)], autojunk=False)
        b0 = m.get_matching_blocks()[0]
        if b0.a == 0 and b0.b == 0 and b0.size >= 1:
            best = max(best, m.ratio())
    return best


def is_start_of(abandoned, rest, run=1):
    # 0.74: measured on real footage — true false starts 0.75-1.00, a sentence
    # that simply goes on with a similar opening 0.71. Over a run of several
    # islands the first 8 letters must match too: a shared END ("...as long as
    # it is not public, it works") is not a shared beginning.
    a, r = strip_leadin(abandoned), strip_leadin(rest)
    if run > 1:
        ha, hr = ''.join(a)[:8], ''.join(r)[:8]
        if difflib.SequenceMatcher(None, ha, hr[:len(ha)], autojunk=False).ratio() < 0.6:
            return False
    return starts_like(a, r) >= 0.74


def restarts(ti, tj, adjacent=False):
    """tj starts the sentence of ti again, the end may differ ("Git add is for
    choosing..." then "Git add is for adding..."): the first 12 letters (>= 2
    words) match at >= 0.85. For neighbouring islands, also: the first 3 words
    are the same once the linking words are set aside ("and you don't want it
    | and that you don't want it"), or ti is said again whole within the first
    words of tj ("something | there is something important")."""
    ti, tj = strip_leadin(ti), strip_leadin(tj)
    if not ti or not tj:
        return False
    if adjacent:
        a_, b_ = skip_links(ti), skip_links(tj)
        if len(a_) >= 3 and a_[:3] == b_[:3] and len(''.join(a_[:3])) >= 7:
            return True
        n = len(ti)
        if n >= 2 and len(''.join(ti)) >= 6 and any(tj[k:k + n] == ti for k in range(1, 4)):
            return True
    if ti[0][0] != tj[0][0]:
        return False
    o, k = '', 0
    while k < len(ti) and (len(o) < 12 or k < 2):
        o += ti[k]
        k += 1
    if len(o) < 12 or k < 2:
        return False
    s = ''.join(tj)[:len(o)]
    return len(s) == len(o) and difflib.SequenceMatcher(None, o, s, autojunk=False).ratio() >= 0.85


def skip_links(t):
    k = 0
    while k < min(2, len(t) - 1) and t[k] in LINKS:
        k += 1
    return t[k:]


def sentence_done(text):
    return text.rstrip(' "»)').endswith(('.', '!', '?', '…', ':', ','))


def false_starts(items, gap=10.0, span=6):
    """items = [(a, b, text)] in order. The indexes to drop: for each i, the
    shortest run i..j-1 whose text is the beginning of what follows. The LAST
    take stays."""
    T = [toks(t) for _a, _b, t in items]
    drop, why, i = set(), {}, 0
    while i < len(items):
        found = None
        for j in range(i + 1, min(i + 1 + span, len(items))):
            if items[j][0] - items[j - 1][1] > gap:
                break
            ab = [t for k in range(i, j) for t in T[k]]
            nxt = [t for k in range(j, min(j + span, len(items))) for t in T[k]]
            if ab and (is_start_of(ab, nxt, j - i) or (j - i <= 3 and restarts(T[i], T[j], adjacent=j == i + 1))):
                found = j
                break
        if found is None:
            i += 1
            continue
        j = found
        ab = ''.join(t for k in range(i, j) for t in T[k])
        glued = i > 0 and items[i][0] - items[i - 1][1] < 0.6 and not sentence_done(items[i - 1][2])
        if len(ab) <= 4 and glued:   # one short word after an unfinished sentence: not enough
            i += 1
            continue
        for k in range(i, j):
            drop.add(k)
            why[k] = f'retake, said again at {items[j][0]:.2f}: "{items[j][2][:60]}"'
        i = j
    return drop, why


def repeats_itself(text):
    """The same words twice in a row inside one island ("the the server")."""
    t = toks(text)
    for n in range(1, 5):
        for i in range(len(t) - 2 * n + 1):
            if len(''.join(t[i:i + n])) >= 3 and t[i:i + n] == t[i + n:i + 2 * n]:
                return ' '.join(t[i:i + 2 * n])
    return None


def tail_restarted(ti, nexts):
    """Is the END of an island (with, maybe, the next islands) the beginning of
    what follows ("...one VPS. As long as it is not public, it works | well." then
    "As long as it is not public, it works well.")? nexts = token lists."""
    for m in range(len(nexts)):
        extra = [t for n in nexts[:m] for t in n]
        rest = [t for n in nexts[m:] for t in n]
        for p in range(1, len(ti)):
            q = ti[p:] + extra
            if len(''.join(q)) >= 8 and (is_start_of(q, rest) or restarts(q, rest)):
                return True
    return False


protect, extra_cuts = windows(args.protect), windows(args.cut)


def protected(a, b):
    return any(pa < b and a < pb for pa, pb in protect)


log = {}            # (a, b) -> (status, text)
warnings = []       # (source time, message)
if use_whisper:
    items = transcribe(islands)
    live = []
    for a, b, t in items:
        if protected(a, b):
            live.append((a, b, t))
        elif no_speech(t):
            log[(a, b)] = ('no-speech', t)
        elif only_fillers(t) and not args.keep_fillers:
            log[(a, b)] = ('filler', t)
        else:
            live.append((a, b, t))

    def refine(item, nexts, level=0):
        """Re-split an island on finer silences, transcribe each piece ALONE and
        judge the pieces (and the next islands) again: this is where the repeats
        whisper swallowed come out ("and so you have | and so now you have" read
        as one sentence). Only false starts and lone fillers go; a piece whisper
        hears nothing in stays (it is inside speech: a breath, a soft syllable).
        Returns (pieces to keep, next islands that turned out to be part of the
        abandoned take), or None if nothing changes."""
        a, b, t = item
        pieces = fine_split(a, b, level)
        if len(pieces) < 2:
            return None
        sub = transcribe(pieces)
        fill = {k for k, p in enumerate(sub) if only_fillers(p[2]) and not args.keep_fillers}
        judged = [k for k, p in enumerate(sub) if k not in fill and not no_speech(p[2])]
        drop, reason = false_starts([sub[k] for k in judged] + nexts)
        gone = [(nexts[k - len(judged)], reason[k]) for k in drop
                if k >= len(judged) and not protected(*nexts[k - len(judged)][:2])]
        reason = {judged[k]: r for k, r in reason.items() if k < len(judged)}
        drop = {judged[k] for k in drop if k < len(judged)}
        if not drop and not fill:
            return None
        kept = [p for k, p in enumerate(sub) if k not in drop and k not in fill]
        for k, p in enumerate(sub):
            if k in drop:
                log[p[:2]] = ('retake', reason[k])
            elif k in fill:
                log[p[:2]] = ('filler', p[2])
            else:
                log[p[:2]] = ('kept', p[2])
        log.pop((a, b), None)
        for it, why in gone:
            log[it[:2]] = ('retake', why)
        return kept, [it[:2] for it, _w in gone]

    if not args.keep_retakes:
        # a. false starts between islands: the last take stays
        drop, reason = false_starts(live)
        drop = {k for k in drop if not protected(*live[k][:2])}
        for k in sorted(drop):
            log[live[k][:2]] = ('retake', reason[k])
        live = [x for k, x in enumerate(live) if k not in drop]
        # b. every island re-split and re-read piece by piece, with the next ones;
        #    finer still when its end looks said again and the first split found nothing
        new, gone = [], set()
        for k, it in enumerate(live):
            if it[:2] in gone:
                continue
            nexts = [x for x in live[k + 1:k + 3] if x[:2] not in gone and x[0] - it[1] < 10.0]
            res = None if protected(*it[:2]) else refine(it, nexts)
            if res is None and not protected(*it[:2]):
                rep = repeats_itself(it[2])
                tail = nexts and tail_restarted(toks(it[2]), [toks(x[2]) for x in nexts])
                if rep or tail:
                    res = refine(it, nexts, level=1)
                    if res is None:
                        warnings.append((it[0], f'"{it[2][-60:]}" ' + (
                            f'repeats "{rep}"' if rep else f'is said again in "{nexts[-1][2][:40]}"')
                            + ', no silence to cut in: kept'))
            if res is None:
                new.append(it)
            else:
                new += res[0]
                gone.update(res[1])
        live = [x for x in new if x[:2] not in gone]
    for a, b, t in live:
        log.setdefault((a, b), ('kept', t))
else:
    live = [(a, b, '') for a, b in islands]

for (a, b), (st, t) in sorted(log.items()):
    if st == 'retake':
        say(f'  cut {a:7.2f} -> {b:7.2f}  {st}  "{cache.get(key((a, b)), "")[:70]}"')

# 5. kept segments ---------------------------------------------------------------
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


def merge(spans):
    spans, outl = sorted(spans), []
    for a, b in spans:
        if outl and a <= outl[-1][1]:
            outl[-1] = (outl[-1][0], max(outl[-1][1], b))
        else:
            outl.append((a, b))
    return outl


live.sort()
keep = []
for k, (a, b, _t) in enumerate(live):
    lo = (live[k - 1][1] + a) / 2 if k else 0.0            # never reach into the neighbour
    hi = (b + live[k + 1][0]) / 2 if k + 1 < len(live) else dur
    keep.append((max(lo, a - args.pad), min(hi, b + args.pad + 0.02)))
keep = merge(keep + [(max(0, a), min(dur, b)) for a, b in protect])
for ca, cb in extra_cuts:                                   # --cut: carve out
    nk = []
    for a, b in keep:
        if cb <= a or ca >= b:
            nk.append((a, b))
            continue
        if ca > a:
            nk.append((a, ca))
        if cb < b:
            nk.append((cb, b))
    keep = nk
segs = [snap_in(a, b) for a, b in keep if b - a >= 2 * FRAME]
if os.environ.get('EDIT_VIDEO_SEGMENTS'):                 # for dev/check_edit.py
    open(os.environ['EDIT_VIDEO_SEGMENTS'], 'w').writelines(f'{a:.6f}\t{b:.6f}\n' for a, b in segs)
if not segs:
    sys.exit('nothing kept: is there any speech in the clips? (try --noise 25)')
kept_dur = sum(b - a for a, b in segs)
n_ret = sum(1 for s, _t in log.values() if s == 'retake')
n_emp = sum(1 for s, _t in log.values() if s in ('no-speech', 'filler'))
say(f'kept {len(segs)} segments: {dur:.1f}s -> {kept_dur:.1f}s '
    f'({n_ret} retakes and {n_emp} islands without speech dropped)')


def to_out(t):
    """A time on the joined footage -> the same instant in the edited video."""
    cum = 0.0
    for a, b in segs:
        if t < a:
            return cum
        if t <= b:
            return cum + t - a
        cum += b - a
    return cum


# 6. render ----------------------------------------------------------------------
F = 0.01                                                    # 10 ms fade: no click at the joins
v = ''.join(f'[0:v]trim={a:.6f}:{b:.6f},setpts=PTS-STARTPTS[v{i}];' for i, (a, b) in enumerate(segs))
a_ = ''.join(f'[0:a]atrim={a:.6f}:{b:.6f},asetpts=PTS-STARTPTS,afade=t=in:d={F},'
             f'afade=t=out:st={max(0, b - a - F):.6f}:d={F}[a{i}];' for i, (a, b) in enumerate(segs))
pairs = ''.join(f'[v{i}][a{i}]' for i in range(len(segs)))
fg = f'{work}/fg.txt'
open(fg, 'w', encoding='utf-8').write(v + a_ + f'{pairs}concat=n={len(segs)}:v=1:a=1[v][a]')
run([FF, '-y', '-i', merged, '-filter_complex_script', fg, '-map', '[v]', '-map', '[a]',
     '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
     '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out])
say(f'-> {out}')

# 7. transcript + the list of takes ----------------------------------------------
if use_whisper:
    def ts(t):
        ms = int(round(t * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'

    cues = []
    for a, b, t in sorted(live):
        ws = t.split()
        if not ws:
            continue
        oa, ob = to_out(a), to_out(b)
        n = max(1, math.ceil(len(ws) / 8))                  # <= 8 words per subtitle
        chunks = [ws[k * len(ws) // n:(k + 1) * len(ws) // n] for k in range(n)]
        total = sum(len(''.join(c)) for c in chunks) or 1
        cur = oa
        for c in chunks:
            nxt = cur + (ob - oa) * len(''.join(c)) / total
            cues.append((cur, nxt, ' '.join(c)))
            cur = nxt
    with open(f'{base}.srt', 'w', encoding='utf-8') as f:
        for n, (a, b, t) in enumerate(cues, 1):
            f.write(f'{n}\n{ts(a)} --> {ts(b)}\n{t}\n\n')
    with open(f'{base}.txt', 'w', encoding='utf-8') as f:
        f.write(' '.join(t for _a, _b, t in sorted(live)).strip() + '\n')
    with open(CACHE, 'w', encoding='utf-8') as f:
        f.write(TAG + '\n# start\tend\tstatus\ttext   (times on the joined footage, before cuts)\n')
        for (a, b), (st, t) in sorted(log.items()):
            f.write(f'{a:.3f}\t{b:.3f}\t{st}\t{cache.get(key((a, b)), t)}\n')
        seen = set(log)                                     # pieces tried but not logged: cache only
        for (a, b), t in sorted(cache.items()):
            if (a, b) not in {key(s) for s in seen}:
                f.write(f'{a:.3f}\t{b:.3f}\t-\t{t}\n')
    say(f'-> {base}.txt + {base}.srt + {base}.takes.tsv')
    for t, msg in sorted(warnings):
        say(f'  to check at {to_out(t):.1f}s in the video: {msg}')

shutil.rmtree(work, ignore_errors=True)
