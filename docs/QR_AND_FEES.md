# Vé QR và phí gửi xe

Vé mới có mã QR ngẫu nhiên, không chứa biển số hoặc thông tin đăng nhập.
QR dùng để tìm vé; không tự xác nhận xe ra, thu tiền hay mở barrier.
Mọi API xem vé và tra QR vẫn cần tài khoản đã đăng nhập.

## Sử dụng

1. Xe vào: chọn loại xe, ảnh và xác nhận biển số, tạo vé. Bấm **Xem / in vé QR** để in hoặc tải mã.
2. Xe ra: quét camera, chọn ảnh QR hoặc dán mã từ đầu đọc USB. Kiểm tra vé được chọn, đối chiếu ảnh xe ra rồi xác nhận.
3. Mở **Thanh toán**, chọn vé chưa thu và tạo QR MB. Máy chủ tự đối soát, ghi phiếu thu khi tiền vào khớp. Tiền mặt hoặc phương thức thủ công vẫn cần nhân viên ghi nhận.
4. Vé đã trả có nút **Xem phiếu thu**. Vẫn có thể mở vé bằng mã vé trong Nhật ký hoặc nút **Xem vé / thu phí** sau khi xe ra.
5. Nếu chưa thấy vé có thể thu tiền, xem thông báo cấu hình trên trang Thanh toán. Biểu phí cần được kích hoạt trước lúc tạo vé; vé cũ không có biểu phí không được tự áp giá hồi tố. Tích hợp MB cần kích hoạt riêng nếu muốn đối soát chuyển khoản.

## Biểu phí

Quản trị viên mở mục **Biểu phí**. Hai loại xe là xe máy và ô tô.
Mức ban đầu chỉ là mẫu, **đang tắt**, cần chỉnh và kích hoạt trước khi áp dụng.
Giá theo lượt hoặc theo thời gian; có thời gian miễn phí và trần mỗi 24 giờ.

- Thời gian được làm tròn lên đến phút, sau đó làm tròn lên theo khoảng tính phí.
- Gửi không quá thời gian miễn phí thì phí bằng 0.
- Khi vượt thời gian miễn phí, tính từ lúc xe vào, không trừ số phút miễn phí.
- Trần phí tính theo từng 24 giờ liên tục từ giờ vào, không theo mốc 0 giờ.
- Trần 0 nghĩa là không giới hạn; giá theo lượt là một mức cho cả lượt gửi.
- Giờ không có múi giờ được hiểu theo UTC+7, tương thích dữ liệu cũ.
- Mỗi vé mới lưu một bản biểu phí tại lúc vào. Đổi giá không sửa phí của vé đang gửi.
- Vé cũ và vé tạo khi biểu phí đang tắt không bị tự áp giá hồi tố.

Chỉ vé COMPLETED có biểu phí đã lưu mới được ghi nhận thu tiền.
Vé IN_PARKING, NEEDS_REVIEW hoặc CANCELLED không được thu qua API này.
Mỗi vé chỉ có một phiếu thu; các lần gửi trùng trả lại phiếu đã lưu.
Máy chủ tự tính và so sánh lại số tiền, không tin số tiền do trình duyệt gửi.
Phiếu thu, sự kiện và nhật ký quản trị được ghi trong cùng giao dịch SQLite.

Chuyển khoản là xác nhận thủ công của nhân viên, không phải kết nối ngân hàng
hoặc cổng thanh toán. Tính năng này không tự chuyển tiền.

## Dữ liệu và phụ thuộc

Schema 4 bổ sung parking_tariffs, ticket_billing, parking_payments; giữ các bảng vé, tài khoản và ảnh cũ.
qrcode 8.2 tạo ảnh QR tại máy chủ. jsQR 1.4.0 được lưu trong frontend/web/vendor,
kèm giấy phép MIT; không gọi dịch vụ QR bên ngoài.

Camera trình duyệt cần HTTPS hoặc localhost và quyền camera. Khi thiếu webcam
có thể chọn ảnh QR hoặc dán nội dung QR; quét ảnh không gửi ảnh QR ra ngoài.
Đóng hoặc chuyển mục sẽ dừng camera. Camera thật chưa được kiểm thử khi không có thiết bị.
