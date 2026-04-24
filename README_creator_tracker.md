# Kuali Creator Tracker

A tool that monitors who is creating apps in Kuali Build. Each time you run it,
it checks the current list of app creators against the last time you ran it, and
tells you if any new people have started building apps.

---

## What It Does

Each time you run the tracker, it:

1. Connects to your Kuali Build instance and downloads the list of all apps and
   who created them.
2. Fetches global stats (total document count, user count, app count, etc.).
3. Compares today's creator list to the last time you ran it.
4. Prints a formatted report in your terminal.
5. Saves a snapshot to `creator_history.json` so it can compare next time.
6. Optionally sends you an email if new creators have appeared.

---

## Before You Start

### 1. Python 3 installed on your computer

- **Mac:** Open Terminal and type `python3 --version`. If you see a version number, you're good.
- **Windows:** Download from https://python.org and install it.

### 2. The `requests` library installed

Open Terminal (Mac) or Command Prompt (Windows) and run:

```
pip3 install requests
```

### 3. A Kuali Build bearer token

This proves to Kuali that you are you.

1. Log into Kuali Build in your browser.
2. Open Developer Tools by pressing **F12**.
3. Click the **Network** tab, then reload the page (**Cmd+R** on Mac, **F5** on Windows).
4. Click on any request in the list that goes to `kualibuild.com`.
5. Look on the right side under **Request Headers**.
6. Find the line that starts with `authorization:` and copy everything **after** the
   word `Bearer ` (the long string of letters and numbers after the space).

> **Keep your token private — treat it like a password.**
>
> Tokens expire after a few hours. If you see an "HTTP 401" error, get a fresh
> token by repeating these steps.

### 4. Your Kuali subdomain

This is the first part of your Kuali Build web address. For example, if you log in
at `https://cedarville.kualibuild.com`, your subdomain is `cedarville`.

---

## How to Run

1. Open **Terminal** (Mac) or **Command Prompt** (Windows).

2. Navigate to the folder where `kuali_creator_tracker.py` lives:
   ```
   cd Downloads
   ```
   (or wherever you saved the file)

3. Run the script with your subdomain and token:
   ```
   python3 kuali_creator_tracker.py --subdomain cedarville --token YOUR_TOKEN_HERE
   ```

   Replace `cedarville` with your subdomain and paste your actual token in place of
   `YOUR_TOKEN_HERE`.

4. The tool connects to Kuali Build, downloads the data, and prints a report.

### Keeping your token out of your command history (recommended)

Instead of putting the token directly in the command, you can set it as a temporary
environment variable. In Terminal, run:

```
export KUALI_TOKEN=YOUR_TOKEN_HERE
python3 kuali_creator_tracker.py --subdomain cedarville
```

Your token will be used automatically without appearing in your command history.

---

## Example Output

```
============================================================
  Kuali Creator Tracker
============================================================

Connecting to https://cedarville.kualibuild.com ...
Fetching global stats...
Fetching all apps (this may take a moment)...
  Fetched 25/89 apps...
  Fetched 50/89 apps...
  Fetched 75/89 apps...
  Fetched 89/89 apps...

================================================================
  Kuali Creator Tracker Report — 2026-04-23 14:32:00 UTC
================================================================

  GLOBAL STATS
  --------------------------------------------------
  Documents:               1,234
  Apps:                       89
  Spaces:                     12
  Integrations:                4
  Users:                     320
  Groups:                     15
  Categories:                  8

  APP CREATOR SUMMARY
  --------------------------------------------------
  Total unique creators:       47
  Apps tracked:                89
  Last snapshot:   2026-04-22 09:15:00 UTC

  NEW CREATORS SINCE LAST RUN (2)
  --------------------------------------------------
  jane.doe@cedarville.edu
    "Travel Request Form" (created 2026-04-22)

  john.smith@cedarville.edu
    "Equipment Request" (created 2026-04-23)
    "Leave of Absence Form" (created 2026-04-23)

================================================================

Done. History saved to creator_history.json
```

---

## Getting Email Notifications

If you want an email when new creators are found, add `--notify-email` with your
address:

```
python3 kuali_creator_tracker.py --subdomain cedarville --notify-email you@example.com
```

When new creators are detected, the script will ask you for your email server details
and password. **Your email password is never saved to disk** — it is only used for
that one send.

If you use Gmail, you will need to create a Google "App Password" (a special
one-time password for scripts). Search "Gmail App Password" for instructions.

---

## Running Automatically (Scheduled / Cron Job)

You can schedule the tracker to run weekly (or daily) so you never have to remember
to check manually.

### On Mac: Using cron

1. Open Terminal and type `crontab -e` (this opens your cron schedule).

2. Add a line like this to run every Monday at 8 AM:
   ```
   0 8 * * 1 KUALI_TOKEN=your_token /usr/bin/python3 /path/to/kuali_creator_tracker.py --subdomain cedarville >> /path/to/tracker.log 2>&1
   ```
   - Replace `your_token` with your bearer token
   - Replace `/path/to/` with the actual folder paths on your computer
   - The `>> tracker.log` part saves output to a log file so you can review it later

3. For automated email notifications (no interactive prompts), set these environment
   variables alongside KUALI_TOKEN:
   ```
   KUALI_TOKEN=your_token SMTP_HOST=smtp.gmail.com SMTP_USER=you@gmail.com SMTP_PASS=your_app_password /usr/bin/python3 /path/to/kuali_creator_tracker.py --subdomain cedarville --notify-email admin@example.com >> tracker.log 2>&1
   ```

> **Note:** Cron tokens expire just like browser tokens. You will need to update
> `KUALI_TOKEN` in your cron line every few hours/days when the token expires.

---

## All Command-Line Options

| Option | Description | Default |
|---|---|---|
| `--subdomain` | Your Kuali subdomain (required) | — |
| `--token` | Your bearer token | `KUALI_TOKEN` env var |
| `--notify-email` | Email to notify when new creators appear | (none) |
| `--history-file` | Path to the history JSON file | `creator_history.json` |
| `--smtp-host` | SMTP mail server hostname | `SMTP_HOST` env var |
| `--smtp-port` | SMTP port number | `587` or `SMTP_PORT` env var |
| `--smtp-user` | SMTP username (sender email) | `SMTP_USER` env var |
| `--smtp-pass` | SMTP password | `SMTP_PASS` env var (or prompted) |

---

## What Gets Saved

The file `creator_history.json` is created in the same folder as the script. It stores:

- A timestamp for each run
- The list of app creators (email addresses)
- App names, IDs, and creation dates
- Global stats counts (document count, user count, etc.)

**It does NOT store:**
- Your bearer token
- Your email password
- Any document content or form submissions

The history file grows slightly with each run. After a year of weekly runs with
~100 apps, it would typically be well under 1 MB.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `python3: command not found` | Install Python 3 from https://python.org |
| `ModuleNotFoundError: No module named 'requests'` | Run `pip3 install requests` in your terminal |
| `HTTP 401` error | Your bearer token has expired — get a fresh one from your browser |
| `Could not connect` | Check your subdomain spelling and internet connection |
| `creator_history.json is invalid or corrupt` | The script will ask if you want to reset it — say yes to start fresh |
| Email fails with "SMTPAuthenticationError" | For Gmail, use an App Password instead of your regular password |
| Email notification skipped | SMTP credentials were incomplete — the history is still saved, only the email failed |
| Apps show no creator in the report | Some system-generated apps have no creator; they are tracked but excluded from creator reports |
