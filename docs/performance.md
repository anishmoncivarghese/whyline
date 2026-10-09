# Performance

Measured on an M-series Mac from the 0.2.0 worktree, median of seven runs. These numbers have not been re-measured against the current release.

| Command | Total |
|---|---:|
| `brief` | 47 ms |
| `sync` | 92 ms |
| `timeline` | 43 ms |
| `status` | 63 ms |
| `explain` | 94 ms |

All remained below the 200 ms interactive target used at the time. `sync` asks git for branch, commit, and changed paths. `explain` shells out to `git blame`.

On a 50,000-event, 6.5 MB ledger, `explain` took about 159 ms against a 1 second target. That is why there is no SQLite index.
