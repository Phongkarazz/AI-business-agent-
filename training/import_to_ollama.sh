#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <path-to-veraxus-gguf> [ollama-model-tag]"
  echo "Example: $0 ~/Downloads/veraxus-coder-3b-q4_k_m.gguf veraxus-coder:3b"
  exit 1
fi

GGUF_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
MODEL_TAG="${2:-veraxus-coder:3b}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_MODELFILE="$(mktemp "${TMPDIR:-/tmp}/veraxus-modelfile.XXXXXX")"

if [ ! -f "$GGUF_PATH" ]; then
  echo "Error: GGUF file not found at $GGUF_PATH" >&2
  exit 1
fi

python3 - "$SCRIPT_DIR/Modelfile.template" "$GGUF_PATH" "$TMP_MODELFILE" <<'PY'
import pathlib, sys
tpl = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
rendered = tpl.replace("./__GGUF_FILE__", sys.argv[2])
pathlib.Path(sys.argv[3]).write_text(rendered, encoding="utf-8")
PY

echo "Importing $GGUF_PATH into Ollama as '$MODEL_TAG'..."
ollama create "$MODEL_TAG" -f "$TMP_MODELFILE"
rm -f "$TMP_MODELFILE"

echo "Running quick JSON smoke test on '$MODEL_TAG'..."
ollama run "$MODEL_TAG" 'Trả về JSON duy nhất: {"status":"ok","sql":"SELECT 1;"}' || true
echo "Done! Select '$MODEL_TAG' in Veraxus (Ollama Local AI Offline)."
