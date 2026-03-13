FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY coupon_bot.py coupon_ui.py ./
COPY scripts ./scripts

RUN mkdir -p /app/runtime /data /config && chown -R app:app /app /data /config

USER app

CMD ["python", "coupon_bot.py", "--config", "/config/config.json"]
