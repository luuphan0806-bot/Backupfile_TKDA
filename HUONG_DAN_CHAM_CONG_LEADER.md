# Hướng dẫn chấm công & Leader Workbench

Tài liệu này giải thích luồng **chấm công có bước Leader duyệt** được bổ sung từ phiên bản schema DB v7. Đây là thay đổi quan trọng về cách tính sản lượng và xuất báo cáo, **cần đọc trước khi nâng cấp môi trường đang chạy**.

## 1. Vì sao báo cáo/thống kê có thể trống

> **Kể từ v7, Thống kê và báo cáo chấm công chỉ tính những dòng công đã được Leader DUYỆT (APPROVED).**

Sau khi nâng cấp, nếu Leader chưa duyệt công ngày nào thì:

- Tab **Thống kê** không hiển thị số liệu ngày đó.
- File `attendance_report_*.xlsx` (sheet `Cham cong`, `Tong hop`) sẽ trống cho ngày đó.

Đây **không phải mất dữ liệu**. Toàn bộ việc đã giao vẫn nằm trong hệ thống ở trạng thái **Chờ duyệt (PENDING)** và hiện đầy đủ trong tab **Leader Workbench** cũng như sheet `San luong tho` của báo cáo. Số liệu sẽ xuất hiện ngay khi Leader duyệt.

## 2. Luồng vận hành đầy đủ

```
Giao việc (Scan/Check)  →  Nhân sự làm & chốt việc (COMPLETED)
        →  Backup file (SCAN) / Nghiệm thu check (CHECK)
        →  Leader Workbench: Duyệt / Override / Không tính công
        →  Thống kê & Báo cáo chấm công
```

Mỗi lần giao việc sinh ra một **dòng chấm công** (attendance entry) tương ứng với nhân sự + hồ sơ + ngày công. Dòng này tự đồng bộ theo trạng thái task; Leader là người chốt cuối cùng.

## 3. Tab Leader Workbench

Mở **Bảng điều hành dự án → Leader Workbench**. Chọn **Ngày công** rồi bấm **Xem ngày**.

### Các chỉ số (KPI)

| Chỉ số | Ý nghĩa |
|---|---|
| Chờ duyệt | Số dòng đang PENDING |
| Đủ điều kiện | Dòng PENDING đã hội đủ điều kiện, có thể duyệt ngay |
| Đã duyệt | Dòng APPROVED (đã vào thống kê) |
| Không tính | Dòng REJECTED/VOID |

### Cột "Nghiệm thu" và điều kiện đủ

- **SCAN**: đủ điều kiện khi task đã chốt hoàn thành **và** hồ sơ đã có **file backup hợp lệ**.
- **CHECK**: đủ điều kiện khi hồ sơ có workflow ở trạng thái **COMPLETED** và có **số trang/số file check** > 0.

### 3 hành động của Leader

1. **Duyệt** (biểu tượng ✓): chỉ thành công khi dòng **đủ điều kiện**. Ghi nhận sản lượng vào thống kê.
2. **Duyệt override** (biểu tượng ghi chú): dùng khi cần tính công dù **chưa đủ điều kiện tự động** (ví dụ file nguồn hợp lệ nhưng chưa backup kịp). **Bắt buộc nhập lý do**; có thể chỉnh **sản lượng tính công** và **số đã chốt**.
3. **Không tính công** (biểu tượng chặn): loại dòng khỏi bảng công. **Bắt buộc nhập lý do**.

Nút **Duyệt dòng đủ điều kiện** ở đầu trang duyệt hàng loạt tất cả dòng đang ở trạng thái "Đủ điều kiện".

> Mọi thao tác Duyệt / Override / Không tính công đều được **ghi audit** và hiển thị trong sheet `Audit chinh sua` của báo cáo.

## 4. Báo cáo chấm công (5 sheet)

File `attendance_report_<từ ngày>_<đến ngày>_*.xlsx`:

| Sheet | Nội dung |
|---|---|
| `Cham cong` | Chi tiết công **đã duyệt** theo ngày/nhân sự |
| `Tong hop` | Tổng hợp theo ngày và nhân sự |
| `San luong tho` | **Toàn bộ** dòng công (mọi trạng thái) để đối chiếu |
| `Ngoai le` | Dòng cần chú ý: chưa duyệt, có override, hoặc SCAN thiếu backup / CHECK chưa COMPLETED |
| `Audit chinh sua` | Nhật ký duyệt/loại/xuất báo cáo trong kỳ |

Khi nghiệm thu, đối chiếu `Tong hop` (số chính thức) với `Ngoai le` (các trường hợp Leader đã can thiệp) để đảm bảo minh bạch.

## 5. Lưu ý khi nâng cấp môi trường đang chạy (migration v7)

Lần đầu mở DB cũ bằng bản mới, hệ thống tự động (idempotent, an toàn chạy lại):

- Thêm cột chấm công vào bảng task và tạo bảng `attendance_entries`.
- **Backfill** mỗi task hiện có thành một dòng chấm công:
  - task `COMPLETED` → `completed_count = 1`.
  - task `CANCELLED` → trạng thái `VOID`.
  - còn lại → `PENDING` (chờ Leader duyệt).

Vì vậy, **ngay sau khi nâng cấp, hãy vào Leader Workbench duyệt lại các ngày công cần xuất báo cáo** trước khi bàn giao số liệu. Hãy thông báo cho bộ phận vận hành/kế toán về bước duyệt mới này để tránh hiểu nhầm "báo cáo trống = mất dữ liệu".

## 6. Câu hỏi thường gặp

- **Thống kê trống dù đã giao việc?** → Chưa duyệt công. Vào Leader Workbench duyệt.
- **Không duyệt được một dòng SCAN?** → Hồ sơ chưa có file backup hợp lệ. Chạy backup hồ sơ, hoặc dùng **Override** kèm lý do.
- **Đã đổi mã hồ sơ (rename) thì công có bị lạc không?** → Không. Dòng chấm công được đồng bộ theo mã hồ sơ mới.
- **Lỡ duyệt sai?** → Dòng đã APPROVED không tự động đổi lại khi task thay đổi; cần xử lý thủ công/ghi nhận qua audit theo quy trình nội bộ.
