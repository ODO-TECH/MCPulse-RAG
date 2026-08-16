FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir --only-binary=:all: -r /app/requirements.txt

COPY app/ /app/

EXPOSE 6646

CMD ["bash", "/app/start.sh"]
