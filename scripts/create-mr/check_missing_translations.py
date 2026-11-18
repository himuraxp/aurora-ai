#!/usr/bin/env python3
"""Check transloco literals extracted from added diff lines against the
project's translation reference file. Pure local: no git, no network.

The wrapper (check_missing_translations.sh) feeds the added lines; this
script extracts the literals, compares them against the JSON keys (flat
or nested), and prints one JSON object.
"""

import argparse
import json
import re
import sys

# Each pattern captures the raw literal. (?:[^'\\]|\\.)* traverses escaped
# quotes (l\'état) without ending the string early.
PATTERNS = (
    re.compile(r"translate\(\s*'((?:[^'\\]|\\.)*)'\s*[,)]"),
    re.compile(r'translate\(\s*"((?:[^"\\]|\\.)*)"\s*[,)]'),
    re.compile(r"'((?:[^'\\]|\\.)*)'\s*\|\s*transloco\b"),
    re.compile(r'"((?:[^"\\]|\\.)*)"\s*\|\s*transloco\b'),
)

UNESCAPES = (("\\'", "'"), ('\\"', '"'), ("\\\\", "\\"))


def unescape_literal(literal: str) -> str:
    for old, new in UNESCAPES:
        literal = literal.replace(old, new)
    return literal


def flatten_keys(value, prefix: str, keys: set) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            flatten_keys(child, f"{prefix}.{key}" if prefix else key, keys)
    else:
        keys.add(prefix)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--added-file", required=True)
    parser.add_argument("--translations-file", required=True)
    parser.add_argument("--checked-files", type=int, default=0)
    parser.add_argument("--max-examples", type=int, default=20)
    parser.add_argument(
        "--action",
        default=None,
        choices=["label", "none", "skipped-no-translations-file", "skipped-no-changed-files"],
    )
    args = parser.parse_args()

    try:
        with open(args.added_file, encoding="utf-8", errors="replace") as fh:
            added_text = fh.read()
    except OSError as exc:
        print(f"ERROR: cannot read added-lines file: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.translations_file, encoding="utf-8") as fh:
            translations = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read translations file: {exc}", file=sys.stderr)
        sys.exit(1)

    keys: set = set()
    flatten_keys(translations, "", keys)

    literals: list = []
    for pattern in PATTERNS:
        for raw in pattern.findall(added_text):
            literal = unescape_literal(raw)
            if literal and literal not in literals:
                literals.append(literal)

    missing = [literal for literal in literals if literal not in keys]
    truncated = len(missing) > args.max_examples
    examples = missing[: args.max_examples]

    if args.action is not None:
        action = args.action
    else:
        action = "label" if missing else "none"

    print(
        json.dumps(
            {
                "action": action,
                "missing": examples,
                "missingCount": len(missing),
                "missingTruncated": truncated,
                "extractedCount": len(literals),
                "checkedFiles": args.checked_files,
                "translationsFile": args.translations_file,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
