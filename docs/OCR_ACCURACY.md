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
3. Provider/model dùng cấu hình runtime hiện có. Mỗi request gồm tối đa ba ảnh
   chi tiết cao: toàn cảnh, vùng cắt nguyên bản, vùng cắt tăng tương phản nhẹ.
   Đây là các góc nhìn của cùng ảnh, không phải ba cảnh độc lập.
4. Nếu lượt đầu đọc rõ đúng một biển và không có ký tự nghi ngờ, gửi thêm **một**
   request mới với ảnh và yêu cầu kiểm tra từng hàng/ký tự. Không gửi đáp án
   lượt đầu, danh sách vé hay biển dự kiến cho lượt kiểm chứng.
5. Chỉ cho dùng gợi ý khi hai lượt cùng đọc được và khớp toàn bộ định danh.
   Không đọc được, nhiều biển, lệch ký tự, lỗi provider hoặc quá thời gian
   kiểm chứng thì để trống gợi ý và yêu cầu nhập tay/chụp lại.

Lượt đầu đã từ chối thì không gọi thêm để ép ra một đáp án. Hai lượt của cùng
model vẫn có thể sai giống nhau; đây không phải mô hình độc lập hay bảo đảm 100%.
`confidence` của vision tiếp tục là `null`, `review_required` luôn là `true`.
`verification` ghi trạng thái `agreed`, `disagreed`, `unavailable`, `timeout`
hoặc `not_attempted`, số request đã thử và phân tích lượt kiểm chứng nếu có.

## Thời gian và OCR dự phòng

Budget hai lượt là `min(2 × timeout cấu hình, 75 giây)`, tính từ lúc chuẩn bị
ảnh. Mỗi request chỉ được phần thời gian còn lại, tối đa timeout cấu hình.
Không bắt đầu lượt mới khi đã hết budget; đáp án usable đến muộn bị loại.
Timeout của SDK là timeout I/O, không phải cơ chế hủy cứng toàn bộ worker.
UI giữ thời hạn 90 giây và nút dừng để nhập tay. Một ảnh dùng được thường cần
hai request; có thể tăng độ trễ và chi phí so với một lượt đọc.

EasyOCR/Paddle chỉ là dự phòng khi khả dụng. Không tự cài model lớn hoặc thay
primary provider. Kết quả local không tự sửa ký tự trước kiểm tra; ghép hai hàng
lấy confidence của hàng yếu hơn, không cộng điểm vì chuỗi hợp định dạng.
Khác biệt giữa các biến thể/fast/deep hoặc một tiền tố đã đọc khác biển đầy đủ
phải giữ trạng thái bất đồng, không chọn đáp án điểm cao rồi bỏ bằng chứng còn lại.
Các helper sửa ký tự cũ chỉ giữ tương thích; không dùng để tạo kết quả OCR usable.

## Bằng chứng và giới hạn

Regression chính: `tests/test_ocr_verification.py`, `tests/test_local_ocr_evidence.py`,
`tests/test_ocr_edge_cases.py`, `tests/test_plate_views.py`, `tests/test_ai_analysis.py`.
Chạy toàn bộ bằng `python scripts/isolated_checks.py --coverage`.

Diagnostic với bốn ảnh nguồn và các biến thể chỉ kiểm tra các trường hợp đã chọn.
Phải ghi riêng số đọc đúng, bỏ qua, nhận sai và lỗi/thời gian; giữ cả lần thất bại.
Ảnh có xe nền chưa rõ cần review nhãn cảnh, không đổi nhãn theo dự đoán của model.
Đánh giá ngoài bãi cần ảnh và nhãn độc lập theo `FIELD_BENCHMARK_PROTOCOL.md`;
không dùng kết quả diagnostic để quảng cáo độ chính xác thực địa.

App thật ở cổng 8000 sử dụng cấu hình AI hiện có. Cổng 8001 là demo ngoại tuyến,
không gọi OCR thật và không được tháo cách ly để giả vờ đã thử model.
