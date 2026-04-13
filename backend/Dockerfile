FROM python:3.10-slim

# Prevent python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Set the working directory to /app
WORKDIR /app

# Install system dependencies
# These are occasionally required by libraries like PyMuPDF or Pillow
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file first to take advantage of Docker layer caching
COPY requirements.txt .

# Install python dependencies from requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend files
COPY . .

# Expose the API port
EXPOSE 8000

# Start the uvicorn server, mapping to Render's dynamic PORT or falling back to 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
