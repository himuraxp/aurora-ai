#!/usr/bin/env python3
"""
Post inline conventional comments on a GitLab MR.

Usage:
    python3 mr-review-comments.py <project_path> <mr_iid> <comments_json_file>

The comments JSON file must be an array of objects with:
    - file:       path to the file (relative to repo root)
    - line:       line number in the new file (must be in the diff)
    - prefix:     conventional comment prefix (issue, suggestion, nitpick, question, thought, praise)
    - body:       comment body (WITHOUT the prefix — it will be prepended automatically)
                  OR full body (WITH the prefix) if already_formatted is true
    - already_formatted: (optional) if true, body is used as-is

Environment:
    Requires glab CLI authenticated.
"""
import json
import subprocess
import sys
import tempfile
import os
import urllib.parse
import time

VALID_PREFIXES = {"issue", "suggestion", "nitpick", "question", "thought", "praise"}


def run_glab_api(endpoint, method="GET", input_file=None, expect_json=True):
    """Run a glab api command and return the parsed JSON response."""
    cmd = ["glab", "api", "--method", method]
    if input_file:
        cmd += ["--input", input_file, "-H", "Content-Type: application/json"]
    cmd.append(endpoint)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(f"glab api failed ({result.returncode}): {stderr or stdout}")

    if not expect_json:
        return result.stdout

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def get_mr_metadata(project_encoded, mr_iid):
    """Fetch MR metadata including diff refs."""
    data = run_glab_api(f"projects/{project_encoded}/merge_requests/{mr_iid}")
    return {
        "base_sha": data["diff_refs"]["base_sha"],
        "head_sha": data["diff_refs"]["head_sha"],
        "start_sha": data["diff_refs"]["start_sha"],
        "source_branch": data.get("source_branch", ""),
        "title": data.get("title", ""),
    }


def fetch_file_lines(project_encoded, file_path, head_sha):
    """Fetch a file at a given ref and return its lines (1-indexed)."""
    encoded_path = urllib.parse.quote(file_path, safe="")
    endpoint = f"projects/{project_encoded}/repository/files/{encoded_path}/raw?ref={head_sha}"
    content = run_glab_api(endpoint, expect_json=False)
    return content.splitlines()


def post_inline_comment(project_encoded, mr_iid, base_sha, head_sha, start_sha,
                        file_path, line, body, max_retries=2):
    """Post a single inline comment as a discussion thread. Returns (success, has_position)."""
    payload = {
        "body": body,
        "position": {
            "base_sha": base_sha,
            "head_sha": head_sha,
            "start_sha": start_sha,
            "position_type": "text",
            "new_path": file_path,
            "new_line": line,
        },
    }

    for attempt in range(1, max_retries + 1):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(payload, f, ensure_ascii=False)
            payload_file = f.name

        try:
            endpoint = f"projects/{project_encoded}/merge_requests/{mr_iid}/discussions"
            resp = run_glab_api(endpoint, method="POST", input_file=payload_file)
        except RuntimeError:
            if attempt < max_retries:
                time.sleep(1)
                continue
            return False, False
        finally:
            os.unlink(payload_file)

        notes = resp.get("notes", []) if isinstance(resp, dict) else []
        has_position = any(n.get("position") for n in notes)
        return True, has_position

    return False, False


def format_comment_body(prefix, body, already_formatted=False):
    """Ensure the comment body starts with the conventional prefix."""
    if already_formatted:
        return body

    # Check if body already starts with a prefix
    first_line = body.strip().split("\n")[0]
    for p in VALID_PREFIXES:
        if first_line.startswith(f"{p}:"):
            return body

    return f"{prefix}: {body}"


def main():
    if len(sys.argv) != 4:
        print("Usage: mr-review-comments.py <project_path> <mr_iid> <comments_json_file>")
        sys.exit(1)

    project_path = sys.argv[1]
    mr_iid = sys.argv[2]
    comments_file = sys.argv[3]

    project_encoded = urllib.parse.quote(project_path, safe="")

    # Load comments
    with open(comments_file, "r", encoding="utf-8") as f:
        comments = json.load(f)

    if not isinstance(comments, list):
        print("ERROR: comments file must contain a JSON array")
        sys.exit(1)

    print(f"MR {mr_iid} — {project_path}")
    print(f"Posting {len(comments)} inline conventional comments...\n")

    # Fetch MR metadata
    try:
        meta = get_mr_metadata(project_encoded, mr_iid)
    except RuntimeError as e:
        print(f"ERROR: could not fetch MR metadata: {e}")
        sys.exit(1)

    base_sha = meta["base_sha"]
    head_sha = meta["head_sha"]
    start_sha = meta["start_sha"]

    success = 0
    failed = []

    for i, comment in enumerate(comments, 1):
        file_path = comment["file"]
        line = comment["line"]
        prefix = comment.get("prefix", "suggestion")
        body = comment["body"]
        already_formatted = comment.get("already_formatted", False)

        if prefix not in VALID_PREFIXES:
            print(f"[{i}/{len(comments)}] ⚠️  invalid prefix '{prefix}' — skipping")
            continue

        full_body = format_comment_body(prefix, body, already_formatted)
        label = full_body.split("\n")[0][:70]
        print(f"[{i}/{len(comments)}] {label}")

        ok, has_pos = post_inline_comment(
            project_encoded, mr_iid, base_sha, head_sha, start_sha,
            file_path, line, full_body,
        )

        if ok and has_pos:
            print(f"  ✅ inline — {file_path}:{line}")
            success += 1
        elif ok and not has_pos:
            print(f"  ⚠️  posted without position — {file_path}:{line}")
            success += 1
        else:
            print(f"  ❌ FAILED — {file_path}:{line}")
            failed.append(comment)

    print(f"\nDone: {success}/{len(comments)} comments posted.")
    if failed:
        print(f"Failed: {len(failed)}")
        for f in failed:
            print(f"  - {f['file']}:{f['line']}")

    return 0 if not failed else 1


if __name__ == "__main__":
    main()
