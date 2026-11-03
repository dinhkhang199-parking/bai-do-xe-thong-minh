# Kiến trúc ITS Parking

Bản đồ source hiện tại, cập nhật 03/11/2026. Phạm vi: đồ án phần mềm năm 3, phần cứng mô phỏng. Frontend là SPA HTML/CSS/JavaScript được FastAPI phục vụ; Streamlit chỉ còn trong tên tương thích của một số hàm/cấu hình và tài liệu lịch sử.

```mermaid
flowchart LR
    U[Nhân viên / quản trị / người xem] --> SPA[SPA: frontend/web]
    SPA -->|HTTP + bearer session| API[FastAPI: api/main.py]
    API --> APP[Application: app_service / scan_cache]
    API --> DOMAIN[parking_service / billing / auth]
    APP --> OCR[alpr_service và OCR adapters]
    APP --> DOMAIN
    DOMAIN --> DB[(SQLite: vé, users, phí, audit)]
    API --> READ[read_queries: tìm kiếm / phân trang]
    READ --> DB
    OCR --> LOCAL[Local detector / OCR]
    OCR --> VISION[Vision provider theo cấu hình]
    API --> SIM[Camera / MQTT / barrier simulators]
    MON[MB monitor] --> DB
    MON --> BRIDGE[Read-only MB bridge: loopback 5051]
    BRIDGE --> BANK[Dịch vụ MB bên ngoài]
```

## Ranh giới module

| Lớp | Trách nhiệm | Không nên làm |
|---|---|---|
| `frontend/web` | Nhập liệu, preview ảnh, bản nháp, trạng thái request, accessibility | Quyết định quyền hoặc thu tiền thay server |
| `api` | HTTP/schema, quyền, upload, status code, error sanitization; `web.py` phục vụ shell | Đặt logic phí trong giao diện |
| `backend/app_service.py` | OCR orchestration và xác nhận nghiệp vụ | Tự khẳng định ảnh đúng vì format hợp lệ |
| `backend/parking_service.py` | Transaction lifecycle, identity, review, cancel | Thay B/8 để làm biển khớp |
| `backend/billing.py` | Tariff snapshot, quote, tiền mặt/chuyển khoản do operator ghi nhận | Sửa phí vé cũ theo bảng phí mới |
| `backend/mb_*` | Yêu cầu QR bền vững, đối soát, polling | Chuyển tiền hoặc tự đăng nhập ngân hàng |
| `backend/db.py`, `migrations.py`, `read_queries.py` | Schema, SQL, truy vấn có giới hạn | Trả mọi vé để browser tự tìm |
| `backend/field_evaluation.py` | Hợp đồng ground truth, chống rò split, số đo chọn lọc | Biến kết quả OCR thành ground truth |
| `integrations` | Ranh giới với model/provider/worker và thiết bị mô phỏng | Báo SIMULATED thành CONNECTED vì có URL |

API router và `app.js` còn lớn; các nghiệp vụ dữ liệu đã ở backend, billing/camera/MB UI đã có module riêng. Không cần đổi framework chỉ để tăng số module. Tiếp tục tách theo trách nhiệm khi có chức năng mới, giữ tests bảo vệ contract.

## Trạng thái vé

```mermaid
stateDiagram-v2
    [*] --> IN_PARKING: biển đầy đủ + chưa có vé mở
    IN_PARKING --> COMPLETED: biển ra khớp chính xác
    IN_PARKING --> NEEDS_REVIEW: lệch biển
    NEEDS_REVIEW --> NEEDS_REVIEW: REJECT_EXIT
    NEEDS_REVIEW --> COMPLETED: MARK_MATCH / APPROVE_EXIT có quyền
    IN_PARKING --> CANCELLED: admin + lý do
    NEEDS_REVIEW --> CANCELLED: admin + lý do
    COMPLETED --> [*]
    CANCELLED --> [*]
```

`COMPLETED` là hoàn tất đối chiếu xe ra, **không đồng nghĩa đã thanh toán** hoặc đã mở barrier thật. Thanh toán là bản ghi riêng và chỉ được ghi khi vé đủ điều kiện. Một biển không thể có hai vé ở IN_PARKING/NEEDS_REVIEW. Kiểm tra rồi ghi trong `BEGIN IMMEDIATE` để tránh hai request cùng vượt kiểm tra.

## Nhận ảnh và xác nhận

