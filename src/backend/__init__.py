"""Backend Smart Schedule CT: lớp trung gian giữa MySQL và 4 module thuật toán lõi.

Giao diện (Streamlit) chỉ gọi các service trong gói này, ví dụ::

    from backend import auth_service, schedule_service, history_service
"""
