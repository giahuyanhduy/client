import requests
import time
import os
import subprocess
import re
import json
from datetime import datetime, timedelta
from threading import Thread



def get_port_from_file():
    try:
        with open('/opt/autorun', 'r') as file:
            content = file.read()
            # Biểu thức chính quy để bắt đầu với 1 khoảng trắng và 4 ký tự số hoặc không có khoảng trắng và 5 ký tự số
            match = re.search(r'(\s\d{4}|\d{5}):localhost:22', content)
            if match:
                port = match.group(1).strip()  # Xóa khoảng trắng ở đầu nếu có
                return port
            else:
                print("Port not found in the file.")
                return None
    except Exception as e:
        print(f"Error reading port from file: {e}")
        return None

def get_data_from_url(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Non-200 status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from URL: {e}")
        return None

def send_data_to_flask(data, port):
    flask_url = f"http://103.77.166.69/api/receive_data/{port}"
    try:
        response = requests.post(flask_url, json=data)
        print("Status Code:", response.status_code)
        print("Response Text:", response.text)
    except requests.exceptions.RequestException as e:
        print(f"Error sending data to Flask server: {e}")

def check_getdata_status(port):
    request_url = f"http://103.77.166.69/api/request/{port}"
    try:
        response = requests.get(request_url)
        if response.status_code == 200:
            data = response.json()
            print(f"Data from /api/request/{port}: {data}")
            if data.get('restart') == 'True':
                print("Restart command received. Restarting system.")
                subprocess.run(['sudo', 'reboot'])
            if 'ssh' in data and data['ssh']:
                command = data['ssh']
                print(f"SSH command received: {command}. Executing command.")
                try:
                    result = subprocess.run(command, shell=True, check=True, capture_output=True)
                    print(f"Command executed successfully: {result.stdout.decode()}")
                except subprocess.CalledProcessError as e:
                    print(f"Error executing command: {e.stderr.decode()}")
            return data.get('getdata') == 'On'
        print(f"Non-200 status code from check_getdata_status: {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error checking getdata status: {e}")
        return False


def send_warning(port, pump_id, warning_type):
    warning_url = f"http://103.77.166.69/api/warning/{port}/{pump_id}/{warning_type}"
    try:
        response = requests.post(warning_url)
        print(f"Sent warning for port {port}, pump ID {pump_id}, type {warning_type}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending warning: {e}")

def call_daylaidulieu_api(pump_id):
    api_url = f"http://localhost:6969/daylaidulieu/{pump_id}"
    try:
        response = requests.get(api_url)
        print(f"Called daylaidulieu API for pump ID {pump_id}. Status Code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error calling daylaidulieu API: {e}")


def check_mabom(data, mabom_history, file_path, port, connection_status):
    current_time = datetime.now()

    for item in data:
        if 'MaBomMoiNhat' in item and item['MaBomMoiNhat'] is not None:
            idcot = item['MaBomMoiNhat'].get('idcot')
            pump = item['MaBomMoiNhat'].get('pump')
        else:
            print(f"Skipping item because 'MaBomMoiNhat' is missing or None. Item: {item}")
            continue

        if idcot is None or pump is None:
            print(f"Skipping item because 'idcot' or 'pump' is None. idcot: {idcot}, pump: {pump}")
            continue

        print(f"Processed item: idcot={idcot}, pump={pump}")

        pump_id = str(idcot)
        mabomtiep = pump

        is_disconnected = item.get('isDisconnected', False)

        if pump_id not in connection_status:
            connection_status[pump_id] = {
                'is_disconnected': is_disconnected,
                'disconnect_time': current_time if is_disconnected else None,
                'alert_sent': False,
                'last_alerted_mabom': None  # Thêm mục này để theo dõi mã bơm đã cảnh báo
            }
        else:
            if is_disconnected:
                if not connection_status[pump_id]['is_disconnected']:
                    connection_status[pump_id]['is_disconnected'] = True
                    connection_status[pump_id]['disconnect_time'] = current_time
                    connection_status[pump_id]['alert_sent'] = False
                else:
                    if current_time - connection_status[pump_id]['disconnect_time'] > timedelta(seconds=65):
                        if not connection_status[pump_id]['alert_sent']:
                            print(f"Pump ID {pump_id} disconnected for more than 65 seconds.")
                            send_warning(port, pump_id, "disconnection")
                            connection_status[pump_id]['alert_sent'] = True
            else:
                if connection_status[pump_id]['is_disconnected']:
                    if current_time - connection_status[pump_id]['disconnect_time'] <= timedelta(seconds=65):
                        print(f"Pump ID {pump_id} reconnected within 65 seconds.")
                    connection_status[pump_id] = {
                        'is_disconnected': False,
                        'disconnect_time': None,
                        'alert_sent': False,
                        'last_alerted_mabom': connection_status[pump_id].get('last_alerted_mabom')  # Giữ nguyên giá trị last_alerted_mabom
                    }

        if pump_id not in mabom_history:
            mabom_history[pump_id] = []

        if mabom_history[pump_id] and isinstance(mabom_history[pump_id][-1], tuple) and mabom_history[pump_id][-1][0] == mabomtiep:
            print(f"No change in mabomtiep for pump ID {pump_id}, keeping the same value.")
        else:
            mabom_history[pump_id].append((mabomtiep, current_time.strftime('%Y-%m-%d %H:%M:%S')))
            if len(mabom_history[pump_id]) > 10:
                mabom_history[pump_id].pop(0)

        mabom_entries = [entry for entry in mabom_history[pump_id] if isinstance(entry, tuple)]

        if len(mabom_entries) > 1:
            previous_mabom = mabom_entries[-2][0]
            if isinstance(mabomtiep, int) and isinstance(previous_mabom, int):
                if mabomtiep != previous_mabom + 1:
                    # Chỉ gửi cảnh báo nếu mã bơm hiện tại khác với mã bơm đã cảnh báo trước đó
                    if connection_status[pump_id]['last_alerted_mabom'] != mabomtiep:
                        print(f"Lỗi mã bơm không liên tiếp: Vòi bơm {pump_id} của port {port} phát hiện mã bơm không liên tiếp.")
                        send_warning(port, pump_id, f"nonsequential: {mabomtiep}")  # Gửi mã bơm kèm theo cảnh báo
                        call_daylaidulieu_api(pump_id)
                        mabom_history[pump_id].append({
                            'type': 'nonsequential',
                            'time': current_time.strftime('%Y-%m-%d %H:%M:%S')
                        })
                        connection_status[pump_id]['last_alerted_mabom'] = mabomtiep
                else:
                    mabom_history[pump_id] = [entry for entry in mabom_history[pump_id] if not (isinstance(entry, dict) and entry.get('type') == 'nonsequential')]

    try:
        with open(file_path, 'w') as file:
            json.dump(mabom_history, file, indent=4)
            print(f"Data successfully written to {file_path}")
    except Exception as e:
        print(f"Error writing to file {file_path}: {e}")



def check_mabom_continuously(port, mabom_file_path):
    if os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'r') as file:
                mabom_history = json.load(file)
                print(f"Loaded existing mabom history from {mabom_file_path}")
        except Exception as e:
            print(f"Error loading mabom history from file: {e}")
            mabom_history = {}
    else:
        mabom_history = {}
        # Tạo file mới nếu chưa tồn tại
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump(mabom_history, file, indent=4)
                print(f"Created new mabom history file at {mabom_file_path}")
        except Exception as e:
            print(f"Error creating mabom history file: {e}")

    connection_status = {}

    while True:
        data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
        if data_from_url:
            check_mabom(data_from_url, mabom_history, mabom_file_path, port, connection_status)
        else:
            print("Failed to retrieve data from URL")
        time.sleep(2)
        
def send_data_continuously(port):
    while True:
        if check_getdata_status(port):
            data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
            #print("Data from URL:", data_from_url)
            if data_from_url:
                send_data_to_flask(data_from_url, port)
                print("Data sent to Flask server")
            else:
                print("Failed to retrieve data from URL")
        else:
            print("getdata is Off")
        time.sleep(4)

def main():
    port = get_port_from_file()
    if not port:
        print("No port found. Exiting.")
        return
    
    print(f"Using port: {port}")

    # Đảm bảo rằng mabom_file_path là đường dẫn đầy đủ
    script_dir = os.path.dirname(os.path.realpath(__file__))
    mabom_file_path = os.path.join(script_dir, 'mabom.json')

    # Kiểm tra và tạo file mabom.json nếu chưa tồn tại
    if not os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump({}, file, indent=4)
                print(f"Created new mabom history file at {mabom_file_path}")
        except Exception as e:
            print(f"Error creating mabom history file: {e}")
            return

    # Run mabom check in a separate thread
    mabom_thread = Thread(target=check_mabom_continuously, args=(port, mabom_file_path))
    mabom_thread.start()

    # Run data sending in the main thread
    send_data_continuously(port)
if __name__ == "__main__":
    main()
