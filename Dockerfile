FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py community.py storage.py instance_lock.py .
RUN useradd --create-home botuser && mkdir /data && chown botuser /data
ENV DATA_DIR=/data
USER botuser
CMD ["python", "-u", "bot.py"]
