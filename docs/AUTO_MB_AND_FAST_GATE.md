# MB tự động và luồng xe vào/ra gọn hơn

## Xe vào

Chọn/chụp ảnh → hệ thống tự đọc và điền biển số → kiểm tra ảnh, sửa nếu cần →
**Xác nhận xe vào**. Có thể dùng Ctrl+Enter để xác nhận.
Không cần bấm Quét rồi chép kết quả.

## Xe ra

Chọn/chụp ảnh → tự đọc biển số và chọn vé khi có đúng một vé khớp chính xác →
kiểm tra ảnh/vé → **Xác nhận xe ra**.
Hệ thống giữ nguyên vé được nhân viên chủ động chọn, kể cả khi AI gợi ý khác,
và hiển thị cảnh báo để tránh chọn nhầm xe. B/8, O/0 và I/1 không bị coi là giống nhau.

Tìm bằng mã vé hoặc QR nằm trong phần mở rộng khi cần.
Nếu AI không đọc chắc hoặc mạng lỗi, nhân viên nhập biển số sau khi đối chiếu
ảnh rồi xác nhận thủ công. Ảnh và thông tin vẫn được giữ khi chuyển mục.

Kết quả quét được lưu tạm tối đa 10 phút trong bộ nhớ máy chủ, ràng buộc với
người dùng và SHA-256 của chính ảnh đó. Xác nhận vé tái dùng kết quả này,
không gọi model lại. Token sai, ảnh đổi hoặc token hết hạn bị từ chối;
client có thể quét lại. Client nhập tay được ghi rõ nguồn manual.

## Thanh toán MB tự động

Mã QR theo vé và mã QR nhập số tiền mới đều có yêu cầu được lưu trên SQLite.
Máy chủ kiểm tra tiền vào định kỳ khoảng 15 giây, kể cả khi đóng popup hoặc
chuyển màn hình. Trình duyệt chỉ cập nhật trạng thái đã lưu.

Khách chuyển đúng tài khoản, tiền VND, số tiền và nội dung → hệ thống tự
ghi **Đã thanh toán**, mã giao dịch MB và phiếu thu. Không cần bấm
“Tôi đã chuyển tiền”. Nút xác nhận thủ công chỉ còn dành cho Tiền mặt hoặc
phương thức thủ công được nhân viên chủ động chọn.

QR nhập số tiền có lịch sử “QR nhập số tiền gần đây”, mở lại được để xem trạng
thái và in phiếu thu tự động. Các mã QR nhanh cũ chưa lưu yêu cầu từ phiên bản
trước không tự trở thành yêu cầu có thể đối soát; cần tạo mã mới.

Mỗi lần tạo QR dùng idempotency key để gửi lặp không tạo trùng yêu cầu.
Mã giao dịch ngân hàng chỉ được dùng một lần cho cả vé và QR nhập số tiền.
Phiếu thu, bằng chứng khớp và audit được ghi chung một transaction SQLite.
Sai số tiền, ghi nợ, thiếu tham chiếu hoặc nhiều giao dịch cùng khớp không
bị đánh dấu đã trả. Một lần xác nhận không tự chuyển tiền hoặc hoàn tiền.

MB phải đang đăng nhập và tài khoản nhận phải được xác minh/kích hoạt.
Khi hết phiên hoặc mất kết nối, hệ thống giữ yêu cầu chờ và báo cần kết nối
lại; không tự ghi đã trả. Giá gửi xe vẫn do quản trị viên cấu hình riêng,
không tự bật biểu phí mẫu hoặc áp giá cho vé cũ.

## Kiểm thử

Các test dùng ảnh, khóa, tài khoản và giao dịch giả.
Có kiểm tra cạnh tranh nhiều monitor, replay giao dịch, lưu yêu cầu qua các
đối tượng monitor mới, cache OCR đúng người/ảnh, token hết hạn và sửa tay
trong khi AI trả lời chậm. Không thực hiện chuyển khoản thật để kiểm thử.
