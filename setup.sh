#!/bin/bash
# 1.12 FIX
# Đường dẫn đến thư mục chứa repository Git
REPO_DIR="/home/client-repo"

# URL của file client.py trên GitHub
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Đồng bộ thời gian hệ thống trước khi làm bất cứ điều gì
echo "Syncing system time with Google's server..."
date -s "$(curl -s --head http://google.com | grep ^Date: | sed 's/Date: //g')"

# Tạo thư mục nếu chưa tồn tại
mkdir -p $REPO_DIR

# Cài đặt python3-pip nếu chưa được cài
if ! command -v pip3 &> /dev/null; then
    echo "python3-pip not found. Installing..."
    apt-get update
    apt-get install -y python3-pip
    if [ $? -ne 0 ]; then
        echo "Failed to install python3-pip. Exiting."
        exit 1
    fi
else
    echo "python3-pip is already installed."
fi

# Cài đặt thư viện Python cần thiết
echo "Installing required Python libraries..."
pip3 install --no-cache-dir requests urllib3 certifi charset_normalizer chardet
if [ $? -ne 0 ]; then
    echo "Failed to install required Python libraries. Exiting."
    exit 1
fi

# Clone repository vào thư mục nếu chưa được clone
if [ ! -d "$REPO_DIR/.git" ]; then
    git clone https://github.com/giahuyanhduy/client.git $REPO_DIR
fi

# Tạo file startup.sh với logic mới
cat <<EOL > $REPO_DIR/startup.sh
#!/bin/bash

LOG_FILE="$REPO_DIR/startup.log"
CLIENT_FILE="$REPO_DIR/client.py"
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Ghi thời gian bắt đầu vào log
echo "Starting startup script at \$(date)" >> \$LOG_FILE

# Kiểm tra xem đây có phải là một repository Git không
if [ ! -d ".git" ]; then
    echo "No .git directory found in \$REPO_DIR. Exiting." >> \$LOG_FILE
    exit 1
fi

# Pull các thay đổi mới nhất từ GitHub
if ! git pull origin main >> \$LOG_FILE 2>&1; then
    echo "Failed to pull changes from GitHub at \$(date), trying to download client.py using curl" >> \$LOG_FILE
    
    # Tải file client.py từ GitHub nếu git pull thất bại
    if curl -o \$CLIENT_FILE \$GITHUB_URL; then
        echo "Successfully downloaded client.py from GitHub at \$(date)" >> \$LOG_FILE
    else
        echo "Failed to download client.py from GitHub at \$(date)" >> \$LOG_FILE
        exit 1
    fi
else
    echo "Successfully pulled latest changes from GitHub at \$(date)" >> \$LOG_FILE
fi

# Kiểm tra xem file client.py có tồn tại không
if [ ! -f \$CLIENT_FILE ]; then
    echo "client.py not found after git pull or curl. Exiting." >> \$LOG_FILE
    exit 1
fi

# Chạy client.py
if python3 \$CLIENT_FILE; then
    echo "Successfully ran client.py at \$(date)" >> \$LOG_FILE
else
    echo "Failed to run client.py at \$(date)" >> \$LOG_FILE
    exit 1
fi
EOL

# Cấp quyền thực thi cho startup.sh
chmod +x $REPO_DIR/startup.sh

# Tạo file service cho systemd
SERVICE_FILE="/etc/systemd/system/client.service"
cat <<EOL | tee ${SERVICE_FILE} > /dev/null
[Unit]
Description=Run client.py from GitHub on startup
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=/bin/bash $REPO_DIR/startup.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

# Kiểm tra xem tệp dịch vụ đã được tạo thành công chưa
if [ -f ${SERVICE_FILE} ]; then
    echo "Service file created successfully at ${SERVICE_FILE}"
else
    echo "Failed to create service file at ${SERVICE_FILE}"
    exit 1
fi

# Kích hoạt và khởi động dịch vụ
systemctl daemon-reload
systemctl enable client.service
systemctl start client.service
systemctl restart client.service

# Kiểm tra trạng thái của dịch vụ
systemctl status client.service

echo "Setup complete. client.service has been created and started."
