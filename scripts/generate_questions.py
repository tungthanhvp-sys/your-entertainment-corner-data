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
GENERAL_FILE = ROOT / "general.json"
KEYWORD_FILE = ROOT / "keyword_round.json"
MANIFEST = ROOT / "manifest.json"

ALLOWED_ROUNDS = {"khoi_dong", "tang_toc", "chinh_phuc"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
DEFAULT_MODELS = ["gemini-3.1-flash-lite", "gemini-3.7-flash"]
GENERAL_CATEGORIES = {
    "dia_ly", "khoa_hoc", "cong_nghe", "toan_hoc", "thien_van",
    "van_hoc", "van_hoc_viet_nam", "nghe_thuat", "am_nhac",
    "the_thao", "moi_truong", "sinh_hoc", "van_hoa_viet_nam"
}


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or "")).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^\w\sÀ-ỹ]", "", text)


def similarity(a, b):
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Gemini did not return JSON")
        return json.loads(text[start:end + 1])


def next_numeric_id(items, prefix):
    nums = []
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for item in items:
        match = pat.match(str(item.get("id", "")))
        if match:
            nums.append(int(match.group(1)))
    return max(nums, default=0) + 1


def validate_question(q):
    if not isinstance(q, dict):
        return False
    if q.get("target") not in {"history_vietnam", "general"}:
        return False
    if q.get("round") not in ALLOWED_ROUNDS:
        return False
    if q.get("difficulty") not in ALLOWED_DIFFICULTIES:
        return False
    if q.get("target") == "general" and q.get("category") not in GENERAL_CATEGORIES:
        return False
    if not isinstance(q.get("question"), str) or len(q["question"].strip()) < 12:
        return False
    answers = q.get("answers")
    if not isinstance(answers, list) or len(answers) != 4:
        return False
    if len({normalize(x) for x in answers}) != 4:
        return False
    if not isinstance(q.get("correct"), int) or q["correct"] not in range(4):
        return False
    if not isinstance(q.get("explanation"), str) or len(q["explanation"].strip()) < 20:
        return False
    return True


def validate_keyword(k):
    if not isinstance(k, dict):
        return False
    if not isinstance(k.get("answer"), str) or len(k["answer"].strip()) < 2:
        return False
    clues = k.get("clues")
    if not isinstance(clues, list) or len(clues) < 4:
        return False
    if not all(isinstance(x, str) and len(x.strip()) >= 12 for x in clues):
        return False
    if k.get("difficulty") not in ALLOWED_DIFFICULTIES:
        return False
    if not isinstance(k.get("explanation"), str) or len(k["explanation"].strip()) < 20:
        return False
    return True


def shuffle_answers(q):
    pairs = list(enumerate(q["answers"]))
    random.shuffle(pairs)
    old_correct = q["correct"]
    q["answers"] = [value for _, value in pairs]
    q["correct"] = next(
        i for i, (old_i, _) in enumerate(pairs) if old_i == old_correct
    )
    return q


def build_prompt(count, old_questions, old_keywords):
    oldq = "\n".join("- " + q for q in old_questions[-120:])
    oldk = "\n".join("- " + q for q in old_keywords[-40:])
    return f"""
Bạn biên tập ngân hàng câu hỏi cho game kiến thức tiếng Việt, tối ưu cho TalkBack.
Tạo {count} câu hỏi trắc nghiệm mới VÀ 2 chướng ngại vật Giải mã mới.

MỤC TIÊU CÂU HỎI:
- Khoảng 40% câu thuộc Lịch sử Việt Nam, target=history_vietnam, category=lich_su_viet_nam.
- Khoảng 60% thuộc nhiều lĩnh vực khác, target=general. Hãy phân tán qua địa lý, khoa học, công nghệ, toán, thiên văn, văn học, nghệ thuật, âm nhạc, thể thao, môi trường, sinh học, văn hóa Việt Nam.
- Ưu tiên medium và hard: khoảng 15% easy, 55% medium, 30% hard.
- Khởi động không được toàn câu quá dễ; Tăng tốc và Chinh phục ưu tiên medium/hard.
- Chỉ dùng dữ kiện ổn định, phổ biến, có một đáp án rõ ràng. Không dùng câu gây tranh cãi hoặc dữ kiện bạn không chắc.
- Không gần trùng danh sách câu cũ.
- Mỗi câu đúng 4 đáp án và 1 đáp án đúng.
- Explanation ngắn, rõ, dễ nghe bằng TalkBack.

MỤC TIÊU CHƯỚNG NGẠI VẬT:
- Đa lĩnh vực, không chỉ lịch sử.
- Có ít nhất 4 gợi ý từ khó đến dễ.
- answer ngắn gọn; không đưa đáp án trực tiếp trong gợi ý sớm.
- letter_count là số chữ cái của answer, không tính khoảng trắng hoặc dấu câu; chữ có dấu vẫn tính là 1 chữ.
- difficulty ưu tiên medium hoặc hard.

Chỉ trả JSON hợp lệ theo schema:
{{
  "questions": [
    {{
      "target": "general",
      "category": "khoa_hoc",
      "round": "tang_toc",
      "difficulty": "hard",
      "question": "...",
      "answers": ["...", "...", "...", "..."],
      "correct": 0,
      "explanation": "..."
    }}
  ],
  "keyword_puzzles": [
    {{
      "category": "khoa_hoc",
      "answer": "...",
      "letter_count": 8,
      "difficulty": "medium",
      "clues": ["...", "...", "...", "..."],
      "explanation": "..."
    }}
  ]
}}

CÂU ĐÃ CÓ:
{oldq}

CHƯỚNG NGẠI VẬT ĐÃ CÓ:
{oldk}
""".strip()


