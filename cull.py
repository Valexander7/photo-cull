"""Monthly photo cull helper for Apple Photos.

Sorts one month of photos into two albums using Apple's own quality scores:
  "Best of <Month YYYY>"          -> strongest shots, for John to heart
  "Probably delete <Month YYYY>"  -> weak shots, for John to review and delete

It never deletes anything. It only adds photos to albums.

Usage:
  .venv/bin/python cull.py                 # current month, dry run
  .venv/bin/python cull.py 2026-08         # a given month, dry run
  .venv/bin/python cull.py 2026-08 --apply # actually create the albums
"""

import argparse
import datetime as dt

import osxphotos
from osxphotos.photosalbum import PhotosAlbum

BEST_SHARE = 0.10  # top 10% of the month's photos go to "Best of"


def is_delete_candidate(p) -> bool:
    """Return True if photo p looks like one John would not miss.

    Useful signals on p (an osxphotos PhotoInfo):
      p.favorite          already hearted by John
      p.screenshot        a screenshot
      p.score.overall     Apple's overall quality, about -1 (bad) to 1 (great)
      p.score.failure     higher means Apple thinks the shot failed (blur, etc.)
      p.burst, p.burst_selected   burst frames; burst_selected = the pick
    """
    # John, 2026-09-24: screenshots always go; otherwise strict (only clearly bad shots).
    if p.screenshot:
        return True
    if p.burst and not p.burst_selected:
        return True
    return p.score.overall < -0.5


def month_range(month: str):
    start = dt.datetime.strptime(month, "%Y-%m")
    end = (start + dt.timedelta(days=32)).replace(day=1)
    return start, end


def weaker_duplicates(photos):
    """In each group of near-identical shots, return all but the best one."""
    seen, weaker = set(), []
    for p in photos:
        if p.uuid in seen or not p.duplicates:
            continue
        group = [p] + [d for d in p.duplicates if not d.intrash]
        seen.update(d.uuid for d in group)
        group.sort(key=lambda d: (d.favorite, d.score.overall), reverse=True)
        weaker.extend(d for d in group[1:] if not d.favorite)
    return weaker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("month", nargs="?", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--apply", action="store_true", help="create the albums")
    args = ap.parse_args()

    start, end = month_range(args.month)
    label = start.strftime("%B %Y")
    db = osxphotos.PhotosDB()
    photos = [
        p for p in db.photos(from_date=start, to_date=end)
        if p.isphoto and not p.hidden and not p.intrash
    ]

    ranked = sorted(
        (p for p in photos if not p.screenshot),
        key=lambda p: p.score.overall, reverse=True,
    )
    best = ranked[: max(1, int(len(ranked) * BEST_SHARE))] if ranked else []
    best_ids = {p.uuid for p in best}

    delete = {p.uuid: p for p in photos if is_delete_candidate(p) and not p.favorite}
    for p in weaker_duplicates(photos):
        delete.setdefault(p.uuid, p)
    delete = [p for uuid, p in delete.items() if uuid not in best_ids]

    print(f"{label}: {len(photos)} photos")
    print(f"  Best of:          {len(best)}")
    print(f"  Probably delete:  {len(delete)}")

    if not args.apply:
        print("Dry run. Add --apply to create the albums in Photos.")
        return
    if best:
        PhotosAlbum(f"Best of {label}").add_list(best)
    if delete:
        PhotosAlbum(f"Probably delete {label}").add_list(delete)
    print("Albums created. Review them in Photos; nothing was deleted.")


if __name__ == "__main__":
    main()
