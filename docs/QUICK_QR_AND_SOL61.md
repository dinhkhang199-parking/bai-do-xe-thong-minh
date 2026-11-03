# QR thanh toán nhanh và phân tích biển số GPT 6.1 Sol

## Tạo QR ngay trên trang Thanh toán

Nút **Tạo QR thanh toán** ở đầu trang mở ô nhập số tiền cần nhận.
Hệ thống dùng tài khoản MB mặc định đã được lưu, tạo QR cục bộ và cho tải PNG.
Từ phiên bản schema 6, QR nhập tiền dùng tiền tố PAY và được lưu thành yêu cầu.

QR nhập tiền được máy chủ tự theo dõi, không cần bấm xác nhận đã chuyển.
Khi giao dịch MB khớp, trạng thái và phiếu thu được lưu tự động kể cả khi đóng
cửa sổ QR. Mã QR thủ công cũ có tiền tố QR không có yêu cầu lưu kèm nên cần
tạo mã mới để dùng tự đối soát.
Để thu và đối soát theo vé, chọn vé đã duyệt ra có biểu phí, chọn Chuyển khoản MB
và tạo mã của vé như luồng hiện có. Biểu phí/MB cần được kích hoạt riêng.

API mới POST /payments/qr-requests nhận amount và idempotency_key, yêu cầu
admin/operator. Đầu ra dùng tài khoản MB mặc định đã xác minh và kích hoạt.
Tiền là số nguyên từ 1 đến 1 tỷ đồng. API qr-preview cũ chỉ giữ để tương thích,
không phải luồng tự động. Xem AUTO_MB_AND_FAST_GATE.md.

## Model và ảnh khó

Đã xác minh danh sách 9Router có cx/gpt-6.1-sol. Cấu hình dùng đúng alias này,
Responses API, reasoning effort high, chi tiết ảnh high, timeout 60 giây.
Mỗi ảnh chỉ có một lượt gọi model, không tự lặp retry trả phí.

Pipeline gửi ảnh gốc và tối đa hai ảnh cắt đối chiếu nếu detector ONNX có sẵn
xác định được đúng một vùng biển số: ảnh phóng to gốc và bản tăng tương phản nhẹ.
Detector không tự tải trọng số; thiếu detector thì vẫn phân tích ảnh gốc.
Không ép chọn crop khi có nhiều biển số hoặc vùng quá nhỏ.

Prompt yêu cầu đọc từng dòng, giữ chữ/số thực sự nhìn thấy, lưu ý B/8, O/0,
I/1 và không tự thêm số để khớp mẫu. Trường hợp không chắc phải báo ký tự còn
nghi ngờ; dữ liệu vẫn yêu cầu đối chiếu ảnh, không có điểm tin cậy giả.
Giao diện hiển thị lỗi ảnh, ký tự nghi ngờ và ghi chú phân tích.

## Xác minh

Hai ảnh giả lập (rõ, xoay nhẹ/hơi mờ) được đọc đúng toàn chuỗi.
Sau khi người dùng đồng ý gửi đúng hai ảnh cắt, hai mẫu lóa/mờ và nghiêng
được đọc đúng toàn chuỗi; mỗi yêu cầu dùng ba góc nhìn.
Đây là kết quả của bốn mẫu thử, không phải bảo đảm đọc đúng mọi ảnh ngoài đời.
Không gửi ảnh toàn cảnh thật trong lượt kiểm tra đã được phê duyệt.

Tài liệu tham khảo chính thức:

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/guides/images-vision
