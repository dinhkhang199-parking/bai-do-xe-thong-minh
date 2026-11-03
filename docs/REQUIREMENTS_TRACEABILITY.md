# Ma trận yêu cầu và bằng chứng

Phạm vi chốt ngày 03/11/2026: đồ án **phần mềm**, camera IP/MQTT/barrier được mô phỏng. Mô hình AI có sẵn là thành phần tích hợp; người vận hành xác nhận trước ghi nhận. Không tự nhận điểm học phần hoặc chứng nhận triển khai ngoài bãi.

Mỗi test dưới đây phải chạy thành công trên cùng source manifest của bản nộp. Tên file là đường dẫn từ gốc repository, không thay cho kết quả chạy.

| ID | Yêu cầu/tiêu chí chấp nhận | API hoặc module | Kiểm chứng tự động |
|---|---|---|---|
| FR-01 | Đăng nhập; quyền viewer không ghi dữ liệu | `/auth/login`, `backend/auth.py` | `tests/test_api_auth_jwt.py`, `tests/test_api_contract.py` |
| FR-02 | Khóa/đổi quyền/xóa user làm phiên cũ hết hiệu lực | `/admin/users` | `tests/test_session_security.py` |
| FR-03 | Nhận ảnh hợp lệ, giới hạn 10 MB; không nhận ảnh hỏng | `/ocr`, `backend/storage.py` | `tests/test_storage_resize.py`, `tests/test_extended_regressions.py` |
| FR-04 | Nhiều biển/bất đồng/NaN không tự xác nhận; kiểm chứng vision và giữ nguyên định danh local | `backend/alpr_service.py`, `backend/openai_vision_adapter.py` | `tests/test_ocr_edge_cases.py`, `tests/test_vision_auto_fusion.py`, `tests/test_ocr_verification.py`, `tests/test_local_ocr_evidence.py` |
| FR-05 | Kết quả quét thuộc đúng ảnh và người dùng; không quét lại khi xác nhận | `/ocr`, `backend/scan_cache.py` | `tests/test_scan_reuse.py` |
| FR-06 | Một biển chỉ có một vé đang mở, kể cả yêu cầu đồng thời | `/vehicle/entry` | `tests/test_concurrent_lifecycle.py` |
| FR-07 | Biển xe ra khớp chính xác; B/8 là hai định danh | `/vehicle/exit` | `tests/test_review_fixes.py`, `tests/test_parking_service.py` |
| FR-08 | Lệch biển chuyển NEEDS_REVIEW; duyệt/hủy có quyền và lý do | `/tickets/{id}/resolve`, `/cancel` | `tests/test_parking_service.py`, `tests/test_api_contract.py` |
| FR-09 | Biểu phí đóng băng theo vé; thay phí không đổi lịch sử | `/pricing`, `/tickets/{id}/finance` | `tests/test_billing.py` |
| FR-10 | Chỉ thu vé đủ điều kiện, chặn quote cũ và thu hai lần | `/tickets/{id}/payment` | `tests/test_billing.py` |
| FR-11 | Đối soát tiền vào theo đúng số tiền/mã/receiver; không dùng lại giao dịch | `/tickets/{id}/mb-order`, `/payments/qr-requests` | `tests/test_mb_payments.py` với bank giả |
| FR-12 | Mất kết nối MB không tự ghi đã thu; không tự đăng nhập khi khởi động | `backend/mb_monitor.py`, `integrations/mb_readonly_worker.py` | `tests/test_mb_payments.py`, `tests/test_mb_worker_lifecycle.py` |
| FR-13 | Tìm vé trên server, mặc định 50 dòng; giữ bản nháp khi làm mới | `/tickets/active`, `frontend/web/app.js` | `tests/test_read_queries.py`, `tests/test_fullstack_regressions.py`, `tests/test_web_ui.cjs` |
| FR-14 | Phản hồi cũ không ghi đè ảnh/tài khoản mới; dừng quét để nhập tay | `frontend/web/app.js` | `tests/test_web_ui.cjs` |
| FR-15 | Audit, event, dữ liệu trạng thái nhất quán | `backend/parking_service.py`, `backend/db.py` | `tests/test_concurrent_lifecycle.py`, `tests/test_billing.py` |
| FR-16 | Adapter trả trạng thái SIMULATED, không báo kết nối thiết bị thật | `/devices/status`, `/devices/barrier/open` | `tests/test_device_integrations.py`, `tests/test_review_fixes.py` |
| NFR-01 | Backup gồm WAL đã commit; restore lỗi không mất DB cũ | `scripts/backup_runtime.py`, `restore_runtime.py` | `tests/test_fullstack_regressions.py`, `tests/test_review_fixes.py`, `tests/test_restore_runtime.py` |
| NFR-02 | Error JSON không lộ đường dẫn/khóa | `api/main.py` | `tests/test_api_path_redaction.py`, `tests/test_fullstack_regressions.py` |
| NFR-03 | Bộ cài/tự kiểm thử dùng được ngoài máy phát triển | `requirements/windows-py314.lock.txt`, `scripts/isolated_checks.py` | Cài venv sạch, `pip check`, CI Windows |
| NFR-04 | Demo ngoại tuyến tách DB/tài khoản, không gọi AI/MB | `scripts/serve.py --demo` | `tests/test_demo_launcher.py`, `scripts/demo_acceptance.py` |
| EVAL-01 | Không lấy nhãn làm prediction, không nhập nhằng B/8, không bịa latency | `backend/benchmarking.py` | `tests/test_evaluation_integrity.py` |
| EVAL-02 | Nhãn có người gán/người review, ảnh đóng hash, nhóm không rò split | `scripts/field_evaluate.py` | `tests/test_evaluation_integrity.py` |

## Tách ba mức bằng chứng

1. **Hợp đồng và thuật toán:** unit/integration tests chạy bằng fixture. Chứng minh các nhánh đã thử, không chứng minh OCR ngoài đời.
2. **Demo phần mềm:** server thật trên loopback, trình duyệt, API và DB riêng. Báo cáo `demo-acceptance.json` lưu kết quả; không có giao dịch ngân hàng thật.
3. **OCR thực nghiệm:** ảnh thật và nhãn được review độc lập, tách development/test. Chỉ báo độ chính xác khi có file đánh giá hợp lệ. Phiên bản này cung cấp công cụ, không tự tạo nhãn người gán hoặc bù số lượng mẫu.
