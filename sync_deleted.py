"""Find photos trashed in Google Photos (by Photo Judge) inside Apple Photos.

Reads the list Photo Judge saves to ~/Downloads after a trash, matches each
photo in Apple Photos by the moment it was taken plus its file name, and puts
the matches in an album "Deleted in Google" for John to review and delete.
It never deletes anything itself.

Usage:
  .venv/bin/python sync_deleted.py                  # newest list, dry run
  .venv/bin/python sync_deleted.py LIST.json        # a given list, dry run
  .venv/bin/python sync_deleted.py LIST.json --apply
  .venv/bin/python sync_deleted.py --auto           # every new list, used by launchd

--auto is run by the launch agent com.john.photo-cull-sync whenever ~/Downloads
changes. It adds matches to the album, renames the list "... (synced to Apple).json"
so it is never processed twice, and shows a Mac notification. John still does
the delete in Photos. Remove the agent with:
  launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.john.photo-cull-sync.plist
"""

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import traceback
from collections import defaultdict

import osxphotos
from osxphotos.photosalbum import PhotosAlbum

ALBUM = "Deleted in Google"
TIME_TOLERANCE_S = 2  # Google and Apple can round the capture time differently


def stem(name):
    return os.path.splitext(name or "")[0].lower()


SYNCED_TAG = " (synced to Apple)"
LOG = os.path.expanduser("~/Library/Logs/photo-cull-sync.log")


def notify(title, text):
    safe = lambda x: x.replace("\\", "").replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{safe(text)}" with title "{safe(title)}" sound name "Glass"'])


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def pending_lists():
    return sorted(
        p for p in glob.glob(os.path.expanduser("~/Downloads/*Photo Judge trashed in Google*.json"))
        if SYNCED_TAG not in p
    )


def newest_list():
    files = glob.glob(os.path.expanduser("~/Downloads/*Photo Judge trashed in Google*.json"))
    if not files:
        raise SystemExit("No Photo Judge list found in ~/Downloads.")
    return max(files, key=os.path.getmtime)


def match(entries, photos):
    """Return (sure, likely, missing).

    sure:   same capture second (within tolerance) and same file name
    likely: same capture second and same size, but the name differs
            (common for photos saved from chat apps)
    Each Apple photo is used at most once.
    """
    by_second = defaultdict(list)
    for p in photos:
        by_second[int(p.date.timestamp())].append(p)

    used, sure, likely, missing = set(), [], [], []
    for e in entries:
        t = int(e["timestamp"] / 1000)
        candidates = [
            p for s in range(t - TIME_TOLERANCE_S, t + TIME_TOLERANCE_S + 1)
            for p in by_second.get(s, []) if p.uuid not in used
        ]
        named = [p for p in candidates if e.get("fileName") and stem(p.original_filename) == stem(e["fileName"])]
        sized = [p for p in candidates if e.get("width") and {p.width, p.height} == {e["width"], e["height"]}]
        if len(named) >= 1:
            used.add(named[0].uuid)
            sure.append(named[0])
        elif len(sized) == 1:  # only trust size when it's unambiguous
            used.add(sized[0].uuid)
            likely.append(sized[0])
        else:
            missing.append(e)
    return sure, likely, missing


def sync_list(db, path):
    entries = json.load(open(path))  # a half-downloaded file fails here; retried next run
    ts = [e["timestamp"] / 1000 for e in entries]
    start = dt.datetime.fromtimestamp(min(ts) - 86400)
    end = dt.datetime.fromtimestamp(max(ts) + 86400)
    photos = [p for p in db.photos(from_date=start, to_date=end) if not p.intrash]
    return entries, match(entries, photos)


def auto():
    lists = pending_lists()
    if not lists:
        return
    try:
        db = osxphotos.PhotosDB()
    except Exception:
        log("cannot open Photos library\n" + traceback.format_exc())
        # Downloads changes often; warn at most once a day, not on every change.
        marker = os.path.expanduser("~/Library/Logs/photo-cull-sync.warned")
        if not os.path.exists(marker) or dt.datetime.now().timestamp() - os.path.getmtime(marker) > 86400:
            open(marker, "w").close()
            notify("Photo sync needs access",
                   "Couldn't read Apple Photos. Turn on Full Disk Access for python3.14, then it will retry.")
        return
    for path in lists:
        try:
            entries, (sure, likely, missing) = sync_list(db, path)
        except json.JSONDecodeError:
            continue  # still downloading
        except Exception:
            log(f"failed on {path}\n" + traceback.format_exc())
            notify("Photo sync failed", f"Could not sync {os.path.basename(path)}. Tell Claude.")
            continue
        found = sure + likely
        if found:
            PhotosAlbum(ALBUM).add_list(found)
        base, ext = os.path.splitext(path)
        os.rename(path, base + SYNCED_TAG + ext)
        log(f"{os.path.basename(path)}: {len(entries)} listed, {len(sure)} name match, "
            f"{len(likely)} size match, {len(missing)} not found")
        n = lambda k: f"{k} photo" + ("" if k == 1 else "s")
        note = f'{n(len(found))} ready to delete in the "{ALBUM}" album.'
        if missing:
            note += f" {n(len(missing))} not found in Apple Photos."
        notify("Photos to delete in Apple Photos", note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("list", nargs="?")
    ap.add_argument("--apply", action="store_true", help="add matches to the album")
    ap.add_argument("--auto", action="store_true", help="sync every new list (launchd)")
    args = ap.parse_args()
    if args.auto:
        return auto()

    path = args.list or newest_list()
    entries, (sure, likely, missing) = sync_list(osxphotos.PhotosDB(), path)

    print(f"List: {os.path.basename(path)} ({len(entries)} photos trashed in Google)")
    print(f"  Found in Apple Photos (time + name match): {len(sure)}")
    print(f"  Found in Apple Photos (time + size match): {len(likely)}")
    print(f"  Not found in Apple Photos:                 {len(missing)}")
    for e in missing[:10]:
        when = dt.datetime.fromtimestamp(e["timestamp"] / 1000)
        print(f"    - {e.get('fileName') or '(no name)'} taken {when:%Y-%m-%d %H:%M:%S}")

    if not args.apply:
        print("Dry run. Add --apply to put the matches in the album.")
        return
    PhotosAlbum(ALBUM).add_list(sure + likely)
    print(f'Added {len(sure) + len(likely)} photos to "{ALBUM}". Review and delete them in Photos.')


if __name__ == "__main__":
    main()
