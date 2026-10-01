# Temporal Archive Viewer

Decodes Temporal Cloud's [S3 export](https://docs.temporal.io/cloud/export)
files — Protobuf-encoded `temporal.api.export.v1.WorkflowExecutions`, not
JSON — into a readable, searchable Streamlit UI, so teams can browse and
cross-check archived (closed) workflow histories without writing a script
per lookup.

## Quick start

```bash
make setup   # create .venv and install dependencies
make start   # run in the background
```

Then open http://localhost:8501. When you're done:

```bash
make stop
```

## Makefile commands

| Command        | What it does                                                          |
|----------------|------------------------------------------------------------------------|
| `make setup`   | Create `.venv` and install `requirements.txt` (also run automatically by `run`/`start`) |
| `make run`     | Run in the foreground (Ctrl+C to stop) — best for development         |
| `make start`   | Run in the background (PID tracked in `.streamlit.pid`)               |
| `make stop`    | Stop the background instance                                          |
| `make restart` | `stop` + `start`                                                      |
| `make status`  | Show whether it's running and the URL                                 |
| `make logs`    | Tail the background instance's log (`.streamlit.log`)                 |
| `make clean`   | Stop the app, remove `.venv`, logs, and `__pycache__`                 |
| `make clean-cache` | Wipe the local S3 decode/search cache (`~/.cache/temporal-archive-viewer`) |

Override the port with `make start PORT=8888`.

## Testing against a real bucket

1. **Confirm you have a profile with access**, before touching the app at all:
   ```bash
   aws sts get-caller-identity --profile <profile-name>
   ```
   This should return the AWS account that owns the archive bucket. If it
   errors or returns the wrong account, fix that first — the app can't do
   anything boto3 itself can't do.
   - Expired SSO token → `aws sso login --profile <profile-name>`, then retry.
   - No profile at all → `aws configure sso` (or `aws configure` for static
     keys) to create one in `~/.aws/config`.
   - List what profiles exist locally: `aws configure list-profiles`.

2. **Start the app**: `make start` (background) or `make run` (foreground,
   so you can watch logs live while testing).

3. **In the sidebar**, fill in:
   - **S3 bucket** — e.g. `my-temporal-archive-bucket`
   - **AWS profile** — the profile you just verified in step 1
   - **Root prefix** — defaults to `temporal-workflow-history/export/`,
     matching Temporal Cloud's export key layout
     (`{root}/{namespace}/{yyyy}/{mm}/{dd}/{hh}/{shard}/{file}`)
   - **AWS region** — usually leave blank; set it only if `Test connection`
     complains about a region/endpoint mismatch
   - Click **Test connection**. A green "Connected" means you're good to go;
     any error is shown verbatim with a specific next step (expired token,
     access denied, wrong bucket name, etc.) rather than a raw traceback.

4. **Browse** into a real namespace/date/hour folder and open a file, or
   **Search** a namespace + date range and scan it, to confirm real decoded
   data renders (workflow ID, status, event timeline, payloads).

### Swapping bucket / profile / account

- **Quick, one-off swap**: just retype the sidebar fields — takes effect on
  the next interaction, no restart needed, and the values carry over
  automatically when you switch between the Browse and Search pages.
- **Change your default so you don't have to retype it**: set env vars
  before launching —
  ```bash
  export TEMPORAL_ARCHIVE_BUCKET=my-temporal-archive-bucket
  export AWS_PROFILE=<profile-name>
  export TEMPORAL_ARCHIVE_PREFIX=temporal-workflow-history/export/
  make start
  ```
- **AWS session expires mid-session** (SSO tokens time out): you'll see the
  "session token has expired" error from `Test connection` or a scan. Run
  `aws sso login --profile <profile-name>` again in a terminal — no app
  restart needed, boto3 picks up the refreshed token automatically on the
  next call.
- **Switching AWS accounts entirely**: just change the profile in the
  sidebar (or `AWS_PROFILE` + `make restart`) to one authenticated against
  the other account.

## Pages

- **📂 Browse** — drill down through the bucket with clickable breadcrumbs
  (namespace → date → hour → shard), open a file, and view its decoded
  workflow history. Folder listings and file bytes are cached briefly in
  memory so re-clicking around the same area feels instant.
- **🔍 Search** — scope a namespace + date/hour range and scan it once;
  results are cached locally in `~/.cache/temporal-archive-viewer/index.db`
  keyed by S3 ETag, so re-scanning unchanged files is instant. Filter across
  everything scanned so far by workflow ID, workflow type, status, or any
  text in the decoded payloads (e.g. a ticket ID or user email). Don't know
  the namespace name? Use the "Discover namespaces" expander to list them
  from the bucket instead of guessing.

Both pages share a **workflow detail view**: status badge, failure
message/cause when the workflow failed, warnings for excessive retries or
non-determinism errors, a "Download decoded JSON" button, and an event
timeline that auto-expands the final event and any failed/timed-out/
terminated/canceled events (❌) so the outcome is visible without clicking
through — with an "Expand all events" toggle when you need the full trace.

## Design notes

- All decoding/search/caching logic lives in `src/` with no Streamlit
  imports, so it can be lifted into another internally-hosted Streamlit app
  later with minimal changes — only the thin `pages/*.py` files would need
  rewriting.
- Status and failure/retry diagnostics are rule-based (see `src/status.py`),
  not LLM-based — no external AI dependency is required to get useful
  debugging signal out of an archived history.
