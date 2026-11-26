FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/contracts.py app/trace_store.py app/context_store.py app/incident_context.py app/context_api.py app/telemetry_receipts.py ./app/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.context_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
