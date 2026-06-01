FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir flask flask-cors requests

COPY university_api_server.py /app/

EXPOSE 5000

CMD ["python", "university_api_server.py"]