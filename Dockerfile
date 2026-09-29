# Playwright's official image ships Chromium plus all the system libraries it needs.
# The tag MUST match the playwright version pinned in requirements.txt (1.44.0),
# because each Playwright release expects a specific Chromium build.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

CMD ["python", "scheduler.py"]
