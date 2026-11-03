# Protocol đánh giá OCR có nhãn độc lập

Mục tiêu là đo bản pipeline cụ thể trên bộ ảnh chưa dùng chỉnh model/ngưỡng. Không dùng độ chính xác định dạng, fixture test hoặc nhãn OCR gợi ý làm độ chính xác ngoài đời.

## Thu thập và gán nhãn

Đề xuất tối thiểu 100 ảnh thực tế, nên có 300+ với nhiều xe/cảnh độc lập. Bao gồm ngày, tối, chói, nghiêng, mưa/bẩn, nhòe, che khuất, không có biển và nhiều biển. Ghi rõ số mẫu/nhóm của từng điều kiện; không nhân 4 ảnh thành 300 biến thể rồi coi là 300 cảnh độc lập.

Chỉ sử dụng ảnh có quyền sử dụng phù hợp; không đẩy ảnh khách hoặc dữ liệu vận hành lên repo. Có thể chạy local. Tùy chọn `--live` sẽ gửi chính ảnh trong manifest tới provider đang cấu hình; chỉ dùng khi được phép sử dụng ảnh theo cách đó.

```powershell
python scripts/field_evaluate.py prepare path/to/images work/field/labels.csv
```

Script chỉ ghi đường dẫn và hash, để trống nhãn. Hai người phải gán và kiểm tra độc lập, không nhìn dự đoán của engine đang chấm trước khi hoàn tất. CSV có các cột:

| Cột | Nội dung |
|---|---|
| sample_id | Mã mẫu duy nhất |
| image_path, image_sha256 | Ảnh được review và hash bytes của ảnh |
| group_id | Cùng xe/cảnh/ảnh gốc và mọi biến thể phải cùng nhóm |
| split | `development` hoặc `test`; không để nhóm/biển xuất hiện ở cả hai |
| condition | Nhãn điều kiện, ví dụ day/night/glare/blur/multiple/no_plate |
| expected_action | `read` khi có một biển đủ đọc; `abstain` khi không thể quyết định an toàn |
| expected_plate | Đầy đủ ký tự khi read; rỗng khi abstain |
| label_source | `human`; `ocr-prefilled` không được nhận |
| labeler, reviewer | Hai danh tính khác nhau do nhóm xác nhận |
| reviewed_at | Ngày/giờ ISO thực sự review, không điền thời gian giả |

Validator kiểm tra cấu trúc, file/hash, duplicate bytes, group leakage và cùng biển rò split. Nó không xác minh một người có thực sự đọc ảnh hay không, không phát hiện được mọi ảnh gần giống, và không thay thế biên bản gán nhãn. Thông tin camera/địa điểm/quyền sử dụng nên lưu trong datasheet riêng, không công khai thông tin nhạy cảm.

## Đóng băng tập test

Sau khi gán nhãn, chọn split theo **nhóm trước khi đo**. Chỉ chỉnh pipeline/ngưỡng dựa trên development; không sửa nhãn test để khớp output. Nếu thực sự phát hiện lỗi nhãn, lập phiên bản dataset mới, ghi lý do và chạy lại toàn bộ. Giữ kết quả cũ, manifest hash, source hash và model/engine. `run` từ chối ghi đè file kết quả đã có.

```powershell
python scripts/field_evaluate.py validate work/field/labels.csv
python scripts/field_evaluate.py run work/field/labels.csv --split test --output work/field/local-v1.json
# Với provider đã được phép dùng cho bộ ảnh này:
python scripts/field_evaluate.py run work/field/labels.csv --split test --live --output work/field/vision-v1.json
```

Lệnh chạy gọi `process_plate_image`, cùng điểm vào nghiệp vụ với app, trong runtime riêng để không ghi crop/log vào dữ liệu vận hành. Không tạo vé, không đăng nhập MB. Bản local tắt vision; các engine local có thể cần weights/dependency đã cài từ trước. Bản vision ghi model public nhưng không xuất khóa/URL bí mật.

## Định nghĩa số đo

- **Exact plate accuracy:** số prediction đúng từng ký tự / số mẫu `read`; chỉ bỏ khoảng trắng/dấu trình bày và khác biệt hoa–thường, **không** đổi B↔8, O↔0. Đếm cả prediction bị từ chối; xem acceptance/decision riêng.
- **Accepted:** đúng predicate frontend `is_usable === true`, không ambiguous/disagreement; vẫn cần người xác nhận, không có nghĩa xe được mở cổng tự động.
- **False accept:** prediction được accepted nhưng sai biển hoặc mẫu yêu cầu abstain. Báo theo toàn bộ mẫu và riêng số accepted; mẫu lỗi provider không tự được coi là abstain thành công.
- **Abstention rate:** không accepted / tổng số mẫu; **safe abstention rate** chỉ tính các mẫu expected abstain được từ chối mà không lỗi pipeline.
- **Correct decision rate:** read phải đúng và accepted; abstain phải từ chối, không exception.
- **Latency:** thời gian từng lần gọi gồm lỗi, P50/P95 nearest-rank/max; lần đầu có thể chứa cold start. Không lấy thời gian đọc CSV làm latency OCR.
- **Wilson 95%:** khoảng cho exact accuracy, có giả định độc lập; ảnh cùng nhóm có tương quan nên khoảng này chỉ tham khảo, không làm tăng số cảnh độc lập.

Mẫu số rỗng trả `null` (chưa đo), không trả một điểm 100% hoặc tự suy ra accuracy. Mỗi điều kiện có thống kê riêng. `errors > 0` khiến CLI trả mã lỗi dù vẫn giữ toàn bộ báo cáo để điều tra; không loại ảnh khó khỏi mẫu số để làm đẹp kết quả.

## Chốt tiêu chí trước khi chạy

Rubric học phần chưa được cung cấp. Nhóm và giảng viên nên thống nhất mục tiêu exact accuracy/false accept/latency theo cảnh dùng. Với đồ án có người xác nhận, độ trễ 9–15 giây của mẫu vision trước cần được công bố; không đặt ngưỡng 2 giây rồi tuyên bố đã đạt khi chưa đo. Phần cứng mô phỏng nằm trong phạm vi, không cần bịa số liệu barrier thật.

Các CSV prefilled cũ và benchmark chẩn đoán 12 ca chỉ dùng để phát hiện lỗi. Chưa có bộ nhãn người review độc lập đạt quy mô mục tiêu trong bản source hiện tại. Đây là phần bằng chứng thực nghiệm nhóm cần hoàn thành; phần mềm không tự bù bằng nhãn AI.
