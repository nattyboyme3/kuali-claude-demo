#!/usr/bin/env python3
"""
Kuali Re-File Trigger
Finds documents in an app submitted after a threshold date and triggers a
secondary workflow (default: "Re-File") on each one.

Usage (dry run):
  python3 kuali_refile_trigger.py --url URL --token TOKEN --app-id ID

Usage (run):
  python3 kuali_refile_trigger.py --url URL --token TOKEN --app-id ID --run

Pass the token via env var to avoid it appearing in shell history:
  KUALI_TOKEN=<token> python3 kuali_refile_trigger.py --url URL --app-id ID
"""
import sys
import os
import json
import argparse
import datetime
import concurrent.futures
import threading

try:
    import requests
except ImportError:
    print("ERROR: The 'requests' library is required.")
    print("Install it by running:  pip3 install requests")
    sys.exit(1)


GRAPHQL_PATH = "/app/api/v0/graphql"
DEFAULT_TIMEZONE = "America/New_York"

APP_NAME_QUERY = """
query AppName($appId: ID!) {
  app(id: $appId) {
    name
  }
}
"""

LIST_QUERY = """
query ListPageQuery($appId: ID!, $skip: Int!, $limit: Int!, $sort: [String!]) {
  app(id: $appId) {
    dataset {
      documentConnection(
        args: {skip: $skip, limit: $limit, sort: $sort, versionConfig: LATEST_VERSION}
        keyBy: ID
      ) {
        totalCount
        edges {
          node {
            id
            data
            meta
          }
        }
        pageInfo {
          hasNextPage
          skip
          limit
        }
      }
    }
  }
}
"""

SECONDARY_WORKFLOWS_QUERY = """
query SecondaryWorkflows($documentId: ID!) {
  document(id: $documentId, keyBy: ID) {
    id
    dataset {
      id
      secondaryWorkflows
      __typename
    }
    __typename
  }
}
"""

TRIGGER_MUTATION = """
mutation TriggerSecondaryWorkflow($args: TriggerSecondaryWorkflowInput!, $documentId: ID!) {
  triggerSecondaryWorkflow(args: $args) {
    id
    status
    query {
      document(id: $documentId) {
        id
        secondaryWorkflowData {
          id
          workflowId
          definitionId
          workflowName
          status
          simulation
          startedAt
          completedAt
          createdAt
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
"""


def graphql_request(config, operation_name, query, variables, raise_on_error=False):
    """Send one GraphQL request; return the parsed response data dict."""
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {config['token']}",
        "content-type": "application/json",
        "apollographql-client-name": "kuali-refile-trigger",
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
        print("Check that the base URL is correct and you have internet access.")
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
        description="Trigger a secondary workflow on Kuali Build documents submitted after a date."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Kuali Build base URL, e.g. https://cedarville.kualibuild.com",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("KUALI_TOKEN", ""),
        help="Bearer token (or set KUALI_TOKEN env var)",
    )
    parser.add_argument(
        "--app-id",
        required=True,
        dest="app_id",
        help="App ID from the document-list URL",
    )
    parser.add_argument(
        "--after",
        default="2026-04-30",
        help="Process documents submitted after this date (YYYY-MM-DD). Default: 2026-04-30",
    )
    parser.add_argument(
        "--workflow-name",
        default="Re-File",
        dest="workflow_name",
        help='Name of the secondary workflow to trigger. Default: "Re-File"',
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually trigger workflows (default is dry-run preview only)",
    )
    return parser.parse_args()


def gather_config():
    """Build config from CLI args."""
    args = parse_args()

    token = args.token
    if not token:
        print("ERROR: Bearer token is required. Pass --token or set KUALI_TOKEN env var.")
        sys.exit(1)

    try:
        threshold = datetime.datetime.fromisoformat(args.after).replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        print(f"ERROR: Invalid date '{args.after}'. Use YYYY-MM-DD format.")
        sys.exit(1)

    return {
        "base_url": args.url.rstrip("/"),
        "token": token,
        "app_id": args.app_id,
        "threshold": threshold,
        "workflow_name": args.workflow_name,
        "graphql_url": args.url.rstrip("/") + GRAPHQL_PATH,
        "do_run": args.run,
    }


