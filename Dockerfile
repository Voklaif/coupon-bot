FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY coupon_bot.py coupon_ui.py ./

ENV PYTHONUNBUFFERED=1

# Default runs the Telegram bot; override command for UI.
CMD ["python", "coupon_bot.py", "--config", "/data/config.json"]
