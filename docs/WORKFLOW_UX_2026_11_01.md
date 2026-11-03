# Tối ưu thao tác ITS Parking — 01/11/2026

Đã cập nhật trực tiếp dự án và xác minh mã mới đang được phục vụ tại http://localhost:8000/.

## Thay đổi

- Xe ra: tìm vé bằng biển số/mã vé, bỏ qua dấu cách và dấu phân cách; vẫn cần chọn đúng vé.
- Giữ ảnh, biển số và vé đã chọn khi chuyển mục trong cùng tab. Bản nháp không lưu lâu dài; tải lại tab hoặc đăng xuất sẽ xóa.
- Đổi ảnh bằng một nút; xóa biển số sửa tay cũ khi thay bằng ảnh khác.
- Quét ảnh có nút “Dùng biển số đã đối chiếu”; không tự áp dụng hoặc tự ghi nhận lượt xe.
- Ctrl+Enter gửi biểu mẫu đang thao tác. Enter thông thường không gửi nhầm.
- Thông báo lỗi hiện cạnh nút gửi. Ngăn gửi lặp và chuyển mục khi đang ghi nhận; ngừng chờ sau 90 giây, nhắc kiểm tra Nhật ký trước khi gửi lại vì máy chủ có thể đã nhận lượt xe.
- Xe ra lệch biển có thông báo chưa duyệt và nút mở phần kiểm tra.
- Nhật ký: giữ bộ lọc khi chuyển mục, gom lần gõ liên tiếp trong 250 ms, Enter tìm ngay, xóa bộ lọc một lần bấm.
- Nhật ký tải 50 vé mỗi trang; bảng cuộn riêng với tiêu đề cố định, thay cho 500 dòng kéo dài.
- Đăng nhập có trạng thái đang xử lý và ngăn bấm gửi trùng.

## Xác minh

78 kiểm thử giao diện đạt, 0 lỗi, 0 bỏ qua. Bổ sung 14 ca cho các hành vi mới.
Thử bằng tài khoản, ảnh và vé giả trên bản sao cổng 8002, AI thật đã tắt.
Đã kiểm tra hai giao diện, màn hình 390 × 844, giữ bản nháp, tìm vé cũ và vé ra lệch biển.
Không có lỗi console trong phiên kiểm tra.

Lượt sửa này không thay đổi backend, cấu hình đăng nhập hoặc dữ liệu vận hành.
Camera/IP/RTSP và phần cứng không nằm trong phạm vi xác minh này.

Xem frontend-output.txt, verification.json và các ảnh trong cùng thư mục để đối chiếu.
