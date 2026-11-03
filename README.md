# ITS Parking — đồ án phần mềm quản lý xe vào/ra

SPA HTML/CSS/JavaScript + FastAPI + SQLite, nhận dạng biển số có người đối chiếu, quản lý vé, biểu phí, thanh toán và audit. Phạm vi học thuật đã chốt: **phần cứng mô phỏng**. Model vision/detector là thành phần tích hợp có sẵn, không nhận là mô hình tự huấn luyện.

## Bắt đầu

Môi trường đã chọn để tái lập: **Windows x64, Python 3.14, Node.js 26.13.0**. Mở PowerShell ở thư mục chứa README:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements/windows-py314.lock.txt
.venv\Scripts\python.exe -m pip check
```

Lock gồm cả dependency test/local OCR. Nếu chỉ dùng web và vision đã cấu hình, có thể cài `requirements_web.txt`; đó không phải bộ cài đầy đủ của regression. Không cần Node cho runtime SPA, chỉ cần khi kiểm thử JavaScript.

## Hai cách mở app

| Mục đích | Lệnh | Dữ liệu và kết nối |
|---|---|---|
| Demo ngoại tuyến trên máy bảo vệ | `start_demo.bat` | `http://127.0.0.1:8001`, DB riêng trong `work/offline-demo`; OCR nhập tay, bank tắt, thiết bị mô phỏng |
| Dùng cấu hình/dữ liệu hiện có | `start.bat` | `http://127.0.0.1:8000`, đọc `.env`; không tạo tài khoản demo hoặc đăng nhập MB |

Hai launcher dùng `.venv` nếu có, kiểm tra dependency/cổng/signing key, chỉ mở browser sau readiness đạt. Nếu cổng đã dùng, không dừng process khác; chọn `--port` khác bằng CLI.

```powershell
.venv\Scripts\python.exe scripts/serve.py --demo --open-browser
.venv\Scripts\python.exe scripts/serve.py --check
.venv\Scripts\python.exe scripts/serve.py --open-browser
```

Tài khoản **chỉ trong demo ngoại tuyến**:

| Vai trò | Tên | Mật khẩu demo công khai |
|---|---|---|
| Quản trị | admin | ItsDemo@2026A |
| Điều hành | operator | ItsDemo@2026O |
| Chỉ xem | viewer | ItsDemo@2026V |

Demo có nhãn trên trang đăng nhập và các màn hình nghiệp vụ; mỗi lần khởi động có signing key mới nên cần đăng nhập lại. Không tạo prediction OCR giả. Dữ liệu demo được giữ qua lần mở lại; muốn buổi demo trắng dùng `--demo-dir work/demo-buoi-moi` với thư mục rỗng. Script từ chối thư mục đang có dữ liệu không mang marker demo.

## Cấu hình runtime hiện có

`.env.example` chỉ là mẫu; không ghi đè `.env` đang dùng. Tạo khóa ký bằng `python scripts/configure_security.py` nếu chưa có. Không đưa `.env`, `.mb_bridge_token`, DB, ảnh khách hoặc log vận hành vào Git. Mặc định runtime ở `~/plate_demo_data`; `ITS_BASE_DIR` có thể đổi. `ITS_LOAD_ENV=false` dùng cho demo/test để không nạp cấu hình cá nhân.

Vision chọn bằng `ITS_OPENAI_VISION_MODEL`, `ITS_OPENAI_BASE_URL`, `ITS_OPENAI_API_MODE`; cần provider/9Router đang chạy và khóa hợp lệ. Không có model cố định trong kiến trúc. Webcam trình duyệt cần localhost/HTTPS và quyền camera; chưa có kết nối IP/RTSP thật. MB worker khởi động riêng bằng `scripts/start_mb_bridge.py`; khởi động worker không đồng nghĩa đã đăng nhập. Xem `docs/MB_INTEGRATION.md` và `docs/AUTO_MB_AND_FAST_GATE.md`.

## Luồng nghiệp vụ

1. Chọn/chụp ảnh; kiểm tra biển nhận dạng hoặc nhập tay đầy đủ, rồi xác nhận xe vào.
2. Xe ra chỉ tự chọn vé khi có một biển khớp chính xác; lệch biển vào NEEDS_REVIEW.
3. Operator/admin xử lý review; admin hủy có lý do. Viewer chỉ xem.
4. Biểu phí chỉ bắt đầu dùng sau khi admin xác nhận bật; mỗi vé giữ snapshot riêng. Vé đủ điều kiện mới được thu, receipt idempotent.
5. QR/order được lưu trên server; MB mất phiên không được tự báo đã thu. Đối soát đọc tiền vào, không có chức năng chuyển tiền.

