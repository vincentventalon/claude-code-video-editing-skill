#!/usr/bin/env python3
"""sync_from_private.py — carry the cutting improvements of a private editing
pipeline over to this public skill, then test. For the maintainer only: the
skill itself never runs this.

The private pipeline is a Claude Code skill in another git repo. Its path is
never written here: pass it in the PRIVATE_SKILL environment variable (or
--private).

    export PRIVATE_SKILL=/path/to/private/skills/tiktok-edit

    python dev/sync_from_private.py status       # 1. what changed in the private cutting code
    #  -> hand the printed diff file to Claude: "port what is worth it into
    #     scripts/edit_video.py" (rules below)
    python dev/sync_from_private.py test RUSH.MP4 --lang fr    # 2. real test, old vs new
    python dev/sync_from_private.py mark          # 3. once ported: remember where we are

Porting rules (the reason this is not a copy):
  - the public script stays ONE file, standard library only, ffmpeg +
    whisper.cpp, macOS / Windows / Linux, no paid API, no key, no
    `claude -p`, no personal path;
  - only the CUT travels (islands, whisper per island, retakes, joins, sync):
    no subtitles styling, no b-roll, no covers, no publishing;
  - every change is tested on a real rush with `test` before it is kept.

`test` renders the rush twice in a temporary folder (the public script at
--against, default `main`, and the working copy), runs dev/check_edit.py on
both and prints them side by side: duration, A/V desync, words cut at the
joins, repeats left. Nothing is committed and nothing is pushed: the last
line prints the commands to do it by hand.
"""
import argparse, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STATE = os.path.join(HERE, 'private-sync.txt')          # last private commit carried over
WATCHED = ['scripts/salves.py', 'scripts/jump_cuts.py', 'scripts/align.py',
           'scripts/postflight.py', 'references/coupes.md']
# what must never reach the public repo
LEAKS = ['/Users/', '/home/', 'cockpit', 'pifpafpoum', 'claude -p', 'elevenlabs',
         'api_key', 'apikey', 'openai']

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('cmd', choices=['status', 'test', 'mark'])
ap.add_argument('rush', nargs='*', help='test: the rush(es) to cut')
ap.add_argument('--private', default=os.environ.get('PRIVATE_SKILL'),
                help='the private skill folder (default: $PRIVATE_SKILL)')
ap.add_argument('--lang', default='fr')
ap.add_argument('--model', default=os.environ.get('WHISPER_MODEL', 'large-v3-turbo'),
                help='whisper model name or ggml-*.bin path (default: $WHISPER_MODEL or large-v3-turbo)')
ap.add_argument('--against', default='main', help='test: git ref to compare with (main)')
ap.add_argument('--out', help='test: folder for the renders (default: a new temp folder)')
args = ap.parse_args()


def git(*a, cwd=REPO, check=True):
    return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True, check=check).stdout


def leak_check():
    bad = []
    for f in git('ls-files').split() + git('ls-files', '--others', '--exclude-standard').split():
        if f.startswith('dev/private-sync') or f == 'dev/sync_from_private.py':
            continue
        p = os.path.join(REPO, f)
        try:
            txt = open(p, encoding='utf-8').read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(txt.splitlines(), 1):
            low = line.lower()
            for w in LEAKS:
                if w.lower() in low:
                    bad.append(f'{f}:{n}: "{w}" -> {line.strip()[:90]}')
    print('leak check: ' + ('clean' if not bad else f'{len(bad)} line(s) to look at'))
    for b in bad:
        print('  ' + b)


def need_private():
    if not args.private or not os.path.isdir(args.private):
        sys.exit('set PRIVATE_SKILL (or --private) to the private skill folder')
    return os.path.abspath(args.private)


if args.cmd == 'status':
    priv = need_private()
    head = git('rev-parse', 'HEAD', cwd=priv).strip()
    last = open(STATE).read().split()[0] if os.path.exists(STATE) else None
    print(f'private HEAD {head[:10]}   last carried over: {last[:10] if last else "never"}')
    if not last:
        print('never synced: read these files whole, port, then `mark`:')
        print(''.join(f'  {os.path.join(priv, w)}\n' for w in WATCHED))
        leak_check()
        sys.exit()
    log = git('log', '--format=%h %ad %s', '--date=short', f'{last}..{head}', '--', *WATCHED, cwd=priv)
    if not log.strip():
        print('nothing new in the cutting code since the last sync.')
    else:
        print('commits touching the cut:\n' + ''.join('  ' + l + '\n' for l in log.splitlines()))
        print(git('diff', '--stat', last, head, '--', *WATCHED, cwd=priv, check=False))
        diff = git('diff', last, head, '--', *WATCHED, cwd=priv, check=False)
        fd, path = tempfile.mkstemp(prefix='private-cut-', suffix='.diff')
        os.write(fd, diff.encode())
        os.close(fd)
        print(f'full diff: {path}')
        print('next: ask Claude in this repo — "read that diff and port into scripts/edit_video.py '
              'what improves the cut, following the rules at the top of dev/sync_from_private.py", '
              'then run `test`.')
    leak_check()

elif args.cmd == 'test':
    if not args.rush:
        sys.exit('test: give the rush(es) to cut')
    out = os.path.abspath(args.out) if args.out else tempfile.mkdtemp(prefix='sync-test-')
    os.makedirs(out, exist_ok=True)
    old = os.path.join(out, 'edit_video_old.py')
    open(old, 'w', encoding='utf-8').write(git('show', f'{args.against}:scripts/edit_video.py'))
    new = os.path.join(REPO, 'scripts', 'edit_video.py')
    model = args.model if os.path.exists(args.model) else os.path.join(
        os.path.expanduser('~'), '.cache', 'whisper-cpp', f'ggml-{args.model}.bin')
    rushes = [os.path.abspath(r) for r in args.rush]
    for tag, script in (('old', old), ('new', new)):
        video, segs = os.path.join(out, f'{tag}.mp4'), os.path.join(out, f'{tag}.segments.tsv')
        print(f'=== {tag}: {os.path.relpath(script, REPO) if tag == "new" else args.against}', flush=True)
        env = dict(os.environ, EDIT_VIDEO_SEGMENTS=segs)
        r = subprocess.run([sys.executable, script, *rushes, '-o', video, '--lang', args.lang,
                            '--model', args.model], env=env, capture_output=True, text=True)
        open(os.path.join(out, f'{tag}.log'), 'w', encoding='utf-8').write(r.stderr)
        print('\n'.join(l for l in r.stderr.splitlines() if not l.startswith('->')))
        if r.returncode:
            print(f'{tag} FAILED (see {out}/{tag}.log)')
            continue
        chk = [sys.executable, os.path.join(HERE, 'check_edit.py'), video, '--lang', args.lang,
               '--model', model]
        if len(rushes) == 1 and os.path.exists(segs):
            chk += ['--source', rushes[0], '--segments', segs]
        print(subprocess.run(chk, capture_output=True, text=True).stdout)
    print(f'renders in {out} — watch old.mp4 and new.mp4 before deciding.')
    leak_check()
    print('\nnothing was committed or pushed. If it is good:\n'
          f'  git -C {REPO} add -A && git -C {REPO} commit -m "..." && '
          f'git -C {REPO} push -u origin $(git -C {REPO} branch --show-current)')

elif args.cmd == 'mark':
    priv = need_private()
    head = git('rev-parse', 'HEAD', cwd=priv).strip()
    open(STATE, 'w').write(head + '\n')
    print(f'carried over up to private commit {head[:10]} (dev/private-sync.txt, commit it with the port)')
