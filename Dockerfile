FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY pulse ./pulse
RUN pip install --no-cache-dir ".[api]" && useradd -m app
USER app
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["pulse-api"]
