FROM python:3.9

WORKDIR /app

# 将项目所有文件复制到容器中
COPY . .

# 安装依赖
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# 创建 sessions 目录
RUN mkdir -p /app/sessions

# 指定挂载点，将项目所有文件映射到容器外部
VOLUME ["/app"]

CMD ["python", "bot.py"]