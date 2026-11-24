FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && install -d -o 10001 -g 10001 -m 0750 /data
COPY app/contracts.py app/trace_store.py app/incident_context.py app/llm_analysis.py app/incident_workflow.py ./app/
USER 10001:10001
CMD ["uvicorn", "app.incident_workflow:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
