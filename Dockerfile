FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY filmweb_arr_sync/ filmweb_arr_sync/
COPY main.py .

VOLUME ["/data"]

CMD ["python", "main.py"]
