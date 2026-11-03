# Cài lại và kiểm chứng bản nộp

Môi trường mục tiêu: Windows x64, Python 3.14, Node.js 26.13.0. File lock chứa SHA-256 của wheel cho môi trường này. Không dùng lock này để tuyên bố đã kiểm thử Linux/macOS/Python khác.

## Cài sạch

Tại thư mục gốc dự án, chạy PowerShell:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements/windows-py314.lock.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe scripts/isolated_checks.py --coverage --output-dir work/submission-checks
.venv\Scripts\python.exe scripts/demo_acceptance.py --output work/demo-acceptance.json
```

Node phải nằm trong PATH. Bộ lock là superset phục vụ regression/OCR cục bộ; `requirements_web.txt` chỉ đủ cho web và vision đã cấu hình. `requests` là dependency của worker MB, được khai báo trong bộ test để phép thử adapter không dựa vào gói có sẵn trên máy.

`isolated_checks.py` tạo một checkout tạm theo danh sách thư mục được phép, không sao chép `.env`, bridge token, DB hoặc ảnh vận hành. Môi trường không kế thừa biến cấu hình ITS; bank thật và vision thật bị tắt. Conftest có DB tạm riêng. File bằng chứng lưu ngoài checkout tạm:

- `source-manifest.json`: hash tệp source đã thử.
- `backend-junit.xml`, `backend-output.txt`: số test/fail/error/skip.
- `frontend-output.txt`: kết quả Node test runner.
- `coverage.json`, `coverage.xml`, `coverage-report-output.txt`: line và branch coverage của `api`, `backend`, `integrations` trong tiến trình pytest. Không đo JS, script CLI hay tiến trình con.
- `checks-summary.json`: mã trả về của từng bước. Coverage kết hợp line/branch tối thiểu 75%; đây là ngưỡng hồi quy, không phải tiêu chí “75% chất lượng”.

Chỉ nhận bản nộp nếu mọi bước thành công, không bỏ qua test bắt buộc, hash khớp bản nộp. Không tái sử dụng báo cáo test cũ sau khi sửa source.

## CI

`.github/workflows/checks.yml` chạy Windows + lock + test + smoke demo và đính kèm artifact. Quyền workflow chỉ đọc source. Đây là cấu hình sẵn; chỉ có thể gọi là CI đã chạy khi repository được đẩy lên GitHub và có run thật. Bản cục bộ kiểm tra cùng lệnh nhưng không giả một GitHub run.

## Phạm vi test

Các bài test đồng thời kiểm tra transaction, idempotency, phiên và phản hồi trễ. Camera/MB/provider được giả ở ranh giới tích hợp; test mô hình CAPTCHA chỉ dùng ảnh đã hết hạn, không đăng nhập. Cần tránh lấy số test hoặc coverage để suy ra độ chính xác OCR. Protocol thực nghiệm nằm trong `FIELD_BENCHMARK_PROTOCOL.md`.

## Cập nhật lock

Tạo venv mới, nâng các dependency trực tiếp có chủ đích, resolve bằng pip `--report`, lưu version và hash wheel từ `download_info.archive_info.hashes.sha256`, rồi chạy lại toàn bộ. Đừng `pip freeze` cả môi trường cá nhân có thư viện không liên quan. Giữ bản lock trước để rollback.
