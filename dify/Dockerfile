FROM python:3.11.14-slim
WORKDIR /opt/debate
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY data/ data/
ENV PYTHONUNBUFFERED=1 DEBATE_BIND=0.0.0.0 DEBATE_PORT=18604
CMD ["python", "src/server.py"]