def extract_title(data_blob):
    """Best-effort title extraction from a document's data blob."""
    if not data_blob or not isinstance(data_blob, dict):
        return "(no title)"
    for key in ("title", "Title", "name", "Name", "subject", "Subject",
                 "label", "Label", "description", "Description"):
        val = data_blob.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()[:80]
    for val in data_blob.values():
        if val and isinstance(val, str) and val.strip():
            return val.strip()[:80]
    return "(no title)"


def parse_meta(meta_blob):
    """Return (submitted_at_datetime, submitter_name) from meta blob."""
    if isinstance(meta_blob, str):
        try:
            meta_blob = json.loads(meta_blob)
        except json.JSONDecodeError:
            return None, "unknown"

    submitted_at_raw = meta_blob.get("submittedAt") or meta_blob.get("createdAt")
    if not submitted_at_raw:
        return None, "unknown"

    try:
        if isinstance(submitted_at_raw, (int, float)):
            ts = submitted_at_raw / 1000 if submitted_at_raw > 1e10 else submitted_at_raw
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        else:
            s = str(submitted_at_raw).replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None, "unknown"

    user = (
        meta_blob.get("submittedByUser")
        or meta_blob.get("createdByUser")
        or meta_blob.get("submittedBy")
        or {}
    )
    if isinstance(user, dict):
        name = (
            user.get("name")
            or user.get("displayName")
            or user.get("email")
            or "unknown"
        )
    elif isinstance(user, str):
        name = user
    else:
        name = "unknown"

    return dt, name


def fetch_documents_after(config):
    """Return list of dicts for all documents submitted after config['threshold']."""
    threshold = config["threshold"]
    app_id = config["app_id"]
    limit = 100
    skip = 0
    results = []

    print(f"\nFetching documents submitted after {threshold.date()} ...")

    while True:
        variables = {
            "appId": app_id,
            "skip": skip,
            "limit": limit,
            # Sort descending so newest documents come first; stop once we pass threshold
            "sort": ["-meta.submittedAt"],
        }
        data = graphql_request(config, "ListPageQuery", LIST_QUERY, variables)

        try:
            connection = data["app"]["dataset"]["documentConnection"]
        except (KeyError, TypeError):
            print("ERROR: Unexpected API response structure.")
            print("Check that your App ID is correct.")
            sys.exit(1)

        edges = connection.get("edges", [])
        page_info = connection.get("pageInfo", {})
        total_count = connection.get("totalCount", "?")

        if skip == 0:
            print(f"Total documents in app: {total_count}")

        passed_threshold = False
        for edge in edges:
            node = edge.get("node", {})
            meta_blob = node.get("meta", {})
            data_blob = node.get("data", {})

            if isinstance(meta_blob, str):
                try:
                    meta_blob = json.loads(meta_blob)
                except json.JSONDecodeError:
                    meta_blob = {}
            if isinstance(data_blob, str):
                try:
                    data_blob = json.loads(data_blob)
                except json.JSONDecodeError:
                    data_blob = {}

            submitted_at, submitter = parse_meta(meta_blob)
            if submitted_at is None:
                continue

            if submitted_at <= threshold:
                # Sorted descending — once we cross the threshold we're done
                passed_threshold = True
                break

            results.append({
                "id": node["id"],
                "title": extract_title(data_blob),
                "submitter": submitter,
                "submitted_at": submitted_at,
            })

        if passed_threshold or not page_info.get("hasNextPage", False) or not edges:
            break

        skip += limit

    print(f"Found {len(results)} document(s) submitted after {threshold.date()}.")
    return results


