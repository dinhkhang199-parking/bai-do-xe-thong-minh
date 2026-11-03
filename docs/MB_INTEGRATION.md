# Kết nối MB để đối soát phí gửi xe

Tích hợp dùng thư viện MBBank có trong thư mục API người dùng cung cấp.
Đây là thư viện không chính thức, phụ thuộc cơ chế đăng nhập MB hiện hành.
Luồng của ITS chỉ đăng nhập, lấy danh sách tài khoản VND và đọc lịch sử tiền vào.
Không cung cấp thao tác chuyển tiền, hoàn tiền hoặc mở barrier qua kết nối này.

## Bắt đầu

1. Đăng nhập ITS bằng quản trị viên, mở **Kết nối MB**.
2. Bấm **Kết nối MB**. Thông tin đăng nhập được đọc từ MB_PHONE / MB_PASSWORD
   trong file .env của thư mục API MB gốc. ITS không sao chép các giá trị này
   sang giao diện, database hoặc mã nguồn.
3. Chọn **Tự động bằng Ecaptcha** nếu đã có cấu hình dịch vụ, hoặc **Nhập tay**.
   Tự nhập CAPTCHA khi được yêu cầu. Nếu ngân hàng yêu cầu xác thực bổ sung, hoàn thành
   trong ứng dụng/ngân hàng; thư viện có thể chưa hỗ trợ cơ chế đó.
4. Chọn tài khoản VND được trả về trong phiên đăng nhập, bật tích hợp rồi lưu.
   Không dùng số tài khoản hardcode có sẵn trong bridge.py của bản mẫu.
5. Mở vé đã duyệt ra và có phí > 0. Chọn **Chuyển khoản MB · đối soát**,
   tạo mã và cho khách kiểm tra người nhận trước khi chuyển tiền.
6. Máy chủ kiểm tra nền khoảng mỗi 15 giây, kể cả đóng popup QR. Khi khớp, phiếu thu ghi
   **MB · đã đối soát** và mã giao dịch ngân hàng. Không cần xác nhận đã chuyển.

Biểu phí mẫu và tích hợp MB mặc định đều tắt. Không tự bật để thu tiền thật.
Kết nối ngân hàng và chọn tài khoản không tự kích hoạt biểu phí gửi xe.

## Điều kiện ghi nhận tiền

- Vé đã hoàn tất đối chiếu, chưa thu tiền và còn đúng báo giá.
- Tài khoản nhận và tiền tệ VND khớp.
- Khoản ghi có bằng chính xác số tiền; ghi nợ phải bằng 0.
- Nội dung có đúng mã ITS của yêu cầu và không có mã yêu cầu khác.
- Thời điểm giao dịch nằm trong hiệu lực mã (15 phút).
- Có mã giao dịch duy nhất, chưa dùng cho vé khác.
- Một khoản thu, sự kiện, chứng cứ đối soát và audit được lưu chung một
  transaction SQLite; gửi lặp hoặc nhiều nhân viên kiểm tra không thu trùng.

Thiếu/thừa tiền, sai nội dung, sai tài khoản, nhiều giao dịch cùng khớp,
không có mã tham chiếu hoặc lỗi mạng không được đánh dấu đã trả.
Mã hết hạn có thể kiểm tra lại để nhận ra giao dịch xảy ra trước hạn nhưng
hiển thị muộn. Nếu đã tạo mã mới hoặc khách chuyển sau hạn, nhân viên cần
đối chiếu thủ công trước khi yêu cầu khách chuyển thêm.
Hủy mã hoặc thu tiền mặt không tự hoàn tiền ngân hàng.

## Cách chạy dịch vụ

Worker mới dùng cổng 127.0.0.1:5051, không dùng/mở lại cổng 5050 của bản gốc.
Mọi yêu cầu vào worker phải có khóa chia sẻ, không bật CORS cho trình duyệt.
Web ITS gọi worker ở máy chủ; trình duyệt không biết khóa chia sẻ.
Chỉ khi quản trị viên bấm kết nối mới thực hiện đăng nhập ngân hàng.
CAPTCHA có hai chế độ: nhập tay hoặc Ecaptcha theo lựa chọn quản trị viên khi
kết nối. Khi có cấu hình Ecaptcha hợp lệ, giao diện chọn sẵn chế độ này theo yêu cầu của
chủ dự án; vẫn cần bấm Kết nối MB mới gửi yêu cầu. Chỉ gửi ảnh CAPTCHA đã bỏ
metadata và request_id, không gửi thông tin đăng nhập MB.
Mỗi lần kết nối chỉ gọi Ecaptcha một lần, không tự retry trừ hạn mức.
Dịch vụ lỗi/kết quả không hợp lệ chuyển sang nhập tay. Nếu MB trả đúng lỗi
CAPTCHA GW283 sau kết quả tự động, lấy một ảnh mới cho người dùng nhập tay.
Các lỗi mật khẩu/xác thực khác không được tự thử đăng nhập lặp lại.
QR chuyển khoản được tạo cục bộ theo cấu trúc VietQR/NAPAS, không gửi số tài
khoản, số tiền hoặc nội dung sang dịch vụ ảnh QR bên ngoài.

Đường dẫn thư mục nguồn ở .mb_bridge.json; khóa chia sẻ ở .mb_bridge_token.
Cả hai đã được loại khỏi Git. Thư mục nguồn MB và môi trường .venv314 cần được giữ.
start.bat gọi scripts/start_mb_bridge.py để mở worker nền; worker khởi động
ở trạng thái chưa đăng nhập, không tự gọi lịch sử giao dịch.

## Cấu hình Ecaptcha

Worker ưu tiên ECAPTCHA_URL và ECAPTCHA_TOKEN trong .env của thư mục API MB.
Nếu chưa có các khóa đó, worker đọc giá trị mặc định dạng chuỗi trong bridge.py
cũ bằng AST, không import/chạy file đó. Không sao chép token sang web hoặc database.
Đặt ECAPTCHA_TOKEN rỗng trong .env để tắt giá trị dự phòng từ mã cũ.
Chỉ chấp nhận HTTPS tới ecaptcha.shopcode.top, không theo redirect và không gửi
token trong URL. Phản hồi bị giới hạn kích thước/thời gian và phải có status=success,
captcha là 4–12 ký tự chữ/số. Thay đổi hợp đồng API cần cập nhật adapter tương ứng.

Lệnh cấu hình lại trên máy khác:

```powershell
python scripts/configure_mb_bridge.py --source DUONG_DAN_THU_MUC_API_MB
python scripts/start_mb_bridge.py
```

## Giới hạn xác minh

Kiểm thử bằng tài khoản/giao dịch/CAPTCHA giả, bao gồm các trường hợp sai tiền,
ghi nợ, sai tài khoản, sai nội dung, quá hạn, replay và cạnh tranh thu tiền.
Chưa xác minh phiên đăng nhập hoặc chuyển khoản MB thật trong quá trình phát triển.
Mã ngân hàng MB 970422 được đối chiếu với danh mục công khai của VietQR:
https://api.vietqr.io/v2/banks

Thư viện nguồn: MBBank/pyproject.toml trong thư mục API được cung cấp;
homepage khai báo https://github.com/thedtvn/MBBank (MIT).
