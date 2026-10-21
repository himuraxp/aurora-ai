#!/usr/bin/env python3
"""build_multipart.py — Build a binary-safe multipart/form-data body for GitLab uploads.

Writes the body to --out and prints ONLY the generated boundary to stdout.

Why this script exists: `glab api` has no gh-style `-F file=@...` multipart flag
(that is GitHub CLI syntax — glab's --field/--raw-field produce JSON-encoded
fields, not multipart). The validated upload path (glab 1.86, proven 3/3 in
site-manager MR !604) is:

    build_multipart.py --file capture.png --out body.multipart   # prints boundary
    glab api --method POST \
      --input body.multipart \
      -H "Content-Type: multipart/form-data; boundary=<boundary>" \
      /projects/<id>/uploads
    # -> 201 {"alt": ..., "markdown": ..., "url": ..., "full_path": ...}

Constraints: glab only (never curl — token security), the body file contains
only the media content, the boundary is random per call (secrets.token_hex).
"""

import argparse
import mimetypes
import os
import secrets
import sys

EXIT_ERROR = 1

# Explicit map for the media types create-mr actually uploads (browser
# screenshots and comparison tables); mimetypes.guess_type is the fallback.
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


def content_type_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in CONTENT_TYPES:
        return CONTENT_TYPES[ext]
    guessed = mimetypes.guess_type(path)[0]
    return guessed or "application/octet-stream"


def safe_filename(path: str) -> str:
    # Content-Disposition filename is a quoted-string (RFC 2183): strip quotes,
    # backslashes (quoting escape) and CR/LF (header injection) so a hostile
    # filename cannot corrupt the part headers.
    name = os.path.basename(path)
    for ch in ('"', "\\", "\r", "\n"):
        name = name.replace(ch, "")
    return name or "upload"


def build_body(file_path: str, out_path: str) -> str:
    boundary = "aurora" + secrets.token_hex(16)
    ctype = content_type_for(file_path)
    with open(file_path, "rb") as f:
        payload = f.read()
    headers = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe_filename(file_path)}"\r\n'
        f"Content-Type: {ctype}\r\n"
        f"\r\n"
    ).encode("utf-8")
    closing = f"\r\n--{boundary}--\r\n".encode("utf-8")
    with open(out_path, "wb") as f:
        f.write(headers + payload + closing)
    return boundary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a binary-safe multipart/form-data body for a GitLab upload."
    )
    parser.add_argument("--file", required=True, help="Media file to embed")
    parser.add_argument("--out", required=True, help="Path of the multipart body file to write")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        return EXIT_ERROR
    try:
        boundary = build_body(args.file, args.out)
    except OSError as exc:
        print(f"ERROR: cannot build multipart body: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(boundary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
