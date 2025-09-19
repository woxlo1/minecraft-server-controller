# ベースイメージ
FROM python:3.12-slim

# FastAPI と必要ライブラリ
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# WebUIファイルもコピー
COPY web /app/web
COPY api.py /app/api.py

# uvicornを起動
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
