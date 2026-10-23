# garmin-claude

Talk through your training with an AI assistant, and the workout shows up on your Garmin watch.

Two small scripts connect Garmin Connect to any assistant that can read and write files, like Claude Code or Claude Desktop:

- **`sync.py`** reads your Garmin data (HRV, Body Battery, stress, training readiness, VO2 max, training load) and writes one markdown note. The assistant reads it before giving advice, so you don't have to paste numbers into the chat.
- **`workouts.py`** takes the workouts you agreed on in the conversation, saved as a JSON file, and creates them as structured workouts in Garmin Connect, scheduled on your calendar. The watch syncs them like any other workout, with steps, distances and pace or heart rate targets.

```
Garmin watch ──► Garmin Connect ──► sync.py ──► Garmin.md ──► assistant reads it
                                                                    │
your watch ◄── Garmin Connect ◄── workouts.py ◄── workouts.json ◄───┘ you talk, it writes
```

## Setup

Python 3.9+.

```bash
git clone https://github.com/allankirsten/garmin-claude.git
cd garmin-claude
pip install -r requirements.txt
```

Log in once. The scripts save a token in `~/.garmin-claude` and only ask for the password again when it expires.

```bash
export GARMIN_EMAIL="you@example.com"

# macOS: keep the password in the Keychain
security add-generic-password -a "$GARMIN_EMAIL" -s garmin-connect -w

# anywhere else: an environment variable
export GARMIN_PASSWORD="..."
```

Never write your password in a file in this folder.

## Use

```bash
# Pull the last year of data into a note (first run takes a few minutes, later runs are fast)
python3 sync.py --output ~/notes/Garmin.md --cache ~/notes/garmin-cache.json

# Check what would be sent, then send
python3 workouts.py my-workouts.json --dry-run
python3 workouts.py my-workouts.json
```

`examples/workouts.json` shows the format. Each workout has a stable `key` and a `revision`. Change the plan, bump the revision, run it again: the old workout is removed from Garmin and the new one takes its place. Workouts that didn't change are skipped.

To keep the note fresh, run `sync.py` once a day:

```cron
0 22 * * * cd /path/to/garmin-claude && python3 sync.py --output ~/notes/Garmin.md --cache ~/notes/garmin-cache.json
```

## With Claude

Open Claude Code in the folder where `Garmin.md` lives and tell it how the pieces fit, for example in a `CLAUDE.md`:

```markdown
Before talking about training, read Garmin.md.
When we agree on workouts, write them to workouts.json in the format of
garmin-claude/examples/workouts.json, show me the plan, and after I approve run
`python3 garmin-claude/workouts.py workouts.json`.
```

Then just talk: "how was my recovery this week?", "move Thursday's intervals to Friday and make them shorter", "build me three weeks to get ready for a 10k". The assistant reads the numbers, proposes the plan, and after your OK the workouts are on your watch.

## Notes

- This uses Garmin Connect's unofficial API through [garminconnect](https://github.com/cyberjunky/python-garminconnect) and [garth](https://github.com/matin/garth). Garmin can change it at any time.
- Only running workouts for now.
- Your data stays on your machine: the cache, the note and the state file are in `.gitignore`.
- Health data is sensitive. If you share the note with an AI service, that service sees it.

## License

MIT
