# Rà soát lại sau bản academic release

Phạm vi: tính đúng nghiệp vụ và bằng chứng kiểm thử; không phải chứng nhận bảo mật hoặc kiểm chứng OCR ngoài bãi.

## Các lỗi được sửa

1. **Vé và history chưa atomic khi ghi history lỗi.** Trước đây vé commit trước rồi event/audit được ghi bằng connection riêng, lỗi chỉ được log. Nay vào, ra, resolve và cancel ghi vé/event/audit trong cùng transaction; lỗi history làm toàn bộ thao tác rollback. `append_audit_log` và `append_parking_event` nhận `connection` tùy chọn, không commit connection do caller quản lý. Đã dùng SQLite trigger cố tình làm lỗi từng bảng, từng thao tác để kiểm chứng.
2. **Múi giờ không nhất quán.** Timestamp và phần ngày của mã vé nay dùng UTC+07:00 rõ ràng, độc lập timezone hệ điều hành. Lịch sử event/audit cũ dùng SQLite `CURRENT_TIMESTAMP` (UTC) được trả kèm offset và sắp theo thời điểm thực; không sửa dữ liệu cũ trong DB. Thời gian vé cũ không có offset vẫn được hiểu là giờ Việt Nam như trước.
3. **Báo cáo test có thể còn kết quả đạt cũ khi run mới bị ngắt.** Runner đánh dấu run chưa đạt ngay khi bắt đầu, ghi JSON atomic, báo timeout/thiếu Node/JUnit lỗi/gián đoạn thành thất bại. Không coi không có test hoặc test bị skip là pass. Khóa thư mục output để hai run không ghi chồng. Wrapper cô lập chạy báo cáo trong scratch, rồi chỉ xuất đúng artifact của lượt mới.
4. **Chạy pytest trực tiếp có thể kế thừa đường dẫn DB tuyệt đối hoặc provider từ môi trường.** Conftest nay bỏ cấu hình `ITS_*` kế thừa trước khi thiết lập đường dẫn/credentials fixture; test gửi một DB sentinel và khóa giả từ môi trường để xác nhận không chạm DB đó, không bật provider.
5. **Bằng chứng benchmark có thể đổi giữa lúc chạy.** CSV được đọc một lần, ảnh được copy và kiểm hash trước khi suy luận; kết quả lưu manifest snapshot/hash ban đầu. Nếu inference sửa bản ảnh đã đóng băng hoặc code/weights đổi trong lúc chạy, không xuất kết quả đạt. Ghi báo cáo bằng atomic create-if-absent, không ghi đè chứng cứ trước. Header trùng/cột thừa không tên bị từ chối.

## Cách kiểm tra

```powershell
.venv\Scripts\python.exe scripts/isolated_checks.py --coverage --output-dir work/recheck-results
.venv\Scripts\python.exe scripts/demo_acceptance.py --output work/recheck-demo.json
```

`checks-summary.json` có mục `run`: chỉ nhận `state=completed` và `passed=true`, cùng các component đạt. Một `.checks.lock` còn lại sau khi tiến trình bị buộc dừng không được tự xóa khi chưa rõ run cũ đã kết thúc; dùng thư mục output mới để tiếp tục.

Các test bổ sung: `test_deep_recheck.py`, `test_check_runner_integrity.py`, `test_test_environment_isolation.py`, `test_field_snapshot.py`. Kết quả lượt rà soát: 545 backend + 144 frontend, 0 fail/error/skip; 21 bước HTTP demo qua. Coverage line/branch kết hợp khoảng 77,98% trên api/backend/integrations. Chạy lại và đối chiếu source manifest khi source thay đổi.

Giới hạn còn nguyên: nhãn độc lập/đủ đa dạng cho field accuracy, phần cứng thật ngoài phạm vi phần mềm đã chốt, bank/vision thật không được dùng cho nghiệm thu fixture. Không suy ra độ chính xác OCR hay điểm học phần từ số test.
