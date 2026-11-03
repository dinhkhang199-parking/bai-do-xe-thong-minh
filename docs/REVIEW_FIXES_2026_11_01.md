# Bản sửa sau kiểm tra ngày 01/11/2026

Đã sửa 9 vấn đề được ghi nhận ở lượt rà mã nguồn. Kiểm thử trên bản sao tạm, dữ liệu SQLite/ảnh/tài khoản giả, AI thật tắt: **288 ca backend và 64 ca frontend đạt; không fail, error hoặc skipped**. Mã ứng dụng và test giao cho người dùng trùng byte với bản sao đã kiểm thử. Đây là kết quả regression, không phải cam kết không còn lỗi trong mọi môi trường.

## Những thay đổi chính

| Vấn đề | Bản sửa |
|---|---|
| Nhầm chữ/số trong định danh biển | So vé chỉ bỏ dấu phân cách và chuẩn hóa chữ hoa; bước sửa ký tự OCR không được dùng như phép bằng nhau của biển đã xác nhận. Có ca hồi quy cho `30-AB 123.45` và `30-A8 123.45`. |
| Đường dẫn nguy hiểm trong ZIP | Kiểm tra mọi member, từ chối traversal, đường dẫn Windows/absolute, symlink, tên trùng hoa/thường và archive vượt giới hạn trước khi ghi dữ liệu. Backup mới tạo tên POSIX nhất quán. |
| Database hỏng ghi đè dữ liệu tốt | Dựng staging trên cùng filesystem, kiểm tra tính toàn vẹn SQLite, đóng kết nối rõ ràng trước rename, rollback khi cài đặt lỗi; giữ bản dữ liệu cũ để phục hồi. |
| AI lỗi nhưng fallback mất cảnh báo | Các nhánh trả OCR dự phòng giữ `ai_status`, lỗi đã làm sạch và `review_required`. |
| Phản hồi cũ xóa form mới | Chỉ reset ảnh/biển/vé khi draft vẫn trùng với snapshot gửi đi. |
| Tra cứu giới hạn 500 vé | Tìm biển vào/ra/mã vé và lọc ở server trước phân trang; UI có trang trước/sau và chặn phản hồi tìm kiếm cũ. |
| Lọc ngày sai định dạng timestamp | Parse datetime, hỗ trợ dấu cách/ISO `T` và timezone. Thời gian không có offset được hiểu theo UTC+7; ngày cuối lấy hết ngày; đầu vào sai trả 400. |
| Báo thiết bị sẵn sàng khi chỉ có URL | Tách `CONFIGURED` khỏi trạng thái kết nối; hardware vẫn fail trong kiểm tra production hoặc warn ở demo khi dùng simulator. Readiness ứng dụng dò schema database và signing key thật; không tự chấm điểm test/bảo mật. |
| Review không xem lại được ảnh | Có endpoint ảnh theo vé, kiểm tra đăng nhập và containment uploads, MIME/nội dung ảnh và no-store; UI tải lười hai ảnh qua bearer, thu hồi blob khi rời trang. |

Đã sửa thêm README để dùng requirements web/lệnh web hiện tại; khởi động kiểm tra đủ nhóm dependency bắt buộc và báo lỗi seed thay vì giấu lỗi.

Kiểm tra ứng dụng thật phát hiện signing key chưa đạt yêu cầu. Đã tạo ngẫu nhiên khóa cục bộ mạnh, chỉ thay cấu hình khóa này, không in giá trị hoặc đổi cấu hình provider. Khởi động lại ứng dụng; `/readiness` trả 200 với database/auth đạt, thiết bị vẫn báo mô phỏng. Các phiên cũ cần đăng nhập lại. Công cụ `scripts/configure_security.py` dùng khi chạy thủ công và được gọi bởi `start.bat`; khóa đã đủ mạnh được giữ nguyên.

## Xác minh trình duyệt

- Dùng bản sao phục vụ tại localhost:8002 và tài khoản giả, không dùng dữ liệu vận hành.
- Review mở được cả hai ảnh giả, mỗi ảnh decode ở chiều rộng gốc 800 px.
- Tìm được `FIXTURE-0502` trong bộ 504 vé, qua tìm kiếm server.
- Kiểm tra ở màn hình mặc định và 390 × 844; không tràn ngang; console không ghi nhận lỗi.
- Nguồn gốc và transcript kiểm thử được lưu trong thư mục `outputs/fixes-2026-11-01` của chat Codex.

## Lưu ý vận hành

- **Dừng server ITS trước restore.** Không chạy restore trên database đang được ứng dụng ghi. Phát hiện sidecar WAL/SHM/journal sẽ từ chối thao tác. Rollback xử lý lỗi phát sinh trong quá trình cài đặt; không cam kết giao dịch nguyên tử đồng thời giữa database và thư mục ảnh khi bị cắt điện hoặc tiến trình bị kill.
- Dữ liệu cũ được giữ cạnh đích dưới hậu tố `.before-restore-<id>`. Kiểm chứng dữ liệu sau restore trước khi quyết định dọn các bản cũ.
- `--dry-run` không tạo thư mục hay ghi dữ liệu; chỉ xem cấu trúc/tên/manifest của archive, chưa chạy kiểm tra SQLite nội dung.
- `/readiness` có thể trả 503 nếu database thiếu schema hoặc signing key yếu. `/health` vẫn là liveness. `/system/scorecard` trả điểm `null` vì không có phép đo điểm khách quan; client tích hợp cần xử lý giá trị này.
- API ảnh mới: `GET /tickets/{ticket_id}/images/entry` hoặc `/exit`, cần bearer hợp lệ; không được mở công khai thư mục uploads để thay thế.
- Camera IP/RTSP, MQTT và barrier thật **chưa có adapter trong bản hiện tại**. Các URL không tự tạo kết nối; webcam trình duyệt là luồng riêng. Chưa kiểm chứng phần cứng thật hoặc gọi AI provider thật trong lượt này.
- `start.bat` được rà nguồn; không chạy toàn bộ script trong lượt kiểm thử để tránh cài dependency hoặc seed vào dữ liệu vận hành.

Các test thêm nằm trong `tests/test_review_fixes.py` và `tests/test_web_ui.cjs`; test readiness đã được cập nhật theo hợp đồng không tự chấm điểm.
