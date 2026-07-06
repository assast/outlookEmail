# 使用 Python 3.11 作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装 curl（用于健康检查）
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 复制依赖文件
COPY requirements.txt .

# 安装依赖（包括生产服务器）
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install gunicorn

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 5000

# 启动应用（gunicorn 线程模型，单 worker 多线程）
# 超时等参数通过环境变量注入，无需硬编码在镜像中
CMD ["sh", "-c", "gunicorn -k gthread -w 1 --threads ${GUNICORN_THREADS:-4} -b 0.0.0.0:5000 --timeout ${GUNICORN_TIMEOUT:-300} --graceful-timeout 30 --access-logfile - --error-logfile - --capture-output web_outlook_app:app"]
