FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV CALIBRA_DB=sqlite:////dados/calibra.db
VOLUME /dados
EXPOSE 8000
# Defina CALIBRA_SECRET em produção (ex.: docker run -e CALIBRA_SECRET=$(openssl rand -hex 32) ...)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
