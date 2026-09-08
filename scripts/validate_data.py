#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []
seen_ids = set()
seen_questions = set()

for filename in ["history_vietnam.json", "history_world.json", "general.json"]:
    path = ROOT / filename
    if not path.exists():
        errors.append(f"Missing {filename}")
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        errors.append(f"{filename}: root must be array")
        continue
    for index, question in enumerate(data):
        qid = question.get("id")
        text = str(question.get("question", "")).strip().lower()
        if not qid or qid in seen_ids:
            errors.append(f"{filename}[{index}]: duplicate/missing id")
        seen_ids.add(qid)
        if not text or text in seen_questions:
            errors.append(f"{filename}[{index}]: duplicate/missing question")
        seen_questions.add(text)
        answers = question.get("answers")
        correct = question.get("correct")
        if not isinstance(answers, list) or len(answers) != 4:
            errors.append(f"{filename}[{index}]: answers must have 4 items")
        if not isinstance(correct, int) or correct not in range(4):
            errors.append(f"{filename}[{index}]: correct must be 0..3")

keyword_path = ROOT / "keyword_round.json"
if not keyword_path.exists():
    errors.append("Missing keyword_round.json")
else:
    keyword_data = json.loads(keyword_path.read_text(encoding="utf-8"))
    keyword_ids = set()
    for index, puzzle in enumerate(keyword_data):
        pid = puzzle.get("id")
        answer = str(puzzle.get("answer", "")).strip()
        clues = puzzle.get("clues")
        if not pid or pid in keyword_ids:
            errors.append(f"keyword[{index}]: duplicate/missing id")
        keyword_ids.add(pid)
        if not answer or not isinstance(clues, list) or len(clues) < 2:
            errors.append(f"keyword[{index}]: invalid puzzle")
        letter_count = puzzle.get(
            "letter_count",
            sum(1 for ch in answer if ch.isalpha()),
        )
        if not isinstance(letter_count, int) or letter_count < 1:
            errors.append(f"keyword[{index}]: invalid letter_count")

manifest_path = ROOT / "manifest.json"
if not manifest_path.exists():
    errors.append("Missing manifest.json")
else:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("data_version"), int):
        errors.append("manifest data_version must be int")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)

print("Question data validation passed")
