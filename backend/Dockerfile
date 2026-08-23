FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i http://mirrors.tencentyun.com/pypi/simple \
    --extra-index-url https://pypi.org/simple \
    --trusted-host mirrors.tencentyun.com \
    -r requirements.txt

COPY app ./app
COPY init_db.py .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