Ảnh JPG/PNG/WEBP tối đa 10 MB, validate nội dung và giới hạn pixel. Token quét gắn ảnh/người dùng. Nhiều biển, bất đồng engine, kết quả không đủ chắc chắn cần người kiểm tra; không đổi B/8 hoặc O/0 khi đối chiếu định danh.

## Kiểm thử và báo cáo

```powershell
.venv\Scripts\python.exe scripts/isolated_checks.py --coverage --output-dir work/submission-checks
.venv\Scripts\python.exe scripts/demo_acceptance.py --output work/demo-acceptance.json
```

Runner tạo checkout và DB tạm, tắt bank/vision thật. Có JUnit, Node output, line/branch coverage và source manifest. Không dùng số test lịch sử để xác nhận bản source mới. Workflow GitHub nằm ở `.github/workflows/checks.yml`; cần run thật sau khi đưa repo lên GitHub, chưa tự xuất bản trong phiên làm việc này.

## Đo OCR có ground truth

```powershell
python scripts/field_evaluate.py prepare path/to/images work/field/labels.csv
# Người gán nhãn và người review độc lập hoàn thành CSV; không dùng OCR để tự điền nhãn test.
python scripts/field_evaluate.py validate work/field/labels.csv
python scripts/field_evaluate.py run work/field/labels.csv --output work/field/local-test.json
# Chỉ thêm --live khi muốn gửi chính bộ ảnh này cho vision provider đã cấu hình.
```

Phải có SHA-256 ảnh, group/split, điều kiện, hành động read/abstain và nguồn review. Validator chặn ảnh trùng, nhóm/biển rò development–test và nhãn gợi ý từ OCR. Báo exact identity, false accept, abstention, lỗi và latency P50/P95/max. Phần mềm chỉ xác minh metadata; người nộp chịu trách nhiệm tính độc lập của nhãn.

Các CSV `*_prefilled.csv` cũ là gợi ý cần review, không tự được xem là ground truth. `scripts/run_benchmark.py <predictions.csv>` chỉ tổng hợp dự đoán đã có; thiếu predictions sẽ báo lỗi, thiếu latency/nhãn sẽ báo chưa đo.

## Hồ sơ nộp và bảo vệ

- [Kiến trúc, trạng thái, sequence và quan hệ dữ liệu](ARCHITECTURE.md)
- [Ma trận yêu cầu → code → test](docs/REQUIREMENTS_TRACEABILITY.md)
- [Cài lại, CI và ý nghĩa coverage](docs/TESTING_AND_REPRODUCIBILITY.md)
- [Protocol thực nghiệm OCR](docs/FIELD_BENCHMARK_PROTOCOL.md)
- [Kịch bản demo và câu hỏi bảo vệ](docs/DEFENSE_GUIDE.md)
- [Nguồn thư viện/model và đóng góp](docs/THIRD_PARTY_AND_CONTRIBUTIONS.md)
- [Quy tắc nghiệp vụ](docs/BUSINESS_RULES.md)

Các báo cáo có ngày tháng và `docs/archive` là lịch sử. Tài liệu kiến trúc hiện tại và kết quả chạy kèm hash là nguồn đánh giá bản nộp.

## Backup / giới hạn

`python scripts/bootstrap.py backup` dùng SQLite online backup, gồm WAL đã commit. Trước restore phải dừng server: `python scripts/bootstrap.py restore <archive.zip>`. Restore kiểm tra archive/SQLite, giữ bản `.before-restore-*`; `--dry-run` không thay dữ liệu. Không công khai archive chứa dữ liệu vận hành.

Hệ thống đã có RBAC, thu hồi phiên, transaction, đối soát idempotent và cơ chế phục hồi. Chưa có bằng chứng để khẳng định OCR đúng trong mọi hoàn cảnh, vận hành nhiều làn/máy hoặc phần cứng thật. Điểm học phần phụ thuộc rubric và khả năng giải thích của sinh viên; công cụ không tự cấp điểm 10.
