# Nguồn thành phần và phạm vi đóng góp

Không có xác nhận nhóm tự huấn luyện một mô hình mới. Giá trị đồ án nằm ở thiết kế quy tắc, orchestration, cơ chế từ chối OCR, giao diện, persistence, tích hợp và kiểm chứng. Người nộp phải tự xác nhận phần đóng góp của từng thành viên.

| Thành phần | Nguồn/vai trò | Trạng thái ghi nhận |
|---|---|---|
| FastAPI, Uvicorn, SQLite, pandas, Pillow, qrcode | Thư viện/nền tảng có sẵn | Version thực tế được khóa trong requirements; license trong package metadata |
| 9Router và model vision cấu hình | Dịch vụ nhận dạng qua API tương thích; model tùy cấu hình runtime | Không tự nhận đã huấn luyện model; không đưa khóa provider vào báo cáo |
| EasyOCR, Fast-ALPR, ONNX Runtime | OCR/detector pretrained và runtime có sẵn | Optional engines; chỉ khai báo engine thực sự dùng trong phép đo |
| `models/external/sourudra-*.pt` | Weights có sẵn trong archive người dùng cung cấp | README cũ ghi reference repository nhưng thiếu URL/commit/license cụ thể; cần bổ sung trước phát hành công khai |
| `integrations/person1/plate_detection_phase1/license_plate.pt` | Detector có sẵn trong archive dự án | Nguồn/tác giả/license chưa được xác minh độc lập |
| `models/mb-captcha.onnx` | Bản người dùng cung cấp từ `bank_captcha_solver-master/mbbank/mbbank.onnx` | Xem `models/mb-captcha.md`; chỉ fixture ảnh hết hạn trong test |
| jsQR, three.js | Vendor trong `frontend/web/vendor` | Giữ các file LICENSE đi kèm |
| Multica | Công cụ điều phối phát triển bên ngoài | Không phải nền tảng do nhóm xây dựng; mirror phát triển không tự đồng bộ source vận hành |
| Công cụ sinh mã/AI hỗ trợ | Hỗ trợ sửa lỗi, viết test, tài liệu | Ghi rõ trong báo cáo; sinh viên chịu trách nhiệm đọc, kiểm chứng và giải thích |

`docs/model-assets.json` lưu hash của weights đang có để phân biệt phiên bản; hash không thay thế quyền sử dụng hoặc nguồn gốc. Chưa có quyền phát hành nào được suy ra từ tên file. Bản local không được tự đẩy công khai.

## Bảng nhóm cần tự hoàn thiện

| Thành viên | Phần thực sự làm | Commit/PR/test/bằng chứng | Có thể giải thích trực tiếp |
|---|---|---|---|
| Chưa cung cấp | Chưa xác nhận | Chưa cung cấp | Chưa đánh giá |
