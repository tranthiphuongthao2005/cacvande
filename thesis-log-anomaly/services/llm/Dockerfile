FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt requirements-llm.txt .
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements-llm.txt
COPY app/contracts.py app/trace_store.py app/incident_context.py app/llm_analysis.py app/llm_provider.py app/llm_api.py ./app/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.llm_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
