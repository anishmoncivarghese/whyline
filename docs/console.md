# The console

`whyline` and `whyline console` open the same screen. Chat, Relay, Agents,
Settings and the rest of this project live there. The CLI is for scripts.

## Restart after an upgrade

A running console keeps the whyline it started with in memory. After a newer
version lands on disk — from **Update…**, `uv tool upgrade whyline`, or a
whyline release finishing in this repository — the title becomes:

```text
whyline <installed> is installed · restart to use it
```

The log says `whyline <installed> is installed; this console is <running>.
Press Restart to use it.` **Restart** appears. **Update…** for that version
or older is hidden. The console checks at start, every five minutes, and
right after a whyline release's after-step finishes.

Press **Restart**. A relay running in this checkout is left running; the new
console finds it.

After **Update…** itself finishes, the same **Restart** button appears with
`Restart the console to use <version>.`

## When the console crashes

The error is saved to `~/.whyline/crash.log` (mode 0600). The terminal prints:

```text
The console crashed: <type>: <first line of the message>. Details are saved in ~/.whyline/crash.log. Start it again with: whyline console
```

Textual's traceback is still printed above that line. A normal quit, including
Ctrl-C, writes nothing. The file keeps the last five crashes. Each entry starts
with `--- <time> · whyline <version> · <type>: <message>` and a plain traceback
(at most 200 lines). Traceback locals are omitted, so a secret sitting in a
variable is left out of the file.

### What to send when you report a crash

Attach `~/.whyline/crash.log`. **Help** then **Copy** then **Copy crash log**
copies the last entry (header and traceback) to the clipboard. Include the
whyline version from the header if you paste rather than attach the file.

Open an issue at
[github.com/anishmoncivarghese/whyline/issues](https://github.com/anishmoncivarghese/whyline/issues).

## Help and `whyline doctor`

**Help** (and `/help`) show this line when the last crash is within seven days:

```text
Last console crash: 2026-11-15T12:00:00+05:30 · MarkupError (~/.whyline/crash.log)
```

`whyline doctor` adds the same crash as an informational line:

```text
ok    Last console crash: 2026-11-15T12:00:00+05:30 · MarkupError (~/.whyline/crash.log)
```

Doctor never changes the log. A crash older than seven days is omitted.