```mermaid
sequenceDiagram
    actor O as Nhân viên
    participant W as SPA
    participant A as FastAPI
    participant S as OCR / Scan cache
    participant D as Parking service / SQLite
    O->>W: Chọn/chụp ảnh
    W->>A: POST /ocr
    A->>S: Validate/lưu ảnh rồi nhận dạng
    S-->>A: Candidate + usability + hash/owner token
    A-->>W: Kết quả và cảnh báo
    O->>W: Đối chiếu / sửa / nhập tay
    W->>A: POST /vehicle/entry hoặc exit + token
    A->>S: Kiểm tra owner và hash ảnh
    A->>D: Xác nhận biển trong transaction
    D-->>A: Vé + event + audit
    A-->>W: Kết quả; mismatch vào review
```

Token là cache có hạn trong process, không phải bằng chứng OCR chắc chắn đúng. Ảnh đổi, user đổi, token hết hạn hoặc server restart phải được xử lý theo contract; không gán kết quả cũ cho ảnh mới. Demo ngoại tuyến trả rõ OCR chưa chạy và cho nhập tay, không phát sinh prediction giả.

## Dữ liệu (quan hệ logic)

```mermaid
erDiagram
    PARKING_LOGS ||--|| TICKET_BILLING : snapshot
    PARKING_LOGS ||--o| PARKING_PAYMENTS : receipt
    PARKING_LOGS ||--o{ PARKING_EVENTS : history
    PARKING_LOGS ||--o{ MB_ORDERS : requests
    MB_ORDERS ||--o| MB_MATCHES : bank_evidence
    APP_USERS ||--o{ AUDIT_LOGS : actor
    PARKING_TARIFFS ||--o{ TICKET_BILLING : copied_policy
    APP_USERS ||--o{ MB_QR_REQUESTS : created_by
```

Sơ đồ mô tả liên hệ nghiệp vụ, không khẳng định tất cả cạnh được khai báo bằng foreign key SQLite. `parking_logs.ticket_id`, `ticket_billing.ticket_id`, `parking_payments.ticket_id` là khóa chính riêng. `qr_token`, `receipt_id` unique; `mb_matches` khóa `(account_no, bank_reference)` chặn dùng lại giao dịch. `policy_json` của vé là snapshot; update bảng phí không cascade vào vé cũ. `app_users.auth_version` buộc phiên cũ mất hiệu lực sau thay đổi quan trọng.

## Thanh toán

```mermaid
sequenceDiagram
    participant W as SPA
    participant A as API / Billing
    participant M as MB monitor
    participant B as MB worker
    participant D as SQLite
    W->>A: Yêu cầu finance / quote
    A->>D: Đọc vé và snapshot
    A-->>W: state + amount + quote_id
    alt Tiền mặt
        W->>A: Xác nhận amount/quote/received
        A->>D: Transaction + receipt duy nhất
    else Đối soát MB
        W->>A: Tạo QR order đủ điều kiện
        A->>D: Lưu pending order
        M->>B: Đọc trạng thái và lịch sử tiền vào
        B-->>M: Bank records hoặc lỗi
        M->>D: Chỉ khớp khi đúng receiver/amount/code/reference
    end
    W->>A: Đọc receipt
    A-->>W: Trạng thái từ database
```

Mất kết nối không được đánh dấu đã trả. Model/worker/camera thật là các dependency tùy chọn; không nằm trong đường chạy của bộ test cô lập. Khởi động web không bắt đầu đăng nhập MB.

## Quyết định và giới hạn

- **SPA + FastAPI:** cùng một nguồn quy tắc ở backend, frontend mỏng theo thao tác. Vanilla JS phù hợp quy mô đồ án; cần giữ race guards khi tách module.
- **SQLite:** phù hợp demo đơn máy, hỗ trợ transaction/backup online. Không suy ra khả năng mở rộng nhiều máy từ test nhỏ; cần thêm thử tải trước pilot.
- **Human confirmation:** giảm hậu quả khi OCR sai; chấp nhận thêm thao tác và độ trễ. Accuracy và usability là hai chỉ số khác nhau.
- **Dependency lock theo nền tảng:** tái lập Windows x64/Python 3.14; nền tảng khác cần lock/test riêng.
- **Hai launcher:** `start.bat` dùng cấu hình hiện có trên 8000; `start_demo.bat` cô lập dữ liệu, không tải `.env`, cổng 8001. Cả hai chỉ bind loopback, không seed tài khoản demo vào DB vận hành.
- **Không tự chấm điểm:** `/system/scorecard` và báo cáo mô tả bằng chứng. Điểm học phần do rubric và phần bảo vệ quyết định.

Xem `docs/REQUIREMENTS_TRACEABILITY.md`, `docs/TESTING_AND_REPRODUCIBILITY.md`, `docs/FIELD_BENCHMARK_PROTOCOL.md`, `docs/THIRD_PARTY_AND_CONTRIBUTIONS.md`. Số test chính thức lấy từ báo cáo cùng source hash, không duy trì một con số cứng dễ lỗi thời trong tài liệu kiến trúc.
