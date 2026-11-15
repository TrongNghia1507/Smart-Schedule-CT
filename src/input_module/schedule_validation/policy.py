"""Điều kiện sinh phương án cho resolver.

Người dùng KHÔNG chọn trước các cờ allow_exclude / allow_compress / max_postpone.
Họ chỉ chọn lúc có xung đột, trên danh sách phương án resolver đưa ra. Vì vậy mặc
định ở đây cho phép mọi loại phương án với mọi task; phương án nào dùng được do
kiểm tra ngữ cảnh + engine kiểm chứng của resolver quyết định. Có thể thu hẹp
bằng `rules` / `overrides` nếu sau này muốn cấm cứng một loại phương án.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KindRule:
    allow_compress: bool        # option 2: rút gọn thời lượng chính task
    allow_exclude: bool         # option 1: gỡ task khỏi tuần
    allow_postpone: bool        # option 3: dời hạn chót của chính task
    min_keep_ratio: float = 0.5  # rút gọn tối đa còn bao nhiêu % thời lượng


def _default_rules():
    # min_keep_ratio=0: rút gọn không bị chặn sàn tự đặt; resolver tự tìm mức rút
    # nhỏ nhất đủ chạy, sàn chỉ còn là một chunk_min.
    rule = KindRule(allow_compress=True, allow_exclude=True, allow_postpone=True, min_keep_ratio=0.0)
    return {"soft": rule, "asap": rule, "hard": rule}


@dataclass(frozen=True)
class ResolutionPolicy:
    rules: dict = field(default_factory=_default_rules)
    overrides: dict = field(default_factory=dict)  # task_id -> KindRule

    # Việc cố định có is_flexible (min < full) mới được rút ngắn (option 4).
    # Resolver chỉ rút ngắn fixed có importance < importance của target.
    shortenable_fixed_importance: int = 1
    rigid_fixed_importance: int = 3

    compression_step_minutes: int = 15

    # Mượn giờ ngủ (mở rộng khung hoạt động) tối đa mỗi phía; 0 = tắt. Tối đa 60.
    max_earlier_minutes: int = 30
    max_later_minutes: int = 30

    # Deadline nằm sau tuần lập lịch: "clamp" (tính như phải xong trong tuần)
    # hoặc "skip" (không tính vào tuần này).
    out_of_week_deadline: str = "clamp"

    def rule_for(self, task_id, kind):
        return self.overrides.get(task_id) or self.rules[kind]
