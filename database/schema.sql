-- ============================================================================
-- SMART SCHEDULE CT - DATABASE SCHEMA (HƯỚNG 1: STREAMLIT + PYTHON BACKEND + MYSQL)
-- Tương thích: MySQL 8.0+ / MariaDB 10.4+ / TiDB Cloud Starter (Serverless Free)
--
-- RANH GIỚI ĐỌC / GHI GIỮA NHÓM FRONTEND (UI) VÀ NGƯỜI LÀM BACKEND:
--   1. Dữ liệu ĐẦU VÀO do tầng UI thu thập (ghi qua AuthRepo / MySQLTaskRepository / FeedbackRepo):
--        users, user_week_settings, fixed_tasks, deadline_tasks, feedbacks
--   2. Dữ liệu KẾT QUẢ do Backend tính toán từ CP-SAT & AI rồi GHI VÀO:
--        schedules, schedule_blocks, conflict_options, schedule_histories
--   3. Tầng UI ĐỌC từ 4 bảng kết quả trên (luôn kèm WHERE user_id = ...) để hiển thị lịch,
--      3 phương án gỡ xung đột, và lịch sử các tuần.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS smart_schedule_ct
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE smart_schedule_ct;

-- ----------------------------------------------------------------------------
-- 1. NGƯỜI DÙNG (Tách biệt hoàn toàn không gian dữ liệu từng người qua user_id)
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(100) NOT NULL UNIQUE,          -- MSSV / Email / Tên đăng nhập
    password_hash   VARCHAR(255) NOT NULL,                 -- scrypt / bcrypt hash (không lưu plain text)
    full_name       VARCHAR(120) NOT NULL DEFAULT '',      -- Họ tên hiển thị trên React Web & Admin
    display_name    VARCHAR(120) DEFAULT NULL,             -- Tương thích ngược với auth_service
    email           VARCHAR(255) DEFAULT NULL,
    user_group      VARCHAR(80) DEFAULT NULL,              -- 'Sinh viên', 'Nhân viên văn phòng', ...
    role_group      ENUM('student', 'worker', 'other') NOT NULL DEFAULT 'student',
    role            VARCHAR(16) NOT NULL DEFAULT 'user',   -- 'user' hoặc 'admin'
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until    VARCHAR(40) DEFAULT NULL,
    created_at      VARCHAR(40) NOT NULL,                  -- Chuỗi ISO UTC (VD: '2026-11-26T15:00:00+00:00')
    last_login_at   VARCHAR(40) DEFAULT NULL,
    login_count     INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 2. THIẾT LẬP TUẦN & GIỜ NGỦ (1 dòng cho mỗi cặp user_id + week_start)
