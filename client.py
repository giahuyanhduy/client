import requests
import time
import os
import subprocess
import re
import random
import json
import logging
from datetime import datetime, timedelta
from threading import Thread

logging.basicConfig(filename='client_log.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s:%(message)s')

def get_version_from_js():
    possible_paths = [
        '/home/Phase_3/GasController.js',
        '/home/giang/Phase_3/GasController.js'
    ]

    # Kiểm tra nội dung file /opt/autorun để tìm ./ips
    has_ips = False
    try:
        with open('/opt/autorun', 'r') as file:
            content = file.read()
            if './ips' in content:
                has_ips = True
    except Exception as e:
        logging.error(f"Lỗi khi đọc file /opt/autorun để kiểm tra ./ips: {e}")

    for path in possible_paths:
        if os.path.exists(path):
            with open(path, 'r') as file:
                content = file.read()
                match = re.search(r'const\s+ver\s*=\s*"([^"]+)"', content)
                if match:
                    return match.group(1) + "-IPS" if has_ips else match.group(1)
    
    # Giá trị mặc định với kiểm tra IPS
    return "1.0-IPS" if has_ips else "1.0"

def get_port_from_file():
    try:
        with open('/opt/autorun', 'r') as file:
            content = file.read()
            match = re.search(r'(\s\d{4}|\d{5}):localhost:22', content)
            if match:
                port = match.group(1).strip()
                return port
            else:
                logging.error("Không tìm thấy port trong file.")
                return None
    except Exception as e:
        logging.error(f"Lỗi khi đọc port từ file: {e}")
        return None

