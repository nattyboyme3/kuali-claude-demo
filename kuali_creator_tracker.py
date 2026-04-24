#!/usr/bin/env python3
"""
Kuali Creator Tracker
Tracks app creator stats in Kuali Build over time and reports new creators.

Usage:
  python3 kuali_creator_tracker.py --subdomain cedarville --token YOUR_TOKEN

Pass the token via env var to avoid it appearing in shell history:
  KUALI_TOKEN=your_token python3 kuali_creator_tracker.py --subdomain cedarville

With email notification:
  python3 kuali_creator_tracker.py --subdomain cedarville --notify-email admin@example.com
"""
import sys
import os
import json
import argparse
import datetime
import smtplib
import getpass
import collections
import concurrent.futures
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import requests
except ImportError:
    print("ERROR: The 'requests' library is required.")
    print("Install it by running:  pip3 install requests")
    sys.exit(1)


GRAPHQL_PATH = "/app/api/v0/graphql"
PAGE_LIMIT = 25
DEFAULT_HISTORY_FILE = "creator_history.json"

DETAILS_QUERY = """
query Details {
  totalDocumentCount
  totalAppCount
  totalSpaceCount
  totalIntegrationCount
  usersConnection(args: {limit: 1}) {
    totalCount
  }
  groupsConnection(args: {limit: 1}) {
    totalCount
  }
  categoriesConnection(args: {limit: 1}) {
    totalCount
  }
}
"""

USAGE_APPS_QUERY = """
query UsageApps($args: AppsConnectionInput!) {
  appsConnection(args: $args) {
    totalCount
    edges {
      node {
        id
        name
        type
        createdAt
        createdBy {
          id
          email
        }
        documentCount
      }
    }
  }
}
"""


