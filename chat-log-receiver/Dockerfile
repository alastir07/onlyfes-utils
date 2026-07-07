# 1. Use a stable Python base image (3.12 is a reliable LTS version)
FROM python:3.12-slim

# 2. Set the working directory
WORKDIR /usr/src/app

# 3. Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of your application code
COPY . .

# 5. Command to run the service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