-- ----------------------------------------------------------------------------
CREATE TABLE user_week_settings (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         INT UNSIGNED NOT NULL,
    week_start      DATE NOT NULL,                         -- BẮT BUỘC là ngày Thứ Hai (VD: '2026-11-30')
    sleep_start     CHAR(5) NOT NULL DEFAULT '23:00',      -- 'HH:mm' (00:00 -> 23:59)
    sleep_end       CHAR(5) NOT NULL DEFAULT '06:30',      -- 'HH:mm' (00:00 -> 24:00)
    max_earlier_min TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- Cho phép dậy sớm tối đa 0..60 phút (Option 3)
    max_later_min   TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- Cho phép ngủ muộn tối đa 0..60 phút (Option 3)
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_user_week (user_id, week_start),
    CONSTRAINT fk_settings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT chk_earlier CHECK (max_earlier_min <= 60),
    CONSTRAINT chk_later   CHECK (max_later_min <= 60)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 3. VIỆC CỐ ĐỊNH - FIXED TASKS
--    - Lặp hằng tuần : repeat_days = 'mon,wed,fri', one_off_date = NULL
--    - Một ngày cụ thể: repeat_days = NULL, one_off_date = '2026-12-02'
-- ----------------------------------------------------------------------------
CREATE TABLE fixed_tasks (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id             INT UNSIGNED NOT NULL,
    week_start          DATE NOT NULL,
    task_code           VARCHAR(32) NOT NULL,              -- 'ft_' + 8 ký tự hex (giống uid(True) của lõi cũ)
    name                VARCHAR(100) NOT NULL,
    repeat_days         VARCHAR(35) DEFAULT NULL,          -- tập con của: mon,tue,wed,thu,fri,sat,sun
    one_off_date        DATE DEFAULT NULL,
    start_time          CHAR(5) NOT NULL,                  -- 'HH:mm' (00:00 -> 23:59)
    end_time            CHAR(5) NOT NULL,                  -- 'HH:mm' (00:00 -> 24:00), < start_time = qua đêm
    prep_min            TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- Chuẩn bị/di chuyển trước (0..90 phút)
    after_min           TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- Đi về/dự trù sau (0..60 phút)
    removable_when_busy TINYINT(1) NOT NULL DEFAULT 0,     -- 1 = Option 3 được phép xóa lần diễn ra này
    display_color       CHAR(7) DEFAULT NULL,              -- '#499ed0' (thay cho calendar_colors.json cũ)
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_fixed_code (user_id, week_start, task_code),
    INDEX idx_fixed_lookup (user_id, week_start),
    CONSTRAINT fk_fixed_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT chk_fixed_repeat_or_date CHECK (
        (repeat_days IS NOT NULL AND one_off_date IS NULL)
        OR (repeat_days IS NULL AND one_off_date IS NOT NULL)
    ),
    CONSTRAINT chk_prep_min  CHECK (prep_min <= 90),
    CONSTRAINT chk_after_min CHECK (after_min <= 60)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 4. VIỆC CÓ HẠN CHÓT - DEADLINE TASKS
-- ----------------------------------------------------------------------------
CREATE TABLE deadline_tasks (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         INT UNSIGNED NOT NULL,
    week_start      DATE NOT NULL,
    task_code       VARCHAR(32) NOT NULL,                  -- 'dt_' + 8 ký tự hex (giống uid(False) của lõi cũ)
    name            VARCHAR(100) NOT NULL,
    mandatory       TINYINT(1) NOT NULL DEFAULT 1,         -- 1 = Bắt buộc, 0 = Không bắt buộc (hạn hết Chủ nhật)
    importance      TINYINT UNSIGNED NOT NULL DEFAULT 2,   -- 1, 2, hoặc 3
    deadline        DATETIME NOT NULL,                     -- 'YYYY-MM-DD HH:mm:00' theo giờ Việt Nam
    remaining_min   SMALLINT UNSIGNED NOT NULL,            -- Tổng thời lượng cần làm (phút, > 0)
    focus           ENUM('high', 'low') NOT NULL DEFAULT 'high',
    buffer_min      TINYINT UNSIGNED NOT NULL DEFAULT 15,  -- 0..60, chia hết cho 5
    earliest_start  DATETIME DEFAULT NULL,                 -- NULL = có thể bắt đầu ngay từ thời điểm hiện tại
    chunk_min       SMALLINT UNSIGNED NOT NULL DEFAULT 45,
    chunk_max       SMALLINT UNSIGNED NOT NULL DEFAULT 90,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_deadline_code (user_id, week_start, task_code),
    INDEX idx_deadline_lookup (user_id, week_start),
    CONSTRAINT fk_deadline_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT chk_importance   CHECK (importance BETWEEN 1 AND 3),
    CONSTRAINT chk_remaining    CHECK (remaining_min > 0 AND remaining_min <= 10080),
    CONSTRAINT chk_buffer       CHECK (buffer_min <= 60 AND MOD(buffer_min, 5) = 0),
    CONSTRAINT chk_chunk_range  CHECK (chunk_min > 0 AND chunk_max >= chunk_min)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 5. KẾT QUẢ CHẠY XẾP LỊCH (1 dòng tổng kết cho mỗi lần chạy CP-SAT / Apply Option)
-- ----------------------------------------------------------------------------
CREATE TABLE schedules (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id             INT UNSIGNED NOT NULL,
    parent_schedule_id  INT UNSIGNED DEFAULT NULL,         -- Trỏ về lịch cha bị kẹt (NULL nếu là lần chạy gốc)
    week_start          DATE NOT NULL,
    schedule_version    INT UNSIGNED NOT NULL DEFAULT 0,   -- Số bước đã áp dụng conflict (0, 1, 2...)
    status              ENUM('FEASIBLE', 'NOT_FOUND') NOT NULL,
    proven_optimal      TINYINT(1) NOT NULL DEFAULT 0,     -- 1 nếu CP-SAT trả OPTIMAL
    creation_source     ENUM('cp_sat', 'conflict_option') NOT NULL DEFAULT 'cp_sat',
    applied_option_id   TINYINT UNSIGNED DEFAULT NULL,     -- NULL hoặc 1 (Bỏ task) / 2 (Giảm giờ) / 3 (Nới)
    total_tasks         SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    scheduled_tasks     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    unscheduled_tasks   SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    unscheduled_json    TEXT DEFAULT NULL,                 -- [{task_code, name, missing_minutes, mandatory, importance}]
    input_hash          CHAR(64) DEFAULT NULL,             -- SHA-256 dữ liệu nhập lúc xếp (phát hiện nếu user sửa task)
    solver_state_json   LONGTEXT NOT NULL,                 -- Nội bộ Backend: trạng thái PlanningSession (xem docs/02)
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_schedule_user_week (user_id, week_start),
    CONSTRAINT fk_schedules_user   FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_schedules_parent FOREIGN KEY (parent_schedule_id) REFERENCES schedules(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 6. CÁC KHỐI THỜI GIAN TRÊN LỊCH (Chi tiết ~20-40 ô giờ của 1 bản lịch ở Bảng 5)
-- ----------------------------------------------------------------------------
CREATE TABLE schedule_blocks (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    schedule_id     INT UNSIGNED NOT NULL,
    block_kind      ENUM('deadline', 'fixed', 'reserve', 'sleep') NOT NULL,
    ref_task_code   VARCHAR(32) DEFAULT NULL,              -- task_code gốc (NULL với khối ngủ / nghỉ ngơi)
    title           VARCHAR(200) NOT NULL,                 -- '③ Làm đồ án CT (1/3)', 'Nghỉ ngơi · ...'
    start_datetime  DATETIME NOT NULL,
    end_datetime    DATETIME NOT NULL,
    bg_color        CHAR(7) NOT NULL DEFAULT '#499ed0',
    text_color      CHAR(7) NOT NULL DEFAULT '#ffffff',

    INDEX idx_blocks_schedule (schedule_id, start_datetime),
    CONSTRAINT fk_blocks_schedule FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 7. PHƯƠNG ÁN XỬ LÝ CONFLICT (Lưu cả 3 Option đề xuất LẪN lựa chọn của User)
-- ----------------------------------------------------------------------------
CREATE TABLE conflict_options (
    id                      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    schedule_id             INT UNSIGNED NOT NULL,         -- Thuộc lịch đang bị NOT_FOUND ở Bảng 5
    target_task_code        VARCHAR(32) NOT NULL,          -- Task chưa xếp được (VD: 'dt_02')
    target_task_name        VARCHAR(100) NOT NULL,
    deficit_min             SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    option_code             TINYINT UNSIGNED NOT NULL,     -- 1 = Bỏ task, 2 = Giảm thời lượng, 3 = Nới ràng buộc
    priority_rank           TINYINT UNSIGNED NOT NULL DEFAULT 1, -- Thứ tự ưu tiên 1..3
    is_available            TINYINT(1) NOT NULL DEFAULT 0, -- 1 = Đã được CP-SAT kiểm chứng khả thi
    unavailable_reason      VARCHAR(255) DEFAULT NULL,
    changes_summary         TEXT NOT NULL,                 -- Các dòng từ describe_changes() nối bằng '\n'
    max_new_duration_min    SMALLINT UNSIGNED DEFAULT NULL,-- Option 2: mức thời lượng tối đa cho thanh trượt
    action_payload_json     LONGTEXT DEFAULT NULL,         -- Payload gốc của Engine
    preview_blocks_json     LONGTEXT DEFAULT NULL,         -- Mảng khối lịch xem trước của Option này
    warnings_json           TEXT DEFAULT NULL,             -- Cảnh báo đánh đổi
    unplaced_json           TEXT DEFAULT NULL,             -- Các task khác vẫn chưa xếp được

    -- Cập nhật khi người dùng chọn áp dụng Option này:
    is_selected             TINYINT(1) NOT NULL DEFAULT 0,
    chosen_duration_min     SMALLINT UNSIGNED DEFAULT NULL,
    resulting_schedule_id   INT UNSIGNED DEFAULT NULL,     -- Lịch mới sinh ra ở Bảng 5
    selected_at             DATETIME DEFAULT NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_conflict_option (schedule_id, target_task_code, option_code),
    INDEX idx_conflict_lookup (schedule_id, target_task_code, priority_rank),
    CONSTRAINT fk_conflict_schedule FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
    CONSTRAINT fk_conflict_result   FOREIGN KEY (resulting_schedule_id) REFERENCES schedules(id) ON DELETE SET NULL,
    CONSTRAINT chk_option_code      CHECK (option_code BETWEEN 1 AND 3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 8. LỊCH SỬ PHIÊN BẢN ĐÃ LƯU (Thay thế hoàn toàn schedule_history.json)
--    Đóng băng độc lập theo từng user_id -> xóa nháp ở bảng 3, 4 không ảnh hưởng History!
-- ----------------------------------------------------------------------------
CREATE TABLE schedule_histories (
    id                      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    history_uuid            CHAR(36) NOT NULL UNIQUE,
    user_id                 INT UNSIGNED NOT NULL,
    schedule_id             INT UNSIGNED NOT NULL,
    week_start              DATE NOT NULL,
    week_end                DATE NOT NULL,
    version                 INT UNSIGNED NOT NULL,         -- 1, 2, 3... tăng dần theo (user_id, week_start)
    title                   VARCHAR(200) NOT NULL,         -- 'Lịch 30/11/2026 – 06/12/2026 · Phiên bản 1'
    description             TEXT NOT NULL,
    save_source             ENUM('manual_save', 'conflict_option') NOT NULL,
    creation_method         ENUM('cp_sat', 'conflict_options', 'conflict_options_unknown') NOT NULL DEFAULT 'cp_sat',
    is_complete             TINYINT(1) NOT NULL DEFAULT 1,
    applied_options_json    LONGTEXT DEFAULT NULL,         -- Các Option đã áp dụng dẫn tới phiên bản này
    input_snapshot_json     LONGTEXT DEFAULT NULL,         -- Dữ liệu NHẬP đóng băng: {settings, fixed_tasks, deadline_tasks} để khôi phục
    frozen_record_json      LONGTEXT NOT NULL,             -- Bản đóng băng đầy đủ (context + result) để tải JSON
    user_note               VARCHAR(255) DEFAULT NULL,     -- Ghi chú của người dùng cho phiên bản này
    is_pinned               TINYINT(1) NOT NULL DEFAULT 0, -- 1 = ghim lên đầu danh sách lịch sử
    saved_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_user_week_version (user_id, week_start, version),
    INDEX idx_history_browse (user_id, week_start, version),
    CONSTRAINT fk_history_user     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_history_schedule FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ----------------------------------------------------------------------------
-- 9. ĐÁNH GIÁ LỊCH VỪA CHỐT - 4 PHẦN A, B, C, D (Phục vụ xuất CSV làm báo cáo đồ án)
--    + Phần A (7 tiêu chí): sat_* nhận 1..5 hoặc NULL ("Không áp dụng"); imp_* bắt buộc 1..5
--    + Phần B (5 cặp đánh đổi): 1=Hẳn A, 2=Hơi nghiêng A, 3=Cân bằng, 4=Hơi nghiêng B, 5=Hẳn B
--    + Phần C (Đánh giá chung): hài lòng tổng thể 1..5, cách dùng, so với tự xếp, NPS 0..10, rõ ràng conflict 1..5/NULL
--    + Phần D (Vấn đề & góp ý): mảng JSON các tag vấn đề + 2 câu tự luận mở (không bắt buộc)
-- ----------------------------------------------------------------------------
CREATE TABLE feedbacks (
    id                      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id                 INT UNSIGNED NOT NULL,
    schedule_id             INT UNSIGNED NOT NULL,
    history_id              INT UNSIGNED DEFAULT NULL,
    system_metrics_json     LONGTEXT DEFAULT NULL,         -- Snapshot chỉ số "Hệ thống đo được" lúc chấm (8/8 việc, 29 phiên...)

    -- === PHẦN A: Chấm điểm theo 7 tiêu chí (Mức hài lòng 1..5 hoặc NULL = Không áp dụng | Mức quan trọng 1..5) ===
    sat_coverage            TINYINT UNSIGNED DEFAULT NULL, -- 1. Hoàn thành đủ công việc (Độ phủ)
    imp_coverage            TINYINT UNSIGNED NOT NULL,
    sat_priority            TINYINT UNSIGNED DEFAULT NULL, -- 2. Ưu tiên việc quan trọng (Ưu tiên)
    imp_priority            TINYINT UNSIGNED NOT NULL,
    sat_deadline            TINYINT UNSIGNED DEFAULT NULL, -- 3. Đúng hạn và có dư địa (Đúng hạn)
    imp_deadline            TINYINT UNSIGNED NOT NULL,
    sat_continuity          TINYINT UNSIGNED DEFAULT NULL, -- 4. Liền mạch, ít bị chia nhỏ (Liền mạch)
    imp_continuity          TINYINT UNSIGNED NOT NULL,
    sat_balance             TINYINT UNSIGNED DEFAULT NULL, -- 5. Cân bằng khối lượng và nghỉ ngơi (Cân bằng)
    imp_balance             TINYINT UNSIGNED NOT NULL,
    sat_constraints         TINYINT UNSIGNED DEFAULT NULL, -- 6. Giữ nguyên ràng buộc cá nhân (Giữ ràng buộc)
    imp_constraints         TINYINT UNSIGNED NOT NULL,
    sat_feasibility         TINYINT UNSIGNED DEFAULT NULL, -- 7. Khả thi khi thực hiện (Khả thi)
    imp_feasibility         TINYINT UNSIGNED NOT NULL,

    -- === PHẦN B: 5 cặp đánh đổi (1 = Hẳn A, 2 = Hơi nghiêng A, 3 = Cân bằng, 4 = Hơi nghiêng B, 5 = Hẳn B) ===
    tradeoff_pair_1         TINYINT UNSIGNED NOT NULL,     -- A: Xếp nhiều việc hơn dù chia nhỏ vs B: Làm liền mạch dù bỏ/giảm việc
    tradeoff_pair_2         TINYINT UNSIGNED NOT NULL,     -- A: Xong sớm dư địa lớn dù dồn ngày vs B: Tải đều nhiều nghỉ dù sát hạn
    tradeoff_pair_3         TINYINT UNSIGNED NOT NULL,     -- A: Giữ nguyên ngủ/cố định dù bỏ việc vs B: Nới giờ/cắt giảm để xếp nhiều hơn
    tradeoff_pair_4         TINYINT UNSIGNED NOT NULL,     -- A: Việc quan trọng xếp trước dù dồn vs B: Phân bổ đều dù việc quan trọng muộn hơn
    tradeoff_pair_5         TINYINT UNSIGNED NOT NULL,     -- A: Liền mạch ít phiên dù xong muộn vs B: Chia nhỏ nhiều phiên để xong sớm

    -- === PHẦN C: Đánh giá chung ===
    overall_satisfaction    TINYINT UNSIGNED NOT NULL,     -- 1..5: Rất không hài lòng -> Rất hài lòng
    usage_intent            ENUM(
                                'use_as_is',               -- Dùng nguyên như vậy
                                'minor_edits',             -- Dùng sau khi chỉnh nhỏ (1–2 chỗ)
                                'major_edits',             -- Phải chỉnh nhiều (từ 3 chỗ)
                                'wont_use'                 -- Sẽ không dùng lịch này
                            ) NOT NULL,
    vs_self_scheduling      ENUM(
                                'much_worse',              -- Kém hơn nhiều
                                'slightly_worse',          -- Kém hơn một chút
                                'similar',                 -- Tương đương
                                'slightly_better',         -- Tốt hơn một chút
                                'much_better',             -- Tốt hơn nhiều
                                'never_self_scheduled'     -- Tôi chưa từng tự xếp lịch tuần
                            ) NOT NULL,
    nps_score               TINYINT UNSIGNED NOT NULL,     -- 0..10: Khả năng giới thiệu công cụ cho người khác
    conflict_clarity_score  TINYINT UNSIGNED DEFAULT NULL, -- 1..5 (NULL nếu lịch không phát sinh xung đột)

    -- === PHẦN D: Vấn đề gặp phải và góp ý tự do ===
    reported_issues_json    TEXT NOT NULL,                 -- Mảng JSON các tag vấn đề đã chọn (VD: '["too_many_small_chunks"]')
    best_aspect             TEXT DEFAULT NULL,             -- Điều làm bạn hài lòng nhất (không bắt buộc)
    needs_improvement       TEXT DEFAULT NULL,             -- Điều cần cải thiện nhất (không bắt buộc)

    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_user_schedule_feedback (user_id, schedule_id),
    CONSTRAINT fk_feedback_user     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_feedback_schedule FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE,
    CONSTRAINT fk_feedback_history  FOREIGN KEY (history_id) REFERENCES schedule_histories(id) ON DELETE SET NULL,

    CONSTRAINT chk_sat_coverage     CHECK (sat_coverage    IS NULL OR (sat_coverage    BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_coverage     CHECK (imp_coverage    BETWEEN 1 AND 5),
    CONSTRAINT chk_sat_priority     CHECK (sat_priority    IS NULL OR (sat_priority    BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_priority     CHECK (imp_priority    BETWEEN 1 AND 5),
    CONSTRAINT chk_sat_deadline     CHECK (sat_deadline    IS NULL OR (sat_deadline    BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_deadline     CHECK (imp_deadline    BETWEEN 1 AND 5),
    CONSTRAINT chk_sat_continuity   CHECK (sat_continuity  IS NULL OR (sat_continuity  BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_continuity   CHECK (imp_continuity  BETWEEN 1 AND 5),
    CONSTRAINT chk_sat_balance      CHECK (sat_balance     IS NULL OR (sat_balance     BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_balance      CHECK (imp_balance     BETWEEN 1 AND 5),
    CONSTRAINT chk_sat_constraints  CHECK (sat_constraints IS NULL OR (sat_constraints BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_constraints  CHECK (imp_constraints BETWEEN 1 AND 5),
    CONSTRAINT chk_sat_feasibility  CHECK (sat_feasibility IS NULL OR (sat_feasibility BETWEEN 1 AND 5)),
    CONSTRAINT chk_imp_feasibility  CHECK (imp_feasibility BETWEEN 1 AND 5),

    CONSTRAINT chk_tradeoff_1       CHECK (tradeoff_pair_1 BETWEEN 1 AND 5),
    CONSTRAINT chk_tradeoff_2       CHECK (tradeoff_pair_2 BETWEEN 1 AND 5),
    CONSTRAINT chk_tradeoff_3       CHECK (tradeoff_pair_3 BETWEEN 1 AND 5),
    CONSTRAINT chk_tradeoff_4       CHECK (tradeoff_pair_4 BETWEEN 1 AND 5),
    CONSTRAINT chk_tradeoff_5       CHECK (tradeoff_pair_5 BETWEEN 1 AND 5),

    CONSTRAINT chk_overall_sat      CHECK (overall_satisfaction BETWEEN 1 AND 5),
    CONSTRAINT chk_nps_score        CHECK (nps_score BETWEEN 0 AND 10),
    CONSTRAINT chk_conflict_clarity CHECK (conflict_clarity_score IS NULL OR (conflict_clarity_score BETWEEN 1 AND 5))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE login_events (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id     INT UNSIGNED NOT NULL,
    at          VARCHAR(40) NOT NULL,
    INDEX idx_login_events_at (at),
    CONSTRAINT fk_login_events_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE finalized_schedules (
    id                      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id                 INT UNSIGNED NOT NULL,
    schedule_key            VARCHAR(128) NOT NULL,
    week_start              VARCHAR(16) DEFAULT NULL,
    complete                TINYINT(1) NOT NULL DEFAULT 0,
    used_conflict_options   TINYINT(1) NOT NULL DEFAULT 0,
    at                      VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_finalized_user_key (user_id, schedule_key),
    CONSTRAINT fk_finalized_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE ratings (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id             INT UNSIGNED NOT NULL,
    schedule_key        VARCHAR(128) NOT NULL,
    week_start          VARCHAR(16) DEFAULT NULL,
    created_at          VARCHAR(40) NOT NULL,
    updated_at          VARCHAR(40) NOT NULL,
    overall             TINYINT NOT NULL,
    nps                 TINYINT DEFAULT NULL,
    adoption            VARCHAR(100) DEFAULT NULL,
    vs_manual           TINYINT DEFAULT NULL,
    conflict_clarity    TINYINT DEFAULT NULL,
    criteria_json       LONGTEXT NOT NULL,
    tradeoffs_json      LONGTEXT NOT NULL,
    problems_json       LONGTEXT NOT NULL,
    metrics_json        LONGTEXT NOT NULL,
    comment_good        TEXT DEFAULT NULL,
    comment_improve     TEXT DEFAULT NULL,
    UNIQUE KEY uq_ratings_user_key (user_id, schedule_key),
    INDEX idx_ratings_user (user_id),
    CONSTRAINT fk_ratings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_sessions (
    token_hash  CHAR(64) PRIMARY KEY,
    user_id     INT UNSIGNED NOT NULL,
    csrf        VARCHAR(64) NOT NULL,
    expires     BIGINT NOT NULL,
    INDEX idx_web_sessions_expires (expires),
    CONSTRAINT fk_web_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_drafts (
    user_id     INT UNSIGNED PRIMARY KEY,
    revision    INT NOT NULL,
    payload     LONGTEXT NOT NULL,
    colors      TEXT NOT NULL,
    notes       TEXT NOT NULL,
    CONSTRAINT fk_web_drafts_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_draft_undo (
    user_id     INT UNSIGNED NOT NULL,
    revision    INT NOT NULL,
    state       LONGTEXT NOT NULL,
    PRIMARY KEY (user_id, revision),
    CONSTRAINT fk_web_draft_undo_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_plans (
    seq             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE,
    id              VARCHAR(64) PRIMARY KEY,
    user_id         INT UNSIGNED NOT NULL,
    draft_revision  INT NOT NULL,
    state           LONGTEXT NOT NULL,
    INDEX web_plans_user (user_id, draft_revision, seq),
    CONSTRAINT fk_web_plans_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_history (
    seq         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE,
    user_id     INT UNSIGNED NOT NULL,
    id          VARCHAR(64) NOT NULL,
    week_start  VARCHAR(16) NOT NULL,
    record      LONGTEXT NOT NULL,
    PRIMARY KEY (user_id, id),
    INDEX idx_web_history_order (user_id, week_start, seq),
    CONSTRAINT fk_web_history_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_operations (
    user_id         INT UNSIGNED NOT NULL,
    operation_id    VARCHAR(64) NOT NULL,
    kind            VARCHAR(32) NOT NULL,
    payload         LONGTEXT NOT NULL,
    PRIMARY KEY (user_id, operation_id),
    CONSTRAINT fk_web_operations_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_finalized (
    user_id         INT UNSIGNED NOT NULL,
    schedule_key    VARCHAR(128) NOT NULL,
    week_start      VARCHAR(16) NOT NULL,
    metrics         LONGTEXT NOT NULL,
    PRIMARY KEY (user_id, schedule_key),
    CONSTRAINT fk_web_finalized_ref FOREIGN KEY (user_id, schedule_key)
        REFERENCES finalized_schedules(user_id, schedule_key) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE web_legacy_history_imports (
    user_id     INT UNSIGNED NOT NULL,
    history_id  VARCHAR(64) NOT NULL,
    PRIMARY KEY (user_id, history_id),
    CONSTRAINT fk_web_legacy_imports_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
