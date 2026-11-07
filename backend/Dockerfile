FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY start.sh .
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-deps .
EXPOSE 8000
CMD ["sh", "start.sh"]