def graphql_request(config, operation_name, query, variables, raise_on_error=False):
    """Send one GraphQL request; return the parsed response data dict."""
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {config['token']}",
        "content-type": "application/json",
        "apollographql-client-name": "kuali-creator-tracker",
    }
    cookies = {"authToken": config["token"]}
    payload = {
        "operationName": operation_name,
        "variables": variables,
        "query": query,
    }
    try:
        resp = requests.post(
            config["graphql_url"],
            headers=headers,
            cookies=cookies,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        msg = f"Could not connect to {config['graphql_url']}"
        if raise_on_error:
            raise RuntimeError(msg)
        print(f"\nERROR: {msg}")
        print("Check that the subdomain is correct and you have internet access.")
        sys.exit(1)
    except requests.exceptions.HTTPError:
        msg = f"HTTP {resp.status_code} from API"
        if raise_on_error:
            raise RuntimeError(msg)
        print(f"\nERROR: {msg}")
        if resp.status_code == 401:
            print("Your bearer token appears to be invalid or expired.")
        sys.exit(1)

    body = resp.json()
    if "errors" in body:
        msg = "; ".join(e.get("message", str(e)) for e in body["errors"])
        if raise_on_error:
            raise RuntimeError(f"GraphQL errors: {msg}")
        print(f"GraphQL error: {msg}")
        sys.exit(1)
    return body.get("data", {})


def parse_args():
    parser = argparse.ArgumentParser(
        description="Track Kuali Build app creator stats over time and report new creators."
    )
    parser.add_argument(
        "--subdomain",
        required=True,
        help="Your Kuali subdomain, e.g. cedarville (from cedarville.kualibuild.com)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("KUALI_TOKEN", ""),
        help="Bearer token (or set KUALI_TOKEN env var)",
    )
    parser.add_argument(
        "--notify-email",
        dest="notify_email",
        default="",
        help="Email address to notify when new creators are found",
    )
    parser.add_argument(
        "--history-file",
        dest="history_file",
        default=DEFAULT_HISTORY_FILE,
        help=f"Path to history JSON file (default: {DEFAULT_HISTORY_FILE})",
    )
    parser.add_argument(
        "--smtp-host",
        dest="smtp_host",
        default=os.environ.get("SMTP_HOST", ""),
        help="SMTP server hostname (or set SMTP_HOST env var)",
    )
    parser.add_argument(
        "--smtp-port",
        dest="smtp_port",
        default=os.environ.get("SMTP_PORT", "587"),
        help="SMTP server port (default: 587, or set SMTP_PORT env var)",
    )
    parser.add_argument(
        "--smtp-user",
        dest="smtp_user",
        default=os.environ.get("SMTP_USER", ""),
        help="SMTP username / sender email (or set SMTP_USER env var)",
    )
    parser.add_argument(
        "--smtp-pass",
        dest="smtp_pass",
        default=os.environ.get("SMTP_PASS", ""),
        help="SMTP password (or set SMTP_PASS env var; prompted if missing)",
    )
    return parser.parse_args()


def gather_config():
    """Build config from CLI args and env vars. Nothing is saved to disk."""
    args = parse_args()

    token = args.token
    if not token:
        print("ERROR: Bearer token is required. Pass --token or set KUALI_TOKEN env var.")
        sys.exit(1)

    # Normalize subdomain — strip protocol/slashes if user accidentally included them
    subdomain = args.subdomain.strip()
    for prefix in ("https://", "http://"):
        if subdomain.startswith(prefix):
            subdomain = subdomain[len(prefix):]
            print(f"Note: Using subdomain '{subdomain}' (stripped protocol prefix).")
    subdomain = subdomain.rstrip("/").split(".")[0]  # take only the first segment
    if not subdomain:
        print("ERROR: Subdomain cannot be empty.")
        sys.exit(1)

    base_url = f"https://{subdomain}.kualibuild.com"
    graphql_url = base_url + GRAPHQL_PATH

    try:
        smtp_port = int(args.smtp_port)
    except ValueError:
        print(f"ERROR: Invalid SMTP port '{args.smtp_port}'. Must be a number.")
        sys.exit(1)

    return {
        "token": token,
        "base_url": base_url,
        "graphql_url": graphql_url,
        "subdomain": subdomain,
        "history_file": args.history_file,
        "notify_email": args.notify_email,
        "smtp_host": args.smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": args.smtp_user,
        "smtp_pass": args.smtp_pass,
    }


def load_history(history_file):
    """Return parsed history dict, or a fresh scaffold if the file doesn't exist."""
    if not os.path.exists(history_file):
        return {"snapshots": []}

    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "snapshots" not in data:
            raise ValueError("Unexpected structure")
        return data
    except (json.JSONDecodeError, ValueError):
        print(f"\nWARNING: History file '{history_file}' is invalid or corrupt.")
        answer = input("Reset it and start fresh? This will lose previous history. (yes/no): ").strip().lower()
        if answer in ("yes", "y"):
            return {"snapshots": []}
        print("Exiting to preserve your history file. Delete or fix it manually.")
        sys.exit(1)


def save_history(history_file, history_data):
    """Write history atomically to avoid partial writes."""
    tmp_file = history_file + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=2)
        os.replace(tmp_file, history_file)
    except OSError as e:
        print(f"\nERROR: Could not write history file '{history_file}': {e}")
        print("Check that you have write permission to this directory.")
        sys.exit(1)


def fetch_global_stats(config):
    """Return a flat dict of global Kuali stats."""
    data = graphql_request(config, "Details", DETAILS_QUERY, {})
    return {
        "totalDocumentCount": data.get("totalDocumentCount") or 0,
        "totalAppCount": data.get("totalAppCount") or 0,
        "totalSpaceCount": data.get("totalSpaceCount") or 0,
        "totalIntegrationCount": data.get("totalIntegrationCount") or 0,
        "totalUserCount": (data.get("usersConnection") or {}).get("totalCount") or 0,
        "totalGroupCount": (data.get("groupsConnection") or {}).get("totalCount") or 0,
        "totalCategoryCount": (data.get("categoriesConnection") or {}).get("totalCount") or 0,
    }


def _fetch_page(config, skip):
    """Fetch one page of apps and return (skip, edges, total_count)."""
    variables = {
        "args": {
            "limit": PAGE_LIMIT,
            "skip": skip,
            "sort": ["-createdAt"],
            "query": "",
        }
    }
    data = graphql_request(config, "UsageApps", USAGE_APPS_QUERY, variables)
    try:
        connection = data["appsConnection"]
    except (KeyError, TypeError):
        print("ERROR: Unexpected API response structure for appsConnection.")
        sys.exit(1)
    return skip, connection.get("edges", []), connection.get("totalCount", 0)


