# SealCheck vision service (CPU). Works as a Hugging Face Docker Space (port 7860) or on any Docker host.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/home/user/.cache/huggingface VISION_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user models.py server.py prefetch.py ./
USER user
# bake the Apache-2.0 weights into the image so cold starts do not download them
RUN python prefetch.py
EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