def get_data_from_url(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Mã trạng thái không phải 200: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi lấy dữ liệu từ URL: {e}")
        return None

def send_data_to_flask(data, port):
    flask_url = f"http://14.225.192.65/api/receive_data/{port}"
    try:
        response = requests.post(flask_url, json=data, timeout=60)
        logging.info(f"Dữ liệu đã gửi tới Flask server. Mã trạng thái: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi gửi dữ liệu tới Flask server: {e}")

def check_getdata_status(port, version, mac):
    request_url = f"http://14.225.192.65/api/request/{port},{version},{mac}"
    try:
        response = requests.get(request_url, timeout=60)
        if response.status_code == 200:
            data = response.json()
            laymabom = data.get('laymabom')
            if laymabom and laymabom != 'Off':
                logging.info(f"Nhận được giá trị laymabom: {laymabom}. Gọi API daylaidulieu.")
                call_daylaidulieu_api(laymabom)
            if data.get('restart') == 'True':
                logging.info("Nhận được lệnh restart. Đang khởi động lại hệ thống.")
                try:
                    result = subprocess.run(['reboot', 'now'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    logging.info(f"Lệnh thực thi thành công: {result.stdout.decode()}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Lỗi khi thực thi lệnh: {e.stderr.decode()}")
                except Exception as e:
                    logging.error(f"Lỗi không mong muốn khi thực thi lệnh: {str(e)}")
            if 'ssh' in data and data['ssh']:
                command = data['ssh']
                logging.info(f"Nhận được lệnh SSH: {command}. Đang thực thi lệnh.")
                try:
                    subprocess.Popen(command, shell=True)
                    logging.info(f"Đã bắt đầu thực thi lệnh: {command}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Lỗi khi thực thi lệnh: {e.stderr.decode()}")
                except Exception as e:
                    logging.error(f"Lỗi không mong muốn khi thực thi lệnh: {str(e)}")
            return data.get('getdata') == 'On'
        logging.error(f"Mã trạng thái không phải 200 từ check_getdata_status: {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi kiểm tra trạng thái getdata: {e}")
        return False

def call_daylaidulieu_api(pump_id):
    api_url = f"http://localhost:6969/daylaidulieu/{pump_id}"
    try:
        response = requests.get(api_url, timeout=10)
        logging.info(f"Đã gọi API daylaidulieu cho pump ID {pump_id}. Mã trạng thái: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi gọi API daylaidulieu: {e}")

def send_warning(port, pump_id, warning_type, mabom):
    warning_url = f"http://14.225.192.65/api/warning/{port}/{pump_id}/{warning_type}"
    try:
        response = requests.post(warning_url, json={'mabom': mabom}, timeout=10)
        logging.info(f"Đã gửi cảnh báo cho port {port}, pump ID {pump_id}, loại {warning_type}, mabom {mabom}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi gửi cảnh báo: {e}")

lastRestartAll = None
lastNonSequentialRestart = None

def check_mabom(data, mabom_history, file_path, port, connection_status, is_all_disconnect_restart):
    global lastRestartAll, lastNonSequentialRestart
    current_time = datetime.now()
    all_disconnected = True

    try:
        for item in data:
            idcot = item.get('id')
            pump = item.get('pump')
            statusnow = item.get('status')
            mabom_moinhat = item.get('MaBomMoiNhat', {}).get('pump')

            if idcot is None or pump is None:
                continue

            pump_id = str(idcot)
            mabomtiep = pump
            is_disconnected = item.get('isDisconnected', False)

            if not is_disconnected:
                all_disconnected = False

            if pump_id not in connection_status:
                connection_status[pump_id] = {
                    'is_disconnected': is_disconnected,
                    'disconnect_time': current_time if is_disconnected else None,
                    'alert_sent': False,
                    'last_alerted_mabom': None,
                    'mismatch_count': 0,
                    'restart_done': False
                }
            else:
                if is_disconnected:
                    if not connection_status[pump_id]['is_disconnected']:
                        connection_status[pump_id]['is_disconnected'] = True
                        connection_status[pump_id]['disconnect_time'] = current_time
                        connection_status[pump_id]['alert_sent'] = False
                        connection_status[pump_id]['restart_done'] = False
                    else:
                        if current_time - connection_status[pump_id]['disconnect_time'] > timedelta(seconds=65):
                            if not connection_status[pump_id]['alert_sent']:
                                logging.info(f"Pump ID {pump_id} mất kết nối quá 65 giây.")
                                send_warning(port, pump_id, "disconnection", mabomtiep)
                                connection_status[pump_id]['alert_sent'] = True
                else:
                    if connection_status[pump_id]['is_disconnected']:
                        if current_time - connection_status[pump_id]['disconnect_time'] <= timedelta(seconds=65):
                            logging.info(f"Pump ID {pump_id} đã kết nối lại trong vòng 65 giây.")
                        connection_status[pump_id] = {
                            'is_disconnected': False,
                            'disconnect_time': None,
                            'alert_sent': False,
                            'last_alerted_mabom': connection_status[pump_id].get('last_alerted_mabom'),
                            'mismatch_count': connection_status[pump_id].get('mismatch_count', 0),
                            'restart_done': connection_status[pump_id].get('restart_done', False)
                        }

            if pump_id not in mabom_history:
                mabom_history[pump_id] = []

            if mabom_history[pump_id] and isinstance(mabom_history[pump_id][-1], tuple) and mabom_history[pump_id][-1][0] == mabomtiep:
                continue
            else:
                mabom_history[pump_id].append((mabomtiep, current_time.strftime('%Y-%m-%d %H:%M:%S')))
                if len(mabom_history[pump_id]) > 10:
                    mabom_history[pump_id].pop(0)

            mabom_entries = [entry for entry in mabom_history[pump_id] if isinstance(entry, tuple)]

            if statusnow == 'sẵn sàng':
                if mabom_moinhat and mabom_moinhat != pump:
                    connection_status[pump_id]['mismatch_count'] += 1
                    logging.info(f"Mã bơm không khớp lần {connection_status[pump_id]['mismatch_count']} cho pump ID {pump_id}: {mabom_moinhat} != {pump}")

                    if connection_status[pump_id]['mismatch_count'] == 3:
                        if lastNonSequentialRestart is None or (current_time - lastNonSequentialRestart) > timedelta(minutes=10):
                            logging.info(f"Pump ID {pump_id} có mã bơm không khớp 3 lần. Thực hiện restartall.")
                            subprocess.run(['forever', 'restartall'])
                            lastNonSequentialRestart = current_time
                            time.sleep(3)
                            call_daylaidulieu_api(pump_id)
                            send_warning(port, pump_id, "nonsequential", mabomtiep)
                            connection_status[pump_id]['mismatch_count'] = 0
                        else:
                            logging.info("Phát hiện mã bơm không liên tiếp, nhưng đã restartall gần đây. Đợi 10 phút.")
                else:
                    connection_status[pump_id]['mismatch_count'] = 0

                if len(mabom_entries) > 1:
                    previous_mabom = mabom_entries[-2][0]
                    if isinstance(mabomtiep, int) and isinstance(previous_mabom, int):
                        if mabomtiep != previous_mabom + 1:
                            if connection_status[pump_id]['last_alerted_mabom'] != mabomtiep:
                                logging.info(f"Lỗi mã bơm không liên tiếp: Vòi bơm {pump_id} của port {port}.")
                                send_warning(port, pump_id, "nonsequential", mabomtiep)
                                call_daylaidulieu_api(pump_id)
                                mabom_history[pump_id].append({
                                    'type': 'nonsequential',
                                    'time': current_time.strftime('%Y-%m-%d %H:%M:%S')
                                })
                                connection_status[pump_id]['last_alerted_mabom'] = mabomtiep
                        else:
                            mabom_history[pump_id] = [entry for entry in mabom_history[pump_id] if not (isinstance(entry, dict) and entry.get('type') == 'nonsequential')]

        if all_disconnected and not any(conn['restart_done'] for conn in connection_status.values()) and not is_all_disconnect_restart[0]:
            if lastRestartAll is None or (current_time - lastRestartAll) > timedelta(minutes=10):
                logging.info("Tất cả các vòi đều mất kết nối. Thực hiện restartall.")
                subprocess.run(['forever', 'restartall'])
                lastRestartAll = current_time
                for conn in connection_status.values():
                    conn['restart_done'] = True
                send_all_disconnected_warning(port)
                is_all_disconnect_restart[0] = True
            else:
                logging.info("Tất cả các vòi mất kết nối, nhưng đã restartall gần đây. Đợi 10 phút.")
        
        if not all_disconnected:
            is_all_disconnect_restart[0] = False

    except Exception as e:
        logging.error(f"Lỗi trong check_mab Oman: {e}")

def send_all_disconnected_warning(port):
    warning_url = f"http://14.225.192.65/api/warning/{port}/all/all_disconnection"
    try:
        response = requests.post(warning_url, json={'message': 'Tất cả các vòi đều mất kết nối.'})
        print(f"Đã gửi cảnh báo mất kết nối tất cả cho port {port}")
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi gửi cảnh báo mất kết nối tất cả: {e}")

def check_mabom_continuously(port, mabom_file_path):
    if os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'r') as file:
                mabom_history = json.load(file)
                print(f"Đã tải lịch sử mabom từ {mabom_file_path}")
        except Exception as e:
            print(f"Lỗi khi tải lịch sử mabom: {e}")
            mabom_history = {}
    else:
        mabom_history = {}
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump(mabom_history, file, indent=4)
                print(f"Đã tạo file lịch sử mabom tại {mabom_file_path}")
        except Exception as e:
            print(f"Lỗi khi tạo file lịch sử mabom: {e}")

    connection_status = {}
    is_all_disconnect_restart = [False]

    while True:
        data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
        if data_from_url:
            check_mabom(data_from_url, mabom_history, mabom_file_path, port, connection_status, is_all_disconnect_restart)
        else:
            print("Không lấy được dữ liệu từ URL")
        time.sleep(2)

def random_sleep_time():
    return random.uniform(4, 8)

def send_data_continuously(port, version, mac):
    while True:
        if check_getdata_status(port, version, mac):
            data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
            if data_from_url:
                send_data_to_flask(data_from_url, port)
                print("Dữ liệu đã gửi tới Flask server")
            else:
                print("Không lấy được dữ liệu từ URL")
        else:
            print("getdata đang Off")
        
        sleep_duration = random_sleep_time()
        time.sleep(sleep_duration)

def get_mac():
    try:
        interface_cmd = "ip route get 1.1.1.1 | grep -oP 'dev \\K\\w+'"
        interface = subprocess.check_output(interface_cmd, shell=True).decode().strip()
        result = subprocess.check_output(f"ip link show {interface}", shell=True).decode()
        mac_match = re.search(r"ether ([\da-fA-F:]+)", result)
        if mac_match:
            return mac_match.group(1)
    except subprocess.CalledProcessError as e:
        print(f"Lỗi khi chạy lệnh ip link: {e}")
    except Exception as e:
        print(f"Lỗi lấy MAC Address: {e}")
    return "00:00:00:00:00:00"

def main():
    port = get_port_from_file()
    if not port:
        print("Không tìm thấy port. Thoát.")
        return
    mac = get_mac()
    if not mac:
        print("Không tìm thấy MAC. Thoát.")
        return
    print(f"Sử dụng port: {port}")
    version = get_version_from_js()
    print(f"Sử dụng version: {version}")
    script_dir = os.path.dirname(os.path.realpath(__file__))
    mabom_file_path = os.path.join(script_dir, 'mabom.json')

    if not os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump({}, file, indent=4)
                print(f"Đã tạo file lịch sử mabom tại {mabom_file_path}")
        except Exception as e:
            print(f"Lỗi khi tạo file lịch sử mabom: {e}")
            return

    mabom_thread = Thread(target=check_mabom_continuously, args=(port, mabom_file_path))
    mabom_thread.start()
    send_data_continuously(port, version, mac)

if __name__ == "__main__":
    main()
