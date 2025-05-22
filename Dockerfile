FROM python:3.9-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
RUN mkdir -p ./data
CMD ["python", "bot/main.py"]
