import os

os.environ.setdefault("SECRET_KEY", "pytest-secret")
os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("ADMIN_PASSWORD", "test-pass")
os.environ.setdefault("DATA_DIR", "/tmp/tech-news-hub-pytest")
