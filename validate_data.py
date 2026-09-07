#!/usr/bin/env python3
import json, re, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["history_vietnam.json", "history_world.json", "general.json"]

def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).lower().strip()
    return re.sub(r"\s+", " ", s)

errors = []
seen_ids = set()
seen_q = set()

for fn in FILES:
    path = ROOT / fn
    if not path.exists():
        errors.append(f"Missing {fn}")
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        errors.append(f"{fn}: root must be array")
        continue
    for i, q in enumerate(data):
        qid = q.get("id")
        if not qid or qid in seen_ids:
            errors.append(f"{fn}[{i}]: missing/duplicate id")
        seen_ids.add(qid)
        question = norm(q.get("question",""))
        if not question or question in seen_q:
            errors.append(f"{fn}[{i}]: missing/duplicate question")
        seen_q.add(question)
        answers = q.get("answers")
        if not isinstance(answers, list) or len(answers) != 4:
            errors.append(f"{fn}[{i}]: answers must have 4 items")
        correct = q.get("correct")
        if not isinstance(correct, int) or correct not in range(4):
            errors.append(f"{fn}[{i}]: correct must be 0..3")

manifest = ROOT / "manifest.json"
if not manifest.exists():
    errors.append("Missing manifest.json")
else:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(m.get("data_version"), int):
        errors.append("manifest data_version must be int")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("Question data validation passed.")
