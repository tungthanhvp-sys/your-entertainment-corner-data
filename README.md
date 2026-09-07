# Your Entertainment Corner Data

Kho dữ liệu câu hỏi cho ứng dụng **Your Entertainment Corner**.

## Mục tiêu
- Ưu tiên câu hỏi Lịch sử Việt Nam.
- Cho phép ứng dụng tải bộ câu hỏi mới mà không cần phát hành APK mới.
- Vẫn có dữ liệu cục bộ để chơi khi mất mạng.
- Hỗ trợ các vòng chơi theo phong cách gameshow kiến thức: Khởi động, Giải mã, Tăng tốc, Chinh phục.

## Các tệp
- `manifest.json`: phiên bản và danh sách gói dữ liệu.
- `history_vietnam.json`: câu hỏi Lịch sử Việt Nam.
- `history_world.json`: câu hỏi Lịch sử thế giới.
- `general.json`: kiến thức tổng hợp.
- `keyword_round.json`: dữ liệu vòng Giải mã/từ khóa.

## Quy tắc cập nhật
Khi sửa hoặc thêm câu hỏi:
1. Tăng `data_version` trong `manifest.json`.
2. Nếu sửa riêng một gói, tăng `version` của gói đó.
3. Không đổi `id` của câu hỏi cũ nếu chỉ sửa câu chữ.
4. Mỗi câu hỏi cần có câu trả lời, đáp án đúng và giải thích ngắn.
5. Tránh câu hỏi mơ hồ hoặc phụ thuộc tin tức quá thời điểm.

## Gợi ý tỉ lệ nội dung
- 65% Lịch sử Việt Nam
- 15% Lịch sử thế giới
- 20% kiến thức khác


## Tự động cập nhật câu hỏi bằng Gemini

Kho này có workflow `.github/workflows/update_questions.yml`.

- Chạy tự động mỗi thứ Hai lúc khoảng 09:17 giờ Việt Nam.
- Mặc định tạo tối đa 12 câu Lịch sử Việt Nam mới mỗi tuần.
- Gemini được phép dùng Google Search để kiểm chứng trước khi trả câu hỏi.
- Script loại câu sai định dạng, thiếu nguồn và câu gần trùng.
- Chỉ khi có câu mới hợp lệ, `history_vietnam.json` và `manifest.json` mới được cập nhật.
- Có thể chạy thủ công từ tab Actions.

### Secret bắt buộc

Tạo Repository secret tên chính xác:

`GEMINI_API_KEY`

Không ghi API key vào file JSON, README, mã nguồn hay commit công khai.
