#!/usr/bin/env bash
# build_body.sh — Assemble the MR description body from a template or default format.
#
# Usage: build_body.sh \
#   --context "<context text>" \
#   --solution "<solution text>" \
#   --resources "<resources text, multiline>" \
#   --media "<media markdown, optional>" \
#   --template-file <path>   # optional, path to template file
#
# Outputs the assembled MR body to stdout.
# If a template is provided, replaces placeholders:
#   {{CONTEXT}}, {{SOLUTION}}, {{RESOURCES}}, {{MEDIA}}
# If no template, uses the default format:
#   ## Context / ## Solution / ## Resources / ## Media

set -euo pipefail

CONTEXT=""
SOLUTION=""
RESOURCES=""
MEDIA=""
TEMPLATE_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --context)
      CONTEXT="$2"
      shift 2
      ;;
    --solution)
      SOLUTION="$2"
      shift 2
      ;;
    --resources)
      RESOURCES="$2"
      shift 2
      ;;
    --media)
      MEDIA="$2"
      shift 2
      ;;
    --template-file)
      TEMPLATE_FILE="$2"
      shift 2
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# Validate required fields
if [ -z "$(echo "$CONTEXT" | tr -d '[:space:]')" ]; then
  echo "ERROR: --context is required and must not be whitespace-only." >&2
  exit 1
fi

if [ -z "$(echo "$SOLUTION" | tr -d '[:space:]')" ]; then
  echo "ERROR: --solution is required and must not be whitespace-only." >&2
  exit 1
fi

# Default resources
if [ -z "$RESOURCES" ]; then
  RESOURCES="- (none)"
fi

# Use template if available
if [ -n "$TEMPLATE_FILE" ] && [ -f "$TEMPLATE_FILE" ]; then
  # Newline-safe placeholder replacement (awk, literal index/substr — no
  # regex interpretation). Values are passed via the environment so awk
  # never interprets backslash sequences in user-provided text, and
  # multi-line values (e.g. a Before/After table appended to the solution)
  # are replaced correctly. There is deliberately no fallback that would
  # silently print the raw template on a replacement failure: under
  # `set -euo pipefail` an awk error exits non-zero (fail-closed).
  export MR_BODY_CONTEXT="$CONTEXT"
  export MR_BODY_SOLUTION="$SOLUTION"
  export MR_BODY_RESOURCES="$RESOURCES"
  export MR_BODY_MEDIA="$MEDIA"
  # French sentence as written in real templates (right single quote) + the
  # legacy straight-quote variant (pre-existing implementation quirk).
  export MR_BODY_INCREMENT_DESC='Description de l'"'"'incrément ou du fix à insérer ici'
  export MR_BODY_INCREMENT_DESC_STRAIGHT='Description de l"incrément ou du fix à insérer ici'

  awk '
    # Replace every occurrence of a literal placeholder in a line. The
    # inserted text is never re-scanned (same semantics as sed) and may
    # span multiple lines.
    function replace(line, ph, rep,    out, start, idx, plen) {
      plen = length(ph)
      out = ""
      start = 1
      while ((idx = index(substr(line, start), ph)) > 0) {
        idx = idx + start - 1
        out = out substr(line, start, idx - start) rep
        start = idx + plen
      }
      return out substr(line, start)
    }
    {
      line = $0
      line = replace(line, "{{CONTEXT}}", ENVIRON["MR_BODY_CONTEXT"])
      line = replace(line, "{{SOLUTION}}", ENVIRON["MR_BODY_SOLUTION"])
      line = replace(line, "{{RESOURCES}}", ENVIRON["MR_BODY_RESOURCES"])
      line = replace(line, "{{MEDIA}}", ENVIRON["MR_BODY_MEDIA"])
      line = replace(line, "[]", ENVIRON["MR_BODY_CONTEXT"])
      line = replace(line, ENVIRON["MR_BODY_INCREMENT_DESC"], ENVIRON["MR_BODY_CONTEXT"])
      line = replace(line, ENVIRON["MR_BODY_INCREMENT_DESC_STRAIGHT"], ENVIRON["MR_BODY_CONTEXT"])
      line = replace(line, "Description détaillée", ENVIRON["MR_BODY_SOLUTION"])
      line = replace(line, "Insérer les liens ici", ENVIRON["MR_BODY_RESOURCES"])
      line = replace(line, "Insérer les images ou vidéos ici", ENVIRON["MR_BODY_MEDIA"])
      print line
    }
  ' "$TEMPLATE_FILE"
  exit 0
fi

# Default format (no template)
if [ -n "$MEDIA" ]; then
  cat <<EOF
## Contexte

${CONTEXT}

## Solution

${SOLUTION}

## Ressources

${RESOURCES}

## Media

${MEDIA}
EOF
else
  cat <<EOF
## Contexte

${CONTEXT}

## Solution

${SOLUTION}

## Ressources

${RESOURCES}
EOF
fi
