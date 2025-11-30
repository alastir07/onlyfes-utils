# 1. Use a stable Python base image (3.12 is a reliable LTS version)
FROM python:3.12-slim

# 2. Install necessary system dependencies for Python packages (PyNaCl/Discord voice)
#    and ffmpeg (required if your bot handles any audio/music)
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libsodium-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working directory
WORKDIR /usr/src/app

# 4. Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your application code
COPY . .

# 6. Command to run your bot
#    (Assumes your main file is named 'bot.py', as suggested by the logs)
CMD [ "python3", "bot.py" ]