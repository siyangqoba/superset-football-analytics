# Image for the ETL job and the dashboard bootstrap script.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY etl ./etl
COPY sql ./sql
COPY superset/bootstrap_dashboard.py ./superset/bootstrap_dashboard.py
CMD ["python", "-m", "etl.load"]
