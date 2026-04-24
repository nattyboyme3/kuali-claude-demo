#!/usr/bin/env python3
"""
Kuali Document Cleaner
Finds and deletes Kuali Build documents submitted before a threshold date.

Usage (dry run):
  python3 kuali_document_cleaner.py --url URL --token TOKEN --app-id ID

Usage (delete):
  python3 kuali_document_cleaner.py --url URL --token TOKEN --app-id ID --delete

Pass the token via env var to avoid it appearing in shell history:
  KUALI_TOKEN=<token> python3 kuali_document_cleaner.py --url URL --app-id ID
"""
import sys
import os
import json
import argparse
import datetime

try:
    import requests
except ImportError:
    print("ERROR: The 'requests' library is required.")
    print("Install it by running:  pip3 install requests")
    sys.exit(1)


GRAPHQL_PATH = "/app/api/v0/graphql"

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

DELETE_MUTATION = """
mutation DeleteDocument($id: ID!) {
  deleteDocument(id: $id)
}
"""


def graphql_request(config, operation_name, query, variables, raise_on_error=False):
    """Send one GraphQL request; return the parsed response data dict."""
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {config['token']}",
        "content-type": "application/json",
        "apollographql-client-name": "kuali-document-cleaner",
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
        description="Find and delete Kuali Build documents submitted before a date."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Kuali Build base URL, e.g. https://cedarville-sbx.kualibuild.com",
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
        "--before",
        default="2025-01-01",
        help="Delete documents submitted before this date (YYYY-MM-DD). Default: 2025-01-01",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete after the dry-run preview (requires typing DELETE to confirm)",
    )
    return parser.parse_args()


def gather_config():
    """Build config from CLI args. Nothing is saved to disk."""
    args = parse_args()

    token = args.token
    if not token:
        print("ERROR: Bearer token is required. Pass --token or set KUALI_TOKEN env var.")
        sys.exit(1)

    try:
        threshold = datetime.datetime.fromisoformat(args.before).replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        print(f"ERROR: Invalid date '{args.before}'. Use YYYY-MM-DD format.")
        sys.exit(1)

    return {
        "base_url": args.url.rstrip("/"),
        "token": token,
        "app_id": args.app_id,
        "threshold": threshold,
        "graphql_url": args.url.rstrip("/") + GRAPHQL_PATH,
        "do_delete": args.delete,
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
    # Last resort: first non-empty string value
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
            # Unix timestamp — Kuali returns milliseconds
            ts = submitted_at_raw / 1000 if submitted_at_raw > 1e10 else submitted_at_raw
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        else:
            # ISO 8601 string — handle trailing Z
            s = str(submitted_at_raw).replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None, "unknown"

    # Submitter name: try several common meta paths
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


def fetch_documents_before(config):
    """Return list of dicts for all documents submitted before config['threshold']."""
    threshold = config["threshold"]
    app_id = config["app_id"]
    limit = 100
    skip = 0
    results = []
    total_fetched = 0

    print(f"\nFetching documents submitted before {threshold.date()} ...")

    while True:
        variables = {
            "appId": app_id,
            "skip": skip,
            "limit": limit,
            "sort": ["meta.submittedAt"],
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

        for edge in edges:
            node = edge.get("node", {})
            meta_blob = node.get("meta", {})
            data_blob = node.get("data", {})

            # meta/data may come back as JSON strings
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
                # Can't determine date — skip
                continue

            if submitted_at >= threshold:
                # Documents are sorted ascending; once we pass threshold we're done
                print(f"Scanned {total_fetched + len(results)} documents.")
                return results

            results.append({
                "id": node["id"],
                "title": extract_title(data_blob),
                "submitter": submitter,
                "submitted_at": submitted_at,
            })

        total_fetched += len(edges)

        if not page_info.get("hasNextPage", False) or not edges:
            break

        skip += limit

    print(f"Scanned {total_fetched} documents.")
    return results


def show_dry_run(documents):
    """Print a formatted table of documents that would be deleted."""
    print(f"\n{'=' * 79}")
    print(f"  DRY RUN — {len(documents)} document(s) to be deleted")
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

    print(f"\nTotal: {len(documents)} document(s) would be permanently deleted.")


def confirm_deletion(count):
    """Prompt user to type DELETE to confirm. Returns True if confirmed."""
    print("\nWARNING: Deletion is permanent and cannot be undone.")
    answer = input(
        f"To permanently delete these {count} document(s), type DELETE (all caps): "
    ).strip()
    return answer == "DELETE"


def delete_documents(config, documents):
    """Delete each document, printing progress."""
    total = len(documents)
    print(f"\nDeleting {total} document(s)...")
    deleted = 0
    failed = []

    for doc in documents:
        variables = {"id": doc["id"]}
        try:
            graphql_request(
                config, "DeleteDocument", DELETE_MUTATION, variables,
                raise_on_error=True,
            )
            deleted += 1
            print(f"  [{deleted}/{total}] Deleted: {doc['title'][:50]}")
        except RuntimeError as e:
            failed.append(doc["id"])
            print(f"  FAILED to delete {doc['id']}: {e}")

    print(f"\nDone. {deleted} deleted, {len(failed)} failed.")
    if failed:
        print("Failed IDs:", ", ".join(failed))


def main():
    print("=" * 60)
    print("  Kuali Document Cleaner")
    print("=" * 60)
    config = gather_config()
    documents = fetch_documents_before(config)
    if not documents:
        print("\nNo documents found before the threshold date. Nothing to delete.")
        return
    show_dry_run(documents)
    if not config["do_delete"]:
        print("\n(Dry run only. Pass --delete to enable deletion.)")
        return
    if confirm_deletion(len(documents)):
        delete_documents(config, documents)
    else:
        print("Deletion cancelled. No documents were deleted.")


if __name__ == "__main__":
    main()
