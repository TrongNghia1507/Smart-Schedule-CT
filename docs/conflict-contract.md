# Hợp đồng module Conflict

## Input

- Các mốc thời gian là phút nguyên từ đầu tuần.
- Caller chịu trách nhiệm chuyển timezone và bung fixed task lặp.
- importance: 1–3.
- remaining_min: phần công việc chưa thực hiện.
- active_windows: các khoảng hoạt động không chồng lấn.
- Fixed task và các khoảng khóa phải được validator chung kiểm tra trước.
- Không xếp công việc trước now_minute.

## Quy ước demo

- Sắp xếp lại toàn bộ công việc linh hoạt tương lai.
- Buffer nằm sau mỗi chunk, kể cả chunk cuối.
- Không dời deadline hard/asap.
- Chỉ giảm thời lượng hoặc bỏ task khi có quyền tương ứng.
- Không sửa input hoặc lưu lịch gốc.

## Output

- Bốn options khi có conflict.
- is_available chỉ true khi engine xếp được toàn bộ task còn giữ.
- factual_description là mô tả do code tạo.
- ai_description là phần giải thích AI hoặc fallback.
- preview là lịch xem trước.
- schedule_version được chuyển tiếp để backend chung kiểm tra khi áp dụng.
- deficit_minutes là tổng phút chưa xếp trong lần chạy cơ sở.

## Tích hợp engine

Thay ReferenceScheduler trong api.py bằng adapter có:

- name
- plan(context) -> PlanResult

FEASIBLE chỉ được trả khi mọi ràng buộc được hỗ trợ đều thỏa mãn.
NOT_FOUND không tự động đồng nghĩa với vô nghiệm.

## Áp dụng lựa chọn

Backend chung cần:

1. Lưu report và payload ở server.
2. Nhận conflict_id, option_id và schedule_version từ frontend.
3. Kiểm tra phiên bản và quyền thay đổi.
4. Chạy lại engine trên dữ liệu mới nhất.
5. Lưu thay đổi cùng lịch mới trong một transaction.
6. Tăng version và trả updated plan.

Không tin action_payload tùy ý do frontend gửi lên.