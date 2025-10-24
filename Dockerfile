# Use slim Python image
FROM python:3.11-slim

# System deps for OCR / PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends     tesseract-ocr     poppler-utils     libmagic1     && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Copy project files
COPY . /app

# Optional: if /data is available (e.g., on Hugging Face Persistent Storage), 
# this makes app's ./data point there. Fallback if /data doesn't exist is fine.
RUN mkdir -p /app/data && (rm -rf /app/data && ln -s /data /app/data) || true

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Environment
ENV PYTHONUNBUFFERED=1

# Expose port (Hugging Face uses $PORT; default 7860)
ENV PORT=7860
EXPOSE 7860

# Start the FastAPI app
CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
