"""
Diagnostic tool: verify chapter title language source for a YouTube video.

--- WHY THIS EXISTS ---

YouTube API always returns chapter titles translated to English, regardless of:
- the video's original language
- the user's account language / interface language
- cookies exported from a Russian-language YouTube session
- Accept-Language headers sent to yt-dlp
- yt-dlp player_client setting (web, android, etc.)

This was confirmed by running 6 yt-dlp configurations against a Russian video
with author-defined chapters. All 6 returned English titles via info["chapters"].

The fix: parse timecodes from info["description"] instead — video descriptions
are never auto-translated by YouTube, so chapter titles stay in the author's
original language. This tool was built to confirm the diagnosis and verify
the fix works correctly.

--- WHAT IT TESTS ---

Runs 6 yt-dlp configurations and prints chapter titles for each:
  1. Baseline (no extra headers)
  2. Accept-Language: ru
  3. Accept-Language: ru-RU,ru;q=0.9 (full browser-style header)
  4. player_client=web
  5. player_client=web + Accept-Language: ru
  6. No cookies (isolate cookie effect)

Then separately parses description timecodes — the correct source.

Expected result for a Russian video with author chapters:
  configs 1-6 → English titles (platform behavior, not a bug)
  Description timecodes → Russian titles (use this as chapter source)

--- USAGE ---

    python tools/debug_chapters.py VIDEO_URL [COOKIES_PATH]

Example:
    python tools/debug_chapters.py "https://www.youtube.com/watch?v=RagM_T1HCuo" "app/data/cookies.txt"

Run from the project root. Cookies default to app/data/cookies.txt if not specified.
"""

import json
import subprocess
import sys
import os

YTDLP = "yt-dlp"  # or full path if needed

VIDEO_URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=RagM_T1HCuo"
COOKIES = sys.argv[2] if len(sys.argv) > 2 else "app/data/cookies.txt"


def run(label: str, extra_args: list[str]):
    cmd = [YTDLP, "--no-warnings", "--js-runtimes", "node", "--skip-download", "--print-json"]
    if os.path.exists(COOKIES):
        cmd += ["--cookies", COOKIES]
    cmd += extra_args + [VIDEO_URL]

    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"CMD:  {' '.join(cmd)}")
    print('='*60)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if not r.stdout.strip():
            print(f"ERROR: {r.stderr[:300]}")
            return
        info = json.loads(r.stdout.strip())
        chapters = info.get("chapters") or []
        if not chapters:
            print("chapters: (none)")
        else:
            print(f"chapters ({len(chapters)}):")
            for ch in chapters:
                t = int(ch.get("start_time", 0))
                mm, ss = divmod(t, 60)
                hh, mm = divmod(mm, 60)
                ts = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
                print(f"  {ts}  {ch.get('title', '')}")
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
    except Exception as e:
        print(f"EXCEPTION: {e}")


if __name__ == "__main__":
    print(f"Video: {VIDEO_URL}")
    print(f"Cookies: {COOKIES} (exists={os.path.exists(COOKIES)})")

    # 1. Baseline: no extra headers
    run("Baseline (no Accept-Language)", [])

    # 2. Accept-Language: ru
    run("Accept-Language: ru", ["--add-headers", "Accept-Language:ru"])

    # 3. Accept-Language: ru-RU full
    run("Accept-Language: ru-RU,ru;q=0.9", ["--add-headers", "Accept-Language:ru-RU,ru;q=0.9,en-US;q=0.5,en;q=0.3"])

    # 4. player_client=web (browser-like client)
    run("player_client=web", ["--extractor-args", "youtube:player_client=web"])

    # 5. player_client=web + Accept-Language: ru
    run("player_client=web + Accept-Language:ru", [
        "--extractor-args", "youtube:player_client=web",
        "--add-headers", "Accept-Language:ru"
    ])

    # 6. No cookies baseline (to isolate cookie effect)
    print(f"\n{'='*60}")
    print("TEST: No cookies (to isolate cookie effect)")
    print('='*60)
    cmd = [YTDLP, "--no-warnings", "--js-runtimes", "node", "--skip-download", "--print-json", VIDEO_URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.stdout.strip():
            info = json.loads(r.stdout.strip())
            chapters = info.get("chapters") or []
            print(f"chapters ({len(chapters)}):" if chapters else "chapters: (none)")
            for ch in (chapters or []):
                print(f"  {ch.get('title', '')}")
    except Exception as e:
        print(f"EXCEPTION: {e}")

    # Check description for author-written timecodes (not translated by YouTube)
    print(f"\n{'='*60}")
    print("TEST: Description timecodes (author language, not translated)")
    print('='*60)
    import re
    cmd = [YTDLP, "--no-warnings", "--js-runtimes", "node", "--skip-download", "--print-json"]
    if os.path.exists(COOKIES):
        cmd += ["--cookies", COOKIES]
    cmd += [VIDEO_URL]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.stdout.strip():
            info = json.loads(r.stdout.strip())
            desc = info.get("description") or ""
            # Find lines with timestamp pattern: 0:00 / 00:00 / 0:00:00 / 00:00:00 followed by text
            ts_re = re.compile(r'^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)', re.MULTILINE)
            matches = ts_re.findall(desc)
            if matches:
                print(f"Found {len(matches)} timecodes in description:")
                for ts, title in matches:
                    print(f"  {ts}  {title}")
            else:
                print("No timecodes found in description.")
                print(f"Description (first 500 chars):\n{desc[:500]}")
    except Exception as e:
        print(f"EXCEPTION: {e}")

    print("\nDone.")