def _normalize_edges(edges):
    """Convert raw GraphQL edges to normalized app dicts."""
    apps = []
    for edge in edges:
        node = edge.get("node", {})
        creator = node.get("createdBy") or {}
        apps.append({
            "id": node.get("id", ""),
            "name": node.get("name", "(unnamed)"),
            "type": node.get("type", ""),
            "createdAt": node.get("createdAt", ""),
            "documentCount": node.get("documentCount") or 0,
            "creatorId": creator.get("id"),
            "creatorEmail": creator.get("email"),
        })
    return apps


def fetch_all_apps(config):
    """Return a normalized list of all apps, fetching all pages in parallel."""
    # Fetch the first page to discover totalCount
    _, first_edges, total_count = _fetch_page(config, 0)
    print(f"  Fetched {len(first_edges)}/{total_count} apps...")

    remaining_skips = [
        skip for skip in range(PAGE_LIMIT, total_count, PAGE_LIMIT)
    ]

    # pages_by_skip will hold results in insertion order after parallel fetch
    pages_by_skip = {0: first_edges}

    if remaining_skips:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(remaining_skips))) as pool:
            futures = {pool.submit(_fetch_page, config, skip): skip for skip in remaining_skips}
            for future in concurrent.futures.as_completed(futures):
                skip, edges, _ = future.result()
                pages_by_skip[skip] = edges
                fetched = sum(len(e) for e in pages_by_skip.values())
                print(f"  Fetched {fetched}/{total_count} apps...")

    # Reassemble in sorted page order
    all_apps = []
    for skip in sorted(pages_by_skip):
        all_apps.extend(_normalize_edges(pages_by_skip[skip]))

    return all_apps


def build_snapshot(stats, apps):
    """Build a snapshot dict to append to history."""
    seen_emails = set()
    creators = []
    for app in apps:
        email = app.get("creatorEmail")
        if email and email not in seen_emails:
            seen_emails.add(email)
            creators.append({"id": app.get("creatorId"), "email": email})
    creators.sort(key=lambda c: c["email"])

    return {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "stats": stats,
        "apps": apps,
        "creators": creators,
    }


def find_new_creators(current_snapshot, previous_snapshot):
    """Return list of new creators (with their apps) compared to the previous snapshot."""
    if previous_snapshot is None:
        return []

    previous_emails = {c["email"] for c in previous_snapshot.get("creators", []) if c.get("email")}
    current_emails = {c["email"] for c in current_snapshot.get("creators", []) if c.get("email")}
    new_emails = current_emails - previous_emails

    if not new_emails:
        return []

    # Group each new creator's apps
    grouped = collections.defaultdict(list)
    for app in current_snapshot.get("apps", []):
        if app.get("creatorEmail") in new_emails:
            grouped[app["creatorEmail"]].append({
                "name": app.get("name", "(unnamed)"),
                "createdAt": app.get("createdAt", ""),
            })

    return [
        {"email": email, "apps": sorted(grouped[email], key=lambda a: a["createdAt"])}
        for email in sorted(new_emails)
    ]


def _format_timestamp(iso_str):
    """Return a readable UTC string from an ISO timestamp, or the raw string on failure."""
    if not iso_str:
        return "unknown"
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return iso_str


def _format_date(iso_str):
    """Return YYYY-MM-DD from an ISO timestamp."""
    if not iso_str:
        return "unknown"
    try:
        return iso_str[:10]
    except Exception:
        return iso_str


