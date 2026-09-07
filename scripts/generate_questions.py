#!/usr/bin/env python3
import argparse
import difflib
import json
import os
import random
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
VN_FILE = ROOT / "history_vietnam.json"
MANIFEST = ROOT / "manifest.json"

ALLOWED_ROUNDS = {"khoi_dong", "tang_toc", "chinh_phuc"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
DEFAULT_MODELS = ["gemini-3.1-flash-lite", "gemini-3.7-flash"]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^\w\sÀ-ỹ]", "", text)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_json(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Gemini did not return a JSON object.")
        return json.loads(text[start:end + 1])


def next_id(existing):
    nums = []
    pat = re.compile(r"^vn_hist_(\d+)$")
    for item in existing:
        m = pat.match(str(item.get("id", "")))
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def validate_question(q):
    if not isinstance(q, dict):
        return False
    question = q.get("question")
    answers = q.get("answers")
    correct = q.get("correct")
    explanation = q.get("explanation")
    if not isinstance(question, str) or len(question.strip()) < 12:
        return False
    if not isinstance(answers, list) or len(answers) != 4:
        return False
    if not all(isinstance(a, str) and a.strip() for a in answers):
        return False
    if len({normalize(a) for a in answers}) != 4:
        return False
    if not isinstance(correct, int) or correct not in range(4):
        return False
    if q.get("round") not in ALLOWED_ROUNDS:
        return False
    if q.get("difficulty") not in ALLOWED_DIFFICULTIES:
        return False
    if not isinstance(explanation, str) or len(explanation.strip()) < 20:
        return False
    return True


def shuffle_answers(q):
    indexed = list(enumerate(q["answers"]))
    random.shuffle(indexed)
    old_correct = q["correct"]
    q["answers"] = [answer for _, answer in indexed]
    q["correct"] = next(i for i, (old_i, _) in enumerate(indexed) if old_i == old_correct)
    return q


def build_prompt(count, existing_questions):
    existing_preview = "\n".join(f"- {q}" for q in existing_questions[-80:])
    return f"""
Bạn là biên tập viên ngân hàng câu hỏi cho một trò chơi kiến thức tiếng Việt.
Hãy tạo {count} câu hỏi MỚI về LỊCH SỬ VIỆT NAM.

QUY TẮC BẮT BUỘC:
- Chỉ dùng các sự kiện, nhân vật, địa danh, triều đại và mốc lịch sử phổ biến, ổn định, được công nhận rộng rãi.
- Nếu không chắc chắn về một dữ kiện thì KHÔNG dùng dữ kiện đó.
- Tránh câu hỏi còn tranh luận, số liệu ước đoán, chi tiết quá nhỏ hoặc câu có nhiều đáp án có thể đúng.
- Không tạo câu gần giống các câu đã có ở cuối lời nhắc này.
- Mỗi câu có đúng 4 phương án và chỉ 1 đáp án đúng.
- Giải thích ngắn, rõ ràng, phù hợp để đọc bằng TalkBack.
- Phân bố tương đối: 35% easy, 45% medium, 20% hard.
- Dùng các vòng: khoi_dong, tang_toc, chinh_phuc.
- Không cần URL nguồn vì lần chạy này KHÔNG sử dụng Google Search.
- Chỉ trả về JSON hợp lệ, không Markdown, không văn bản ngoài JSON.

Định dạng:
{{
  "questions": [
    {{
      "round": "khoi_dong",
      "difficulty": "easy",
      "question": "...",
      "answers": ["...", "...", "...", "..."],
      "correct": 0,
      "explanation": "..."
    }}
  ]
}}

CÁC CÂU ĐÃ CÓ, KHÔNG ĐƯỢC LẶP LẠI:
{existing_preview}
""".strip()


def generate_with_model(client, model, prompt):
    print(f"Trying model: {model}")
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.15,
            max_output_tokens=8192,
        ),
    )
    return extract_json(response.text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()
    count = max(4, min(args.count, 20))

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY GitHub secret.", file=sys.stderr)
        return 2

    if not VN_FILE.exists() or not MANIFEST.exists():
        print("Missing history_vietnam.json or manifest.json in repository root.", file=sys.stderr)
        return 2

    existing = load_json(VN_FILE)
    existing_questions = [str(x.get("question", "")).strip() for x in existing if x.get("question")]
    prompt = build_prompt(count, existing_questions)
    client = genai.Client(api_key=api_key)

    custom_model = os.getenv("GEMINI_MODEL", "").strip()
    models = [custom_model] if custom_model else DEFAULT_MODELS
    payload = None
    last_error = None

    for idx, model in enumerate(models):
        try:
            payload = generate_with_model(client, model, prompt)
            print(f"Generation succeeded with {model}.")
            break
        except Exception as exc:
            last_error = exc
            msg = str(exc)
            print(f"Model {model} failed: {msg}", file=sys.stderr)
            rate_limited = any(s in msg.lower() for s in ["429", "resource_exhausted", "too_many_requests", "rate limit"])
            if rate_limited and idx < len(models) - 1:
                print("Waiting 15 seconds before trying fallback model...")
                time.sleep(15)
                continue
            break

    if payload is None:
        print("Gemini generation failed. Repository was left unchanged.", file=sys.stderr)
        if last_error:
            print(f"Last error: {last_error}", file=sys.stderr)
        return 1

    candidates = payload.get("questions", [])
    if not isinstance(candidates, list):
        print("Gemini JSON did not contain a questions array.", file=sys.stderr)
        return 1

    accepted = []
    for q in candidates:
        if not validate_question(q):
            continue
        qt = q["question"].strip()
        if any(similarity(qt, old) >= 0.84 for old in existing_questions):
            continue
        if any(similarity(qt, aq["question"]) >= 0.84 for aq in accepted):
            continue
        q = shuffle_answers(q)
        q["category"] = "lich_su_viet_nam"
        accepted.append(q)
        if len(accepted) >= count:
            break

    if not accepted:
        print("No valid non-duplicate questions were produced; repository left unchanged.")
        return 0

    nid = next_id(existing)
    for q in accepted:
        existing.append({
            "id": f"vn_hist_{nid:04d}",
            "category": "lich_su_viet_nam",
            "round": q["round"],
            "difficulty": q["difficulty"],
            "question": q["question"].strip(),
            "answers": [str(a).strip() for a in q["answers"]],
            "correct": q["correct"],
            "explanation": q["explanation"].strip(),
            "sources": [],
            "generated_at": date.today().isoformat(),
            "generation_mode": "gemini_no_web_grounding",
        })
        nid += 1

    save_json(VN_FILE, existing)

    manifest = load_json(MANIFEST)
    manifest["data_version"] = int(manifest.get("data_version", 0)) + 1
    manifest["updated_at"] = date.today().isoformat()
    for pack in manifest.get("packs", []):
        if pack.get("id") == "history_vietnam":
            pack["version"] = int(pack.get("version", 0)) + 1
    save_json(MANIFEST, manifest)

    print(f"Added {len(accepted)} new Vietnam-history questions.")
    print("Mode: Gemini text generation without Google Search grounding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
