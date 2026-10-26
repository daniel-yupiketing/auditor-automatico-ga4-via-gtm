FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ga4_event_analyzer.py .

EXPOSE 8080

CMD ["streamlit", "run", "ga4_event_analyzer.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
