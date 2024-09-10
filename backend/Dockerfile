# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Install necessary dependencies and Helm
RUN apt-get update && \
    apt-get install -y curl apt-transport-https gnupg2 && \
    curl https://baltocdn.com/helm/signing.asc | apt-key add - && \
    echo "deb https://baltocdn.com/helm/stable/debian/ all main" | tee /etc/apt/sources.list.d/helm-stable-debian.list && \
    apt-get update && \
    apt-get install -y helm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the required files
COPY api/ ./api/
COPY controller/ ./controller/
COPY templates/ ./templates/
COPY schemas/ ./schemas/
COPY app.py .
COPY logger.py .
COPY database.db .
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run app.py when the container launches
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]