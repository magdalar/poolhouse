# Full image (not -slim): some HA deps build from source and need gcc.
# Python version must satisfy the test harness's Requires-Python.
FROM python:3.14
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /repo
