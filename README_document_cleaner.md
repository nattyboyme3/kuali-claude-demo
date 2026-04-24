# Kuali Document Cleaner

A tool that finds and permanently deletes documents in Kuali Build that were
submitted before a date you choose.

---

## Before You Start

You need:

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
6. Find the line that starts with `authorization:` and copy everything **after** the word `Bearer ` (including the long string of letters and numbers).

> **Keep your token private — treat it like a password.**
>
> Tokens expire after a few hours. If you get an authentication error, repeat these steps to get a fresh token.

### 4. The App ID for the form you want to clean

1. In your browser, navigate to the document list for the form you want to clean up.
2. Look at the URL in your browser's address bar:
   ```
   https://cedarville-sbx.kualibuild.com/document-list/67ae5d037386f0027ff2d54f
   ```
3. The long string of letters and numbers at the very end is the App ID (e.g. `67ae5d037386f0027ff2d54f`).

---

## How to Run

1. Open **Terminal** (Mac) or **Command Prompt** (Windows).

2. Navigate to the folder where `kuali_document_cleaner.py` lives. For example, if it is in your Downloads folder:
   ```
   cd Downloads
   ```

3. Run the script:
   ```
   python3 kuali_document_cleaner.py
   ```

4. You will be asked four questions:

   | Prompt | What to enter |
   |---|---|
   | **Kuali Build base URL** | The website address, e.g. `https://cedarville-sbx.kualibuild.com` |
   | **Bearer token** | The token you copied from your browser (your typing will be hidden) |
   | **App ID** | The long ID from the URL (step 4 above) |
   | **Threshold date** | Documents submitted *before* this date will be deleted. Press Enter to use the default: `2025-01-01` |

5. The tool will **show you a preview first** — a table listing every document it would delete, including the submitter's name, document title, and date submitted.

6. After reviewing the list:
   - To **proceed with deletion**, type `DELETE` (all caps) and press Enter.
   - To **cancel without deleting anything**, press Enter without typing anything.

7. If you chose to delete, the tool will delete each document one by one and show you its progress.

---

## Example Session

```
============================================================
  Kuali Document Cleaner
============================================================

You will be prompted for connection details.
These are NOT saved anywhere after the program exits.

Kuali Build base URL
  (e.g. https://cedarville-sbx.kualibuild.com): https://cedarville-sbx.kualibuild.com

Bearer token (from your browser — input is hidden):

App ID
  (the long ID in the document-list URL, e.g. 67ae5d037386f0027ff2d54f): 67ae5d037386f0027ff2d54f

Delete documents submitted BEFORE this date [2025-01-01]:

Fetching documents submitted before 2025-01-01 ...
Total documents in app: 142
Scanned 142 documents.

===============================================================================
  DRY RUN — 3 document(s) to be deleted
===============================================================================
#    Title                               Submitted By             Date
---------------------------------------------------------------------
1    Fall 2024 Travel Request            Jane Smith               2024-10-15
2    Conference Registration             Bob Jones                2024-11-02
3    Equipment Purchase Request          Alice Brown              2024-12-20

Total: 3 document(s) would be permanently deleted.

WARNING: Deletion is permanent and cannot be undone.
To permanently delete these 3 document(s), type DELETE (all caps): DELETE

Deleting 3 document(s)...
  [1/3] Deleted: Fall 2024 Travel Request
  [2/3] Deleted: Conference Registration
  [3/3] Deleted: Equipment Purchase Request

Done. 3 deleted, 0 failed.
```

---

## What the Tool Does NOT Do

- It does **not** save your token, credentials, or any document data to disk.
- It does **not** delete documents that were submitted *on or after* the threshold date.
- It does **not** skip the confirmation step — you must type `DELETE` to proceed.
- It does **not** modify documents — it only deletes them.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `python3: command not found` | Install Python 3 from https://python.org |
| `ModuleNotFoundError: No module named 'requests'` | Run `pip3 install requests` in your terminal |
| `HTTP 401` error | Your bearer token has expired — get a fresh one from your browser (see step 3 above) |
| `Unexpected API response structure` | Double-check that your App ID is correct |
| Documents show `(no title)` | The form uses an unusual field name for its title — the deletion will still work correctly |
| The list looks wrong | Press Enter (without typing DELETE) to cancel — nothing will be deleted |