def resolve_workflow_id(config, document_id):
    """
    Fetch secondary workflows for a document and return the id of the one
    matching config['workflow_name']. Exits if not found.
    """
    data = graphql_request(
        config, "SecondaryWorkflows", SECONDARY_WORKFLOWS_QUERY,
        {"documentId": document_id},
    )

    try:
        raw = data["document"]["dataset"]["secondaryWorkflows"]
    except (KeyError, TypeError):
        print("ERROR: Could not retrieve secondary workflows from API response.")
        sys.exit(1)

    # secondaryWorkflows may be a JSON string or already a list
    if isinstance(raw, str):
        try:
            workflows = json.loads(raw)
        except json.JSONDecodeError:
            workflows = []
    elif isinstance(raw, list):
        workflows = raw
    else:
        workflows = []

    target_name = config["workflow_name"].strip().lower()
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        name = (wf.get("name") or wf.get("workflowName") or "").strip().lower()
        if name == target_name:
            return wf.get("id") or wf.get("workflowId")

    print(f"\nERROR: Secondary workflow '{config['workflow_name']}' not found.")
    print("Available workflows:")
    for wf in workflows:
        if isinstance(wf, dict):
            print(f"  - {wf.get('name') or wf.get('workflowName') or wf}")
    sys.exit(1)


def show_preview(documents, workflow_name):
    """Print a formatted table of documents that will be processed."""
    print(f"\n{'=' * 79}")
    print(f"  DRY RUN — {len(documents)} document(s) to trigger '{workflow_name}' on")
    print(f"{'=' * 79}")

    col_w = {"#": 4, "title": 35, "submitter": 24, "date": 12}
    header = (
        f"{'#':<{col_w['#']}} "
        f"{'Title':<{col_w['title']}} "
        f"{'Submitted By':<{col_w['submitter']}} "
        f"{'Date':<{col_w['date']}}"
    )
    print(header)
    print("-" * len(header))

    for i, doc in enumerate(documents, 1):
        title = doc["title"][:col_w["title"]]
        submitter = doc["submitter"][:col_w["submitter"]]
        date_str = doc["submitted_at"].strftime("%Y-%m-%d")
        print(
            f"{i:<{col_w['#']}} "
            f"{title:<{col_w['title']}} "
            f"{submitter:<{col_w['submitter']}} "
            f"{date_str:<{col_w['date']}}"
        )

    print(f"\nTotal: {len(documents)} document(s) would have '{workflow_name}' triggered.")


def trigger_workflows(config, documents, workflow_id):
    """Trigger the secondary workflow on all documents, 40 at a time."""
    total = len(documents)
    workflow_name = config["workflow_name"]
    print(f"\nTriggering '{workflow_name}' on {total} document(s) (40 concurrent)...")

    counter_lock = threading.Lock()
    completed = [0]
    failed = []

    def trigger_one(doc):
        variables = {
            "args": {
                "documentId": doc["id"],
                "workflowId": workflow_id,
                "timeZone": DEFAULT_TIMEZONE,
            },
            "documentId": doc["id"],
        }
        try:
            graphql_request(
                config, "TriggerSecondaryWorkflow", TRIGGER_MUTATION, variables,
                raise_on_error=True,
            )
            with counter_lock:
                completed[0] += 1
                n = completed[0]
            print(f"  [{n}/{total}] Triggered: {doc['title'][:50]}")
        except RuntimeError as e:
            with counter_lock:
                failed.append(doc["id"])
            print(f"  FAILED for {doc['id']} ({doc['title'][:40]}): {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        list(pool.map(trigger_one, documents))

    print(f"\nDone. {completed[0]} triggered, {len(failed)} failed.")
    if failed:
        print("Failed IDs:", ", ".join(failed))


def main():
    print("=" * 60)
    print("  Kuali Re-File Trigger")
    print("=" * 60)
    config = gather_config()

    app_data = graphql_request(config, "AppName", APP_NAME_QUERY, {"appId": config["app_id"]})
    app_name = (app_data.get("app") or {}).get("name") or config["app_id"]
    print(f"\nApp: {app_name}")

    documents = fetch_documents_after(config)

    if not documents:
        print("\nNo documents found after the threshold date. Nothing to do.")
        return

    # Resolve the workflow ID using the first document (dataset-level, same for all)
    print(f"\nLooking up secondary workflow '{config['workflow_name']}' ...")
    workflow_id = resolve_workflow_id(config, documents[0]["id"])
    print(f"Found workflow ID: {workflow_id}")

    show_preview(documents, config["workflow_name"])

    if not config["do_run"]:
        print("\n(Dry run only. Pass --run to trigger workflows.)")
        return

    trigger_workflows(config, documents, workflow_id)


if __name__ == "__main__":
    main()
