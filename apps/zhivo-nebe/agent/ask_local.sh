#!/bin/bash
# ask_local.sh [model] "prompt"  — or pipe text via stdin
# Delegation helper: bulk work goes to local Ollama on GX10, not to Claude tokens.
# Models: qwen3:30b-a3b (text/structure, fast MoE) | gemma3:27b (general/BG) | llava:34b (vision)
M="${1:-qwen3:30b-a3b}"
shift 2>/dev/null
P="$*"
if [ -z "$P" ]; then P=$(cat); fi
python3 - "$M" "$P" <<'EOF'
import json, sys, urllib.request
model, prompt = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    print(json.load(r).get("response", "").strip())
EOF
