# OCR: độ chính xác và cơ chế kiểm chứng

Mục tiêu là đọc đúng **toàn bộ định danh**, giữ nguyên B/8, O/0, I/1, S/5,
Z/2. Đúng định dạng không chứng minh đúng xe. Kết quả vẫn cần người vận hành
đối chiếu ảnh trước xác nhận; không tự lấy biển đang đỗ để sửa đáp án xe ra.

## Pipeline đang chạy

1. Giữ ảnh upload nguyên vẹn, kiểm tra kích thước/dữ liệu và sửa hướng EXIF
   khi tạo góc nhìn. Ảnh toàn cảnh luôn được gửi để phát hiện nhiều biển.
2. Detector ONNX cục bộ tạo vùng cắt từ ảnh gốc khi thấy đúng một vùng biển.
   Với ảnh có cạnh dài từ 1200 px, chạy thêm bốn ô chồng lấp để hỗ trợ biển nhỏ;
   gộp quan sát trùng nhau, không gộp hai biển cạnh nhau. Tối đa năm lượt detector.
   Không tự tải trọng số. Thiếu detector vẫn có thể dùng vision toàn cảnh.
3. Provider/model dùng cấu hình runtime hiện có; ưu tiên 9Router trước OCR local.
   **Mặc định ưu tiên tốc độ:** một request, tối đa hai ảnh chi tiết cao (toàn cảnh
   và vùng cắt nguyên bản), không tạo ảnh tương phản sẽ bị bỏ đi. Model
   `gpt-6.1-sol` dùng reasoning `low`, giới hạn 2048 token; các model khác giữ
   mặc định riêng. Prompt yêu cầu đáp án gọn theo JSON schema.
4. Không đọc được, nhiều biển hoặc có ký tự chưa chắc thì để trống gợi ý và yêu
   cầu nhập tay/chụp lại. Single pass không có bằng chứng đồng thuận hai lượt;
   không được hiển thị là đã kiểm chứng hoặc chắc chắn đúng.
5. Khi cần chế độ kiểm chứng, đặt `ITS_OPENAI_VISION_VERIFY=true` rồi khởi động
   lại: thêm ảnh tương phản nhẹ, reasoning `high`/6144 token cho SOL, và một
   request ảnh mới nếu lượt đầu usable. Không gửi đáp án lượt đầu hay danh sách
   vé cho lượt sau. Hai lượt phải khớp toàn bộ định danh; bất đồng/lỗi kiểm chứng
   làm kết quả không usable. Chế độ này chậm hơn và không phải mặc định.

Lượt đầu đã từ chối thì không gọi thêm để ép ra một đáp án. Hai lượt của cùng
model vẫn có thể sai giống nhau; đây không phải mô hình độc lập hay bảo đảm 100%.
`confidence` của vision tiếp tục là `null`, `review_required` luôn là `true`.
`ocr_mode` ghi `fast` hoặc `verified`. `verification` ghi `single_pass` khi dùng
chế độ nhanh; các trạng thái khác gồm `agreed`, `disagreed`, `unavailable`,
`timeout`, `not_attempted`, số request đã thử và phân tích kiểm chứng nếu có.

## Thời gian và OCR dự phòng

Budget nhanh là `min(timeout cấu hình, 75 giây)` (mặc định 45 giây);
budget hai lượt là `min(2 × timeout cấu hình, 75 giây)`, tính từ lúc chuẩn bị
ảnh. Mỗi request chỉ được phần thời gian còn lại, tối đa timeout cấu hình.
Không bắt đầu lượt mới khi đã hết budget; đáp án usable đến muộn bị loại.
Timeout của SDK là timeout I/O, không phải cơ chế hủy cứng toàn bộ worker.
UI giữ thời hạn 90 giây và nút dừng để nhập tay. Mặc định chỉ gọi provider một
lần, không kiểm chứng nối tiếp, không đổi model hoặc đổi loại API khi gặp lỗi.
Xác nhận vé dùng lại scan token gắn đúng ảnh/người dùng, không gọi OCR thêm lần nữa.

EasyOCR/Paddle chỉ là dự phòng khi khả dụng. Không tự cài model lớn hoặc thay
primary provider. Kết quả local không tự sửa ký tự trước kiểm tra; ghép hai hàng
lấy confidence của hàng yếu hơn, không cộng điểm vì chuỗi hợp định dạng.
Khác biệt giữa các biến thể/fast/deep hoặc một tiền tố đã đọc khác biển đầy đủ
phải giữ trạng thái bất đồng, không chọn đáp án điểm cao rồi bỏ bằng chứng còn lại.
Các helper sửa ký tự cũ chỉ giữ tương thích; không dùng để tạo kết quả OCR usable.

## Bằng chứng và giới hạn

Regression chính: `tests/test_ocr_verification.py`, `tests/test_local_ocr_evidence.py`,
`tests/test_ocr_edge_cases.py`, `tests/test_plate_views.py`, `tests/test_ai_analysis.py`,
`tests/test_ocr_fast_mode.py` (một request, ưu tiên provider, giữ các guard và timeout).
Chạy toàn bộ bằng `python scripts/isolated_checks.py --coverage`.

Diagnostic với bốn ảnh nguồn và các biến thể chỉ kiểm tra các trường hợp đã chọn.
Phải ghi riêng số đọc đúng, bỏ qua, nhận sai và lỗi/thời gian; giữ cả lần thất bại.
Ảnh có xe nền chưa rõ cần review nhãn cảnh, không đổi nhãn theo dự đoán của model.
Đánh giá ngoài bãi cần ảnh và nhãn độc lập theo `FIELD_BENCHMARK_PROTOCOL.md`;
không dùng kết quả diagnostic để quảng cáo độ chính xác thực địa.

App thật ở cổng 8000 sử dụng cấu hình AI hiện có. Cổng 8001 là demo ngoại tuyến,
không gọi OCR thật và không được tháo cách ly để giả vờ đã thử model.
