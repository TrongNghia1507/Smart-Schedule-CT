FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh \
    CPSAT_WORKERS=1

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
COPY apps ./apps
COPY database ./database
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8501
CMD ["sh", "-c", "streamlit run apps/streamlit/app.py --server.address 0.0.0.0 --server.port ${PORT:-8501} --server.headless true --browser.gatherUsageStats false"]
