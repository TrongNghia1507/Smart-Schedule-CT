"""Định nghĩa mẫu đánh giá lịch. Dùng chung cho biểu mẫu và trang admin."""
from __future__ import annotations

SATISFACTION_LABELS = {
    1: "1 · Rất không hài lòng",
    2: "2 · Không hài lòng",
    3: "3 · Trung lập",
    4: "4 · Hài lòng",
    5: "5 · Rất hài lòng",
}
NOT_APPLICABLE = "Không áp dụng"

IMPORTANCE_LABELS = {
    1: "1 · Không quan trọng",
    2: "2 · Ít quan trọng",
    3: "3 · Bình thường",
    4: "4 · Quan trọng",
    5: "5 · Rất quan trọng",
}

# Mỗi tiêu chí là một trục mục tiêu của biểu đồ Pareto trade-off khi xếp lịch.
CRITERIA = [
    dict(key="coverage", short="Độ phủ", title="Hoàn thành đủ công việc",
         question="Lịch xếp được đầy đủ các việc và thời lượng bạn cần làm trong tuần.",
         objective="Tối đa số việc / thời lượng được xếp"),
    dict(key="priority", short="Ưu tiên", title="Ưu tiên việc quan trọng",
         question="Việc bắt buộc và việc quan trọng cao được xếp chắc chắn, không bị hy sinh.",
         objective="Tối đa tổng điểm ưu tiên"),
    dict(key="timeliness", short="Đúng hạn", title="Đúng hạn và có dư địa",
         question="Việc xong trước hạn với khoảng dự phòng đủ an toàn nếu phát sinh.",
         objective="Hoàn thành sớm / tối thiểu trễ hạn"),
    dict(key="continuity", short="Liền mạch", title="Liền mạch, ít bị chia nhỏ",
         question="Mỗi việc được làm trong ít phiên, mỗi phiên đủ dài để tập trung.",
         objective="Tối thiểu số phiên (mảnh)"),
    dict(key="balance", short="Cân bằng", title="Cân bằng khối lượng và nghỉ ngơi",
         question="Khối lượng giữa các ngày hợp lý, có thời gian nghỉ, không dồn vào giờ quá sớm hoặc quá khuya.",
         objective="Tối thiểu chênh lệch tải / bảo đảm nghỉ"),
    dict(key="constraints", short="Giữ ràng buộc", title="Giữ nguyên ràng buộc cá nhân",
         question="Giờ ngủ, sự kiện cố định và thời lượng việc không bị cắt giảm quá mức để lịch khớp.",
         objective="Tối thiểu chi phí điều chỉnh ràng buộc"),
    dict(key="realism", short="Khả thi", title="Khả thi khi thực hiện",
         question="Bạn tin mình thực sự làm theo được lịch này trong thực tế.",
         objective="Mức độ thực tế của lịch"),
]

# Mỗi cặp đối đầu là một điểm đánh đổi (trade-off) giữa hai trục Pareto.
TRADEOFFS = [
    dict(key="coverage_vs_continuity",
         a="Xếp được nhiều việc hơn, dù mỗi việc bị chia thành nhiều phiên nhỏ",
         b="Mỗi việc làm liền mạch, dù có thể phải bỏ hoặc giảm bớt một vài việc"),
    dict(key="timeliness_vs_balance",
         a="Xong sớm, dư địa lớn, dù một số ngày bị dồn nặng",
         b="Tải đều mỗi ngày và nhiều thời gian nghỉ, dù sát hạn hơn"),
    dict(key="constraints_vs_coverage",
         a="Giữ nguyên giờ ngủ, sự kiện cố định và thời lượng, dù phải bỏ bớt việc",
         b="Chấp nhận nới giờ hoặc cắt giảm để xếp được nhiều việc hơn"),
    dict(key="priority_vs_balance",
         a="Việc quan trọng luôn được xếp trước, dù khối lượng dồn không đều",
         b="Phân bổ đều khối lượng, dù việc quan trọng có thể xếp muộn hơn"),
    dict(key="continuity_vs_timeliness",
         a="Làm liền mạch ít phiên, dù hoàn thành muộn hơn",
         b="Chia nhỏ thành nhiều phiên để hoàn thành sớm hơn"),
]
TRADEOFF_LABELS = {-2: "Hẳn A", -1: "Hơi nghiêng A", 0: "Cân bằng", 1: "Hơi nghiêng B", 2: "Hẳn B"}

ADOPTION_OPTIONS = [
    "Dùng nguyên như vậy",
    "Dùng sau khi chỉnh nhỏ (1–2 chỗ)",
    "Phải chỉnh nhiều (từ 3 chỗ)",
    "Sẽ không dùng lịch này",
]
VS_MANUAL_LABELS = {
    1: "Kém hơn nhiều",
    2: "Kém hơn một chút",
    3: "Tương đương",
    4: "Tốt hơn một chút",
    5: "Tốt hơn nhiều",
}
NO_BASELINE = "Tôi chưa từng tự xếp lịch tuần"

PROBLEMS = [
    "Việc quan trọng bị xếp muộn",
    "Quá nhiều phiên nhỏ lẻ",
    "Có ngày quá dày, thiếu nghỉ",
    "Phải làm quá khuya hoặc quá sớm",
    "Ràng buộc cá nhân bị thay đổi ngoài ý muốn",
    "Có việc bị bỏ hoặc bị giảm thời lượng",
    "Khoảng trống giữa các việc kém hợp lý",
    "Khó hiểu vì sao lịch được xếp như vậy",
    "Không có vấn đề đáng kể",
]