def print_stats_report(current_snapshot, new_creators, previous_snapshot):
    """Print a formatted report to stdout."""
    stats = current_snapshot.get("stats", {})
    creators = current_snapshot.get("creators", [])
    apps = current_snapshot.get("apps", [])
    timestamp = _format_timestamp(current_snapshot.get("timestamp", ""))

    w = 64
    print()
    print("=" * w)
    print(f"  Kuali Creator Tracker Report — {timestamp}")
    print("=" * w)

    print()
    print("  GLOBAL STATS")
    print("  " + "-" * 50)
    print(f"  {'Documents:':<22} {stats.get('totalDocumentCount', 0):>8,}")
    print(f"  {'Apps:':<22} {stats.get('totalAppCount', 0):>8,}")
    print(f"  {'Spaces:':<22} {stats.get('totalSpaceCount', 0):>8,}")
    print(f"  {'Integrations:':<22} {stats.get('totalIntegrationCount', 0):>8,}")
    print(f"  {'Users:':<22} {stats.get('totalUserCount', 0):>8,}")
    print(f"  {'Groups:':<22} {stats.get('totalGroupCount', 0):>8,}")
    print(f"  {'Categories:':<22} {stats.get('totalCategoryCount', 0):>8,}")

    print()
    print("  APP CREATOR SUMMARY")
    print("  " + "-" * 50)
    print(f"  {'Total unique creators:':<28} {len(creators):>6,}")
    print(f"  {'Apps tracked:':<28} {len(apps):>6,}")
    if previous_snapshot:
        prev_ts = _format_timestamp(previous_snapshot.get("timestamp", ""))
        print(f"  {'Last snapshot:':<28} {prev_ts}")
    else:
        print(f"  {'Last snapshot:':<28} (none — this is the first run)")

    print()
    if new_creators:
        print(f"  NEW CREATORS SINCE LAST RUN ({len(new_creators)})")
        print("  " + "-" * 50)
        for creator in new_creators:
            print(f"  {creator['email']}")
            for app in creator["apps"]:
                date_str = _format_date(app["createdAt"])
                print(f'    "{app["name"]}" (created {date_str})')
        print()
    elif previous_snapshot is None:
        print("  First run — baseline established. Run again later to detect new creators.")
        print()
    else:
        print("  No new creators since last run.")
        print()

    print("=" * w)


def _build_email_body(new_creators, current_snapshot):
    """Build the plain-text body for the notification email."""
    timestamp = _format_timestamp(current_snapshot.get("timestamp", ""))
    lines = [
        f"Kuali Creator Tracker — {timestamp}",
        "",
        f"New app creators found: {len(new_creators)}",
        "",
    ]
    for creator in new_creators:
        lines.append(creator["email"])
        for app in creator["apps"]:
            date_str = _format_date(app["createdAt"])
            lines.append(f'  "{app["name"]}" (created {date_str})')
        lines.append("")
    return "\n".join(lines)


def send_email_notification(config, new_creators, current_snapshot):
    """Send an email notification listing new creators. Non-fatal on SMTP failure."""
    notify_email = config["notify_email"]
    print(f"\nNew creators found. Preparing to send notification to {notify_email}...")

    smtp_host = config["smtp_host"] or input("SMTP server (e.g. smtp.gmail.com): ").strip()
    smtp_port = config["smtp_port"]
    smtp_user = config["smtp_user"] or input("Sender email address: ").strip()
    smtp_pass = config["smtp_pass"] or getpass.getpass("Sender email password (hidden): ")

    if not smtp_host or not smtp_user or not smtp_pass:
        print("SMTP credentials incomplete. Email notification skipped.")
        return

    subject = f"Kuali Build: {len(new_creators)} new app creator(s) detected"
    body = _build_email_body(new_creators, current_snapshot)

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = notify_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, notify_email, msg.as_string())
        print(f"Email sent to {notify_email}.")
    except smtplib.SMTPException as e:
        print(f"SMTP error: {e}")
        print("Email notification skipped.")
    except OSError as e:
        print(f"Could not reach SMTP server: {e}")
        print("Email notification skipped.")


def main():
    print("=" * 60)
    print("  Kuali Creator Tracker")
    print("=" * 60)

    config = gather_config()
    history = load_history(config["history_file"])
    previous_snapshot = history["snapshots"][-1] if history["snapshots"] else None

    print(f"\nConnecting to https://{config['subdomain']}.kualibuild.com ...")
    print("Fetching global stats...")
    stats = fetch_global_stats(config)

    print("Fetching all apps (this may take a moment)...")
    apps = fetch_all_apps(config)

    current_snapshot = build_snapshot(stats, apps)
    new_creators = find_new_creators(current_snapshot, previous_snapshot)

    history["snapshots"].append(current_snapshot)
    save_history(config["history_file"], history)

    print_stats_report(current_snapshot, new_creators, previous_snapshot)

    if config["notify_email"] and new_creators:
        send_email_notification(config, new_creators, current_snapshot)

    print(f"Done. History saved to {config['history_file']}")


if __name__ == "__main__":
    main()
