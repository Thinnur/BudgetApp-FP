FROM python:3.10

WORKDIR /app

# Install driver audio (Wajib untuk PyAudio/SpeechRecognition)
RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy semua kode aplikasi
COPY . .

# Beri izin akses file
RUN chmod -R 777 /app

# Buka PORT 8000 (Standar Koyeb)
EXPOSE 8000

# Jalankan aplikasi di port 8000
CMD ["python", "main.py"]