def call_model(client, model, prompt_text):
    response = client.models.generate_content(
        model=model,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.15,
            max_output_tokens=10000,
        ),
    )
    return extract_json(response.text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()
    count = max(8, min(args.count, 20))

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY", file=sys.stderr)
        return 2

    for path in [VN_FILE, GENERAL_FILE, KEYWORD_FILE, MANIFEST]:
        if not path.exists():
            print(f"Missing {path.name}", file=sys.stderr)
            return 2

    vn = load_json(VN_FILE)
    general = load_json(GENERAL_FILE)
    keywords = load_json(KEYWORD_FILE)
    old_questions = [
        str(x.get("question", "")).strip()
        for x in vn + general
        if x.get("question")
    ]
    old_keywords = [
        str(x.get("answer", "")).strip()
        for x in keywords
        if x.get("answer")
    ]

    client = genai.Client(api_key=api_key)
    custom_model = os.getenv("GEMINI_MODEL", "").strip()
    models = [custom_model] if custom_model else DEFAULT_MODELS
    payload = None
    last_error = None

    for index, model in enumerate(models):
        try:
            payload = call_model(
                client,
                model,
                build_prompt(count, old_questions, old_keywords),
            )
            break
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            print(f"{model} failed: {exc}", file=sys.stderr)
            rate_limited = any(
                token in message
                for token in ["429", "resource_exhausted", "too_many_requests", "rate limit"]
            )
            if rate_limited and index < len(models) - 1:
                time.sleep(15)
                continue
            break

    if payload is None:
        print(f"Generation failed: {last_error}", file=sys.stderr)
        return 1

    accepted = []
    for q in payload.get("questions", []):
        if not validate_question(q):
            continue
        text = q["question"].strip()
        if any(similarity(text, old) >= 0.84 for old in old_questions):
            continue
        if any(similarity(text, x["question"]) >= 0.84 for x in accepted):
            continue
        accepted.append(shuffle_answers(q))
        if len(accepted) >= count:
            break

    accepted_keywords = []
    for k in payload.get("keyword_puzzles", []):
        if not validate_keyword(k):
            continue
        if any(similarity(k["answer"], old) >= 0.82 for old in old_keywords):
            continue
        k["letter_count"] = sum(1 for ch in k["answer"] if ch.isalpha())
        accepted_keywords.append(k)
        if len(accepted_keywords) >= 2:
            break

    if not accepted and not accepted_keywords:
        print("No valid new data; unchanged")
        return 0

    vn_id = next_numeric_id(vn, "vn_hist_")
    general_id = next_numeric_id(general, "general_")
    keyword_id = next_numeric_id(keywords, "keyword_")

    for q in accepted:
        item = {
            "category": "lich_su_viet_nam" if q["target"] == "history_vietnam" else q["category"],
            "round": q["round"],
            "difficulty": q["difficulty"],
            "question": q["question"].strip(),
            "answers": [str(x).strip() for x in q["answers"]],
            "correct": q["correct"],
            "explanation": q["explanation"].strip(),
            "generated_at": date.today().isoformat(),
            "generation_mode": "gemini_no_web_grounding",
        }
        if q["target"] == "history_vietnam":
            item["id"] = f"vn_hist_{vn_id:04d}"
            vn_id += 1
            vn.append(item)
        else:
            item["id"] = f"general_{general_id:04d}"
            general_id += 1
            general.append(item)

    for k in accepted_keywords:
        keywords.append({
            "id": f"keyword_{keyword_id:04d}",
            "category": k.get("category", "tong_hop"),
            "answer": k["answer"].strip(),
            "letter_count": k["letter_count"],
            "difficulty": k["difficulty"],
            "clues": [str(x).strip() for x in k["clues"]],
            "explanation": k["explanation"].strip(),
            "generated_at": date.today().isoformat(),
            "generation_mode": "gemini_no_web_grounding",
        })
        keyword_id += 1

    save_json(VN_FILE, vn)
    save_json(GENERAL_FILE, general)
    save_json(KEYWORD_FILE, keywords)

    manifest = load_json(MANIFEST)
    manifest["data_version"] = int(manifest.get("data_version", 0)) + 1
    manifest["updated_at"] = date.today().isoformat()

    changed = set()
    if any(q["target"] == "history_vietnam" for q in accepted):
        changed.add("history_vietnam")
    if any(q["target"] == "general" for q in accepted):
        changed.add("general")
    if accepted_keywords:
        changed.add("keyword_round")

    for pack in manifest.get("packs", []):
        if pack.get("id") in changed:
            pack["version"] = int(pack.get("version", 0)) + 1

    save_json(MANIFEST, manifest)
    print(f"Added {len(accepted)} questions and {len(accepted_keywords)} keyword puzzles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
