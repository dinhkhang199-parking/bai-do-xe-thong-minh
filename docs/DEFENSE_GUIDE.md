# Kịch bản bảo vệ đồ án phần mềm

## Phạm vi và đóng góp

ITS hỗ trợ nhân viên quản lý xe vào/ra, nhận dạng từ ảnh, đối chiếu vé, tính phí và audit. Phần cứng được mô phỏng theo phạm vi người dùng xác nhận. Không phải hệ thống tự lái/barrier tự trị; OCR cần người xác nhận. Phân biệt phần tự thiết kế nghiệp vụ/tích hợp/kiểm thử với thư viện, pretrained weights, dịch vụ vision và mã được AI hỗ trợ. Mỗi thành viên điền đóng góp thật và tự giải thích source.

## Demo 10–12 phút

1. `start_demo.bat`: chỉ ra nhãn Demo ngoại tuyến, cổng 8001 và DB riêng. Đăng nhập admin; giải thích dữ liệu rỗng là thật. Demo có thể nhập tay khi không có mạng.
2. Bật một biểu phí demo, mô tả vì sao biểu phí mặc định chưa dùng thu tiền và snapshot được lưu lúc vào.
3. Đăng nhập operator. Chọn ảnh thử; nhập biển đầy đủ, xác nhận vào, xem vé/QR. Gửi trùng biển: hệ thống chặn.
4. Cho xe ra sai một ký tự, chỉ ra NEEDS_REVIEW và thanh toán chưa được phép. Review có lý do rồi hoàn tất.
5. Thu tiền mặt trong DB demo; thử gửi lại yêu cầu: receipt giữ nguyên. Đổi biểu phí, giải thích vé cũ vẫn có snapshot cũ.
6. Đăng nhập viewer; chỉ xem. Nêu rằng API kiểm quyền độc lập với việc giấu nút.
7. Mở báo cáo test/coverage/source manifest và ma trận yêu cầu; diễn giải một test race.
8. Chuyển bản cấu hình thật bằng `start.bat` ở 8000 để demo OCR khi đã chuẩn bị provider. Nếu provider mất kết nối, dùng đối chiếu/nhập tay và nói rõ OCR thật chưa chạy trong demo ngoại tuyến.
9. Trình bày kết quả field evaluation nếu đã có nhãn độc lập; nếu chưa có, nêu đúng giới hạn và công cụ đo đã hoàn thành. Không gọi 12 ca chẩn đoán là độ chính xác toàn bộ bãi.

Không thử giao dịch MB thật hoặc thay phiên ngân hàng trong buổi demo bất ngờ. Dùng hồi quy provider giả để giải thích thuật toán đối soát.

## Câu hỏi cốt lõi và hướng chứng minh

| Câu hỏi | Source/bằng chứng để tự trình bày |
|---|---|
| Hai cổng gửi cùng biển thì sao? | `BEGIN IMMEDIATE`; test 48 lần vào/36 lần ra đồng thời |
| Vì sao không sửa B thành 8 khi đối chiếu? | Phân biệt candidate OCR với định danh vé; test identity và benchmark integrity |
| OCR đúng format có chắc đúng xe không? | Không; ảnh nhiều biển, uncertainty, disagreement và human confirmation |
| Phản hồi đến sau khi đổi ảnh/tài khoản? | Scan token hash/owner và frontend request guards |
| Đổi phí có làm sai vé cũ? | `ticket_billing.policy_json` chụp tại entry; quote có hash |
| Giao dịch được đọc hai lần có thu hai lần? | Unique receipt/ticket và bank_reference theo account; transaction |
| Tại sao SQLite? | Đơn máy và tải đồ án; transaction đơn giản. Nhiều máy/làn cần kiểm thử tải và thiết kế DB phù hợp |
| Tại sao API và SPA? | Phân tách HTTP/UX khỏi nghiệp vụ; tránh nhân bản quy tắc ở UI |
| OCR accuracy đo thế nào? | Nhãn người kiểm độc lập, nhóm không rò split, hash ảnh, exact identity, false accept, abstain, P95 |
| Coverage 75% nói gì? | Mã đã chạy trong test, không phải chứng minh không có bug hay chất lượng nhãn |
| Những gì chưa có? | Phần cứng thật ngoài phạm vi; CI remote, field validation và đóng góp cá nhân chỉ ghi khi có chứng cứ |

## Bài tập bảo vệ cá nhân

Tự giải thích và thực hiện một thay đổi nhỏ (ví dụ sửa khoảng miễn phí, thêm filter nhật ký) trong checkout tạm; viết test đúng nghiệp vụ, chạy test và giải thích diff. Không học thuộc điểm số. Rubric giảng viên và phần trả lời trực tiếp quyết định điểm học phần.
