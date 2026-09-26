# photo-cull

Apple Photos helpers for cleaning a photo library. Neither script deletes anything; they only fill albums for you to review.

- `cull.py YYYY-MM`: makes "Best of" and "Probably delete" albums for a month from Apple's own quality scores.
- `sync_deleted.py`: takes the list [Photo Judge](https://github.com/Valexander7/photo-judge) saves after trashing photos in Google Photos, finds the same photos in Apple Photos (capture time plus file name, or size), and adds them to a "Deleted in Google" album. This stops the Apple copies from being backed up to Google again.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The Python binary needs Full Disk Access (System Settings → Privacy & Security → Full Disk Access) to read the Photos library. On first run, macOS also asks to allow control of Photos.

## Automatic sync

`com.john.photo-cull-sync.plist` runs `sync_deleted.py --auto` whenever `~/Downloads` changes. New lists are synced, renamed `... (synced to Apple).json`, and a notification says how many photos are ready to delete. Log: `~/Library/Logs/photo-cull-sync.log`.

Install:

```bash
sed "s#__HOME__#$HOME#g" com.john.photo-cull-sync.plist > ~/Library/LaunchAgents/com.john.photo-cull-sync.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.john.photo-cull-sync.plist
```

Remove:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.john.photo-cull-sync.plist && rm ~/Library/LaunchAgents/com.john.photo-cull-sync.plist
```
