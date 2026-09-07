#!/usr/bin/env python3
import argparse, difflib, json, os, random, re, sys, unicodedata
from datetime import date
from pathlib import Path
from google import genai

ROOT = Path(__file__).resolve().parents[1]
VN_FILE = ROOT / "history_vietnam.json"
KW_FILE = ROOT / "keyword_round.json"
MANIFEST = ROOT / "manifest.json"

ALLOWED_ROUNDS = {"khoi_dong", "tang_toc", "chinh_phuc"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"[^\w\sÀ-ỹ]", "", s)

def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def extract_json(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Gemini did not return a JSON object.")
    return json.loads(text[start:end+1])

def next_id(existing, prefix):
    nums = []
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for item in existing:
        m = pat.match(str(item.get("id","")))
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1

def validate_question(q):
    if not isinstance(q, dict): return False
    if not isinstance(q.get("question"), str) or len(q["question"].strip()) < 12: return False
    ans = q.get("answers")
    if not isinstance(ans, list) or len(ans) != 4: return False
    if len({normalize(x) for x in ans}) != 4: return False
    if q.get("round") not in ALLOWED_ROUNDS: return False
    if q.get("difficulty") not in ALLOWED_DIFFICULTIES: return False
    correct = q.get("correct")
    if not isinstance(correct, int) or not 0 <= correct <= 3: return False
    if not isinstance(q.get("explanation"), str) or len(q["explanation"].strip()) < 20: return False
    sources = q.get("sources")
    if not isinstance(sources, list) or not sources: return False
    if not all(isinstance(u, str) and u.startswith(("https://","http://")) for u in sources): return False
    return True

def shuffle_answers(q):
    pairs = list(enumerate(q["answers"]))
    random.shuffle(pairs)
    old_correct = q["correct"]
    q["answers"] = [v for _, v in pairs]
    q["correct"] = next(i for i, (old_i, _) in enumerate(pairs) if old_i == old_correct)
    return q

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12)
    args = ap.parse_args()
    count = max(4, min(args.count, 30))

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY GitHub secret.", file=sys.stderr)
        return 2

    existing = json.loads(VN_FILE.read_text(encoding="utf-8"))
    existing_questions = [x.get("question","") for x in existing]
    existing_preview = "\n".join(f"- {q}" for q in existing_questions[-120:])

    prompt = f"""
Bạn là biên tập viên ngân hàng câu hỏi lịch sử cho một trò chơi kiến thức tiếng Việt.
Hãy tạo {count} câu hỏi MỚI, ưu tiên LỊCH SỬ VIỆT NAM, có thể dùng Google Search để kiểm chứng.

Yêu cầu bắt buộc:
- 100% câu hỏi thuộc lịch sử Việt Nam.
- Không trùng hoặc gần giống các câu đã có bên dưới.
- Mỗi câu có đúng 4 đáp án, chỉ 1 đáp án đúng.
- Tránh câu mơ hồ, gây tranh cãi, hoặc phụ thuộc cách diễn giải.
- Ưu tiên mốc sự kiện, nhân vật, địa danh, triều đại, văn hóa - lịch sử, kháng chiến, cải cách, ngoại giao.
- Phân bố khoảng: 35% dễ, 45% trung bình, 20% khó.
- Phân bố vòng: khoi_dong, tang_toc, chinh_phuc.
- explanation ngắn, rõ, dễ nghe bằng trình đọc màn hình.
- Mỗi câu bắt buộc có ít nhất 1 URL nguồn kiểm chứng đáng tin cậy.
- Không dùng Wikipedia làm nguồn duy nhất khi có thể dùng nguồn giáo dục, bảo tàng, cơ quan nhà nước, sách/ấn phẩm học thuật hoặc nguồn lịch sử có uy tín.
- Trả về CHỈ JSON hợp lệ, không markdown, không giải thích ngoài JSON.

Schema:
{{
  "questions": [
    {{
      "round": "khoi_dong|tang_toc|chinh_phuc",
      "difficulty": "easy|medium|hard",
      "question": "...",
      "answers": ["A","B","C","D"],
      "correct": 0,
      "explanation": "...",
      "sources": ["https://..."]
    }}
  ]
}}

Các câu đã có:
{existing_preview}
"""

    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        input=prompt,
        tools=[{"type": "google_search"}],
    )
    payload = extract_json(interaction.output_text)
    candidates = payload.get("questions", [])

    accepted = []
    for q in candidates:
        if not validate_question(q):
            continue
        if any(similar(q["question"], old) >= 0.84 for old in existing_questions):
            continue
        if any(similar(q["question"], x["question"]) >= 0.84 for x in accepted):
            continue
        q = shuffle_answers(q)
        q["category"] = "lich_su_viet_nam"
        accepted.append(q)
        if len(accepted) >= count:
            break

    if not accepted:
        print("No valid new questions generated; repository left unchanged.")
        return 0

    n = next_id(existing, "vn_hist_")
    for q in accepted:
        q["id"] = f"vn_hist_{n:04d}"
        n += 1
        existing.append({
            "id": q["id"],
            "category": q["category"],
            "round": q["round"],
            "difficulty": q["difficulty"],
            "question": q["question"].strip(),
            "answers": [str(x).strip() for x in q["answers"]],
            "correct": q["correct"],
            "explanation": q["explanation"].strip(),
            "sources": q["sources"],
            "generated_at": date.today().isoformat(),
        })

    VN_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["data_version"] = int(manifest.get("data_version", 0)) + 1
    manifest["updated_at"] = date.today().isoformat()
    for pack in manifest.get("packs", []):
        if pack.get("id") == "history_vietnam":
            pack["version"] = int(pack.get("version", 0)) + 1
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Added {len(accepted)} verified-format history questions.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
