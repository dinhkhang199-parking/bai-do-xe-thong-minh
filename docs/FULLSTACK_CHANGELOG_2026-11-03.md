# Cập nhật full stack — 03/11/2026

## Xe ra và API tìm vé

Trang Xe ra lấy tối đa 50 vé mỗi trang, chỉ lấy `IN_PARKING`. Tìm kiếm chạy ở máy chủ; biển OCR được tra khớp chính xác sau khi bỏ dấu phân cách, vẫn phân biệt chữ và số (B/8). Nhiều vé khớp vẫn cần chọn thủ công. Nút Làm mới vé giữ ảnh, biển nhập tay và kết quả quét. Tìm kiếm mới hủy phản hồi cũ; xác nhận tạm chặn khi đang tìm vé.

`GET /tickets/active` mặc định `limit=50`, hỗ trợ `offset`, `q` (biển/mã vé), `plate` (khớp biển chính xác), `status=IN_PARKING|NEEDS_REVIEW`. Trả `items`, `count`, `total`, `limit`, `offset`. Client cần lấy các trang tiếp theo khi `offset+count<total`; không giả định phản hồi mặc định chứa toàn bộ bãi. Vé cần kiểm tra vẫn có qua API nếu không lọc trạng thái, nhưng không được checkout trực tiếp.

Lịch sử và vé trong bãi được sắp theo thời điểm thực, kể cả dữ liệu cũ trộn UTC, offset và giờ địa phương. Giờ gửi xe không có múi giờ được hiểu là UTC+7. Giao diện hiển thị giờ gửi xe tại Việt Nam, độc lập múi giờ máy người dùng.

## Phiên và lỗi

Đăng nhập lại cùng tài khoản giữ bản nháp. Đăng nhập bằng tài khoản khác xóa ảnh, token quét và lựa chọn của người trước. Phản hồi thành công từ token cũ không được dùng sau khi đổi phiên.

Hộp đăng nhập lại có nút **Đổi tài khoản, xóa bản nháp** để thoát khi tài khoản cũ đã bị khóa hoặc không còn dùng được. Đổi tài khoản/đăng xuất chờ thao tác ghi lượt xe đang chạy kết thúc, tránh mất dấu kết quả.

Lỗi bất ngờ của API trả HTTP 500 với JSON, mã `INTERNAL_ERROR` và `X-Request-ID`; chi tiết lỗi chỉ ở log máy chủ. Giao diện hiển thị mã tra cứu. Các thao tác ghi có phản hồi mất/hỏng không tự lặp; giao diện hướng dẫn kiểm tra trạng thái trước khi gửi lại.

## Sao lưu

`scripts/backup_runtime.py` dùng SQLite online backup để lấy ảnh chụp CSDL bao gồm dữ liệu WAL đã commit. Kiểm tra toàn vẹn bản chụp, đóng gói ở vị trí tạm rồi thay file đích sau khi hoàn tất; thất bại không ghi đè bản cũ. Không đặt file sao lưu trong thư mục uploads.

Sao lưu khi đang chạy không phải ảnh chụp nguyên tử của cả CSDL và toàn bộ thư mục ảnh. Ảnh bằng chứng phải giữ bất biến trong lúc sao lưu; không chạy tác vụ xóa ảnh song song. Dừng dịch vụ trước khi khôi phục. Bản backup chứa dữ liệu vận hành, cần giữ ở vị trí có quyền truy cập phù hợp.

## Kiểm thử

Chạy `python scripts/run_checks.py --output-dir <thư-mục-kết-quả>` trên môi trường riêng. Kiểm thử bao phủ WAL, lỗi ghi backup, tìm vé ngoài trang đầu, B/8, phản hồi đến muộn, giữ ảnh khi làm mới, đổi tài khoản, phân quyền, lifecycle, OCR và thanh toán. Các ca camera/cổng thật, mưa, đèn pha và xe bám đuôi cần kiểm chứng ngoài bãi.
