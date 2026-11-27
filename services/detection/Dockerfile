FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt
COPY app/contracts.py app/trace_store.py app/detection_api.py ./app/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.detection_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
