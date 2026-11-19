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
- Task bắt buộc (mandatory): không bỏ khỏi tuần, không dời deadline.
- Task không bắt buộc: deadline cố định là hết Chủ nhật, được bỏ khỏi tuần.
- Chỉ giảm thời lượng hoặc bỏ task khi có quyền tương ứng.
- Không sửa input hoặc lưu lịch gốc.

## Output

- Ba options khi có conflict: bỏ khỏi tuần, giảm thời lượng, nới ràng buộc.
- is_available chỉ true khi engine xếp được toàn bộ task còn giữ.
- factual_description là mô tả do code tạo.
- ai_description là phần giải thích AI hoặc fallback.
- preview là lịch xem trước.
- schedule_version được chuyển tiếp để backend chung kiểm tra khi áp dụng.
- deficit_minutes là số phút target không xếp được khi giữ nguyên các task còn lại
  (thời lượng yêu cầu trừ số phút lớn nhất còn xếp được).

## Option 3: nới ràng buộc

Chỉ có hai loại thay đổi, đều phải do người dùng chọn:

1. **REMOVE_FIXED** – xóa hẳn một lần diễn ra của sự kiện cố định (cùng thời
   gian chuẩn bị/đi về của nó). Không bao giờ rút ngắn sự kiện.
   - Chỉ xóa sự kiện có `can_remove = true` (cột "Xóa được khi bận" ở Input).
   - Chỉ xóa lần diễn ra chưa bắt đầu và bắt đầu trước deadline của target
     (ngày deadline và các ngày trước đó).
2. **EXPAND_ACTIVE_WINDOW** – dậy sớm hơn (`earlier_minutes`) hoặc thức
   muộn hơn (`later_minutes`), tối đa `max_earlier_minutes` /
   `max_later_minutes` mỗi khung giờ. Chỉ nới các ngày không sau ngày
   deadline; ở ngày deadline không thức quá giờ deadline.
   Giá mỗi phút = `sleep_cost_per_minute + sleep_tier_step_cost × số ngày
   cách ngày deadline`, nên solver nới sát deadline trước: dậy sớm ngày
   deadline, rồi mới đến thức khuya/dậy sớm ngày hôm trước, v.v.

Solver chọn tổ hợp rẻ nhất: giá xóa = `remove_cost_per_minute × số phút bị
xóa`, cộng `event_touch_penalty` cho mỗi lần diễn ra bị xóa/mỗi đêm bị đụng.

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