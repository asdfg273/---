# /home/pi/my_cloud_app/oled_manager.py

import time
import psutil
import os
import subprocess
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
# from luma.oled.device import sh1106
from PIL import ImageFont

# --- OLED Configuration ---
OLED_I2C_ADDRESS = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64

# --- Storage Path Configuration ---
STORAGE_MOUNT_POINT = '/mnt/mydisk' # <--- !!! 确保这是你外部硬盘的挂载点 !!!

# --- Font Configuration ---
# 优先尝试的中文字体路径 (文泉驿微米黑)
CHINESE_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
# 如果是 .ttc (TrueType Collection)，可能需要指定字体索引，通常第一个是 0
CHINESE_FONT_INDEX = 0 # 对于 wqy-microhei.ttc，通常索引0是可用的常规体

FONT_PATHS_TO_TRY = [
    # 首先尝试加载我们指定的中文字体
    # "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", # 另一个选择：文泉驿正黑
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "arial.ttf",
]

def load_font(size, try_chinese=False):
    font_to_use = None
    if try_chinese:
        try:
            # 尝试加载指定的中文字体
            font_to_use = ImageFont.truetype(CHINESE_FONT_PATH, size, index=CHINESE_FONT_INDEX)
            print(f"Successfully loaded Chinese font: {CHINESE_FONT_PATH} with size {size}")
            return font_to_use
        except IOError:
            print(f"Warning: Could not load Chinese font {CHINESE_FONT_PATH}. Trying alternatives.")
        except Exception as e:
            print(f"Warning: Error loading Chinese font {CHINESE_FONT_PATH}: {e}. Trying alternatives.")


    for font_path in FONT_PATHS_TO_TRY:
        try:
            font_to_use = ImageFont.truetype(font_path, size)
            print(f"Loaded fallback font: {font_path} with size {size}")
            return font_to_use
        except IOError:
            continue
    print(f"Warning: Could not load any preferred fonts. Using PIL default font for size {size}.")
    return ImageFont.load_default()

# 调整字体大小以适应屏幕和中文字符
font_small_size = 10  # 中文标签和数据，可以根据显示效果微调
font_time_size = 10   # 时间字体大小
font_small_cn = load_font(font_small_size, try_chinese=True) # 尝试加载中文
font_time = load_font(font_time_size, try_chinese=True) # 时间也用此字体


# --- OLED Device Initialization ---
try:
    serial = i2c(port=1, address=OLED_I2C_ADDRESS)
    device = ssd1306(serial, width=OLED_WIDTH, height=OLED_HEIGHT)
    # if 'sh1106' in str(device.__class__): device = sh1106(...)
    print(f"OLED device (model assumed: {'SSD1306' if 'ssd1306' in str(device.__class__) else 'SH1106'}, {OLED_WIDTH}x{OLED_HEIGHT}) initialized successfully.")
except Exception as e:
    print(f"Critical error initializing OLED: {e}")
    exit()

# --- System Info Getter Functions (与之前版本相同，此处省略以节省空间) ---
def get_cpu_temperature():
    try:
        temp_str = subprocess.check_output(['vcgencmd', 'measure_temp']).decode('utf-8')
        return temp_str.replace("temp=", "").replace("'C\n", "")
    except FileNotFoundError:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = int(f.read().strip()) / 1000
            return f"{temp:.1f}"
        except Exception as e_sys:
            print(f"Warning: vcgencmd not found and error reading /sys: {e_sys}")
            return "N/A"
    except Exception as e_vc:
        print(f"Warning: Error getting CPU temp with vcgencmd: {e_vc}")
        return "N/A"

def get_ram_usage():
    ram = psutil.virtual_memory()
    total_gb = ram.total / (1024**3)
    used_gb = ram.used / (1024**3)
    return f"{used_gb:.1f}/{total_gb:.1f}G {ram.percent}%"

def get_disk_usage(path):
    try:
        disk = psutil.disk_usage(path)
        total_gb = disk.total / (1024**3)
        used_gb = disk.used / (1024**3)
        return f"{used_gb:.1f}/{total_gb:.1f}G {disk.percent}%"
    except FileNotFoundError:
        print(f"Warning: Path not found for disk usage: {path}")
        return "N/A (Path?)"
    except Exception as e:
        print(f"Warning: Error getting disk usage for {path}: {e}")
        return "N/A"

def get_ip_address(interface='wlan0'):
    try:
        result = subprocess.check_output(['ip', '-4', 'addr', 'show', interface], timeout=2).decode('utf-8')
        for line in result.split('\n'):
            if 'inet' in line and 'brd' in line:
                ip = line.strip().split(' ')[1].split('/')[0]
                return ip
        return "N/A (No inet)"
    except FileNotFoundError:
        print("Warning: 'ip' command not found. Cannot get IP address.")
        return "N/A (No ip cmd)"
    except subprocess.TimeoutExpired:
        print(f"Warning: Timeout getting IP for {interface}")
        return "N/A (Timeout)"
    except Exception as e:
        print(f"Warning: Error getting IP for {interface}: {e}")
        return "N/A"
# --- END System Info Getter Functions ---


# --- OLED Display Update Function ---
def display_system_info_on_oled():
    with canvas(device) as draw:
        cpu_temp = get_cpu_temperature()
        ram_info = get_ram_usage().split(' ') # [ "used/totalG", "percent%"]
        disk_root_info = get_disk_usage('/').split(' ')
        disk_storage_info = get_disk_usage(STORAGE_MOUNT_POINT).split(' ')
        ip_wlan0 = get_ip_address('wlan0')
        ip_eth0 = get_ip_address('eth0')

        y_pos = 0
        # 使用 font_small_cn.getbbox("一")[3] 来获取中文字符高度作为行高参考
        try:
            # 尝试获取中文字符高度，如果font_small_cn未成功加载中文则可能用默认字体高度
            line_h = font_small_cn.getbbox("测")[3] + 2 if hasattr(font_small_cn, 'getbbox') else 12
        except AttributeError: # 以防万一 getbbox 不存在
             line_h = 12 # 默认行高

        # 中文标签 (可以根据屏幕空间调整)
        cpu_label = "CPU:"
        ram_label = "内存:"
        root_label = "系统:"
        storage_label = "数据:" # 如果STORAGE_MOUNT_POINT是外部硬盘
        wlan_label = "无线:"
        eth_label = "有线:"

        # 第1行: CPU温度 和 内存使用率
        # 为了节省空间，我们可能需要更紧凑地显示
        text_line1 = f"{cpu_label}{cpu_temp}°C {ram_label}{ram_info[1]}"
        draw.text((0, y_pos), text_line1, font=font_small_cn, fill="white")
        y_pos += line_h

        # 第2行: 系统盘使用率
        text_line2 = f"{root_label}{disk_root_info[1]}"
        draw.text((0, y_pos), text_line2, font=font_small_cn, fill="white")
        y_pos += line_h

        if OLED_HEIGHT >= 64: # 128x64 屏幕
            # 第3行: 数据盘使用率
            text_line3 = f"{storage_label}{disk_storage_info[1]}"
            draw.text((0, y_pos), text_line3, font=font_small_cn, fill="white")
            y_pos += line_h

            # 第4行 & 第5行 (如果空间足够): IP 地址
            ip_displayed = False
            if ip_wlan0 != "N/A (No inet)" and ip_wlan0 != "N/A":
                draw.text((0, y_pos), f"{wlan_label}{ip_wlan0}", font=font_small_cn, fill="white")
                y_pos += line_h
                ip_displayed = True
            
            # 只有当wlan0没有显示IP或者eth0的IP不同时才显示eth0
            if ip_eth0 != "N/A (No inet)" and ip_eth0 != "N/A" and ip_eth0 != ip_wlan0:
                # 如果WLAN没显示，或者ETH IP不同，则显示ETH IP
                if not ip_displayed or (ip_eth0 != ip_wlan0):
                     # 如果上一行已经占满，需要检查y_pos是否超出
                    if y_pos + line_h <= OLED_HEIGHT - line_h: # 留出时间空间
                        draw.text((0, y_pos), f"{eth_label}{ip_eth0}", font=font_small_cn, fill="white")
                        y_pos += line_h

            # 右下角显示时间
            current_time = time.strftime("%H:%M")
            try:
                time_bbox = font_time.getbbox(current_time)
                time_width = time_bbox[2] - time_bbox[0]
                time_height = time_bbox[3] - time_bbox[1]
                # 确保y_pos不会导致时间画在屏幕外
                time_y = OLED_HEIGHT - time_height -1 # 稍微向上一点
                if time_y < y_pos : # 如果当前y_pos已经很靠下了，就和最后一行对齐
                    time_y = y_pos - line_h # 尝试和最后一行文字的基线对齐
                    if time_y < 0 : time_y = OLED_HEIGHT - time_height - 1 # 极端情况

                draw.text((OLED_WIDTH - time_width - 1, time_y ), current_time, font=font_time, fill="white")
            except AttributeError: # 如果 font_time 没有 getbbox
                draw.text((OLED_WIDTH - 30, OLED_HEIGHT -12 ), current_time, font=ImageFont.load_default(), fill="white")


        elif OLED_HEIGHT >= 32: # 128x32 屏幕 (中文显示会非常拥挤)
            # 对于128x32，显示中文可能需要更小的字号或更精简的信息
            if ip_wlan0 != "N/A (No inet)" and ip_wlan0 != "N/A":
                 draw.text((0, y_pos), f"IP:{ip_wlan0}", font=font_small_cn, fill="white")
            elif ip_eth0 != "N/A (No inet)" and ip_eth0 != "N/A":
                 draw.text((0, y_pos), f"IP:{ip_eth0}", font=font_small_cn, fill="white")

# --- Main Loop (与之前版本相同) ---
if __name__ == "__main__":
    print("Starting OLED system information display script (with Chinese font attempt).")
    print(f" - OLED Address: 0x{OLED_I2C_ADDRESS:X}, Assumed Model: {'SSD1306' if 'ssd1306' in str(device.__class__) else 'SH1106'}, Size: {OLED_WIDTH}x{OLED_HEIGHT}")
    print(f" - Monitoring disk usage for root ('/') and storage ('{STORAGE_MOUNT_POINT}').")
    print(f" - Attempting to use Chinese font: {CHINESE_FONT_PATH} (index {CHINESE_FONT_INDEX})")
    print(" - Press Ctrl+C to stop.")

    try:
        display_system_info_on_oled()
    except Exception as e:
        print(f"Error during initial display: {e}", exc_info=True) # 添加 exc_info

    update_interval_seconds = 5
    try:
        while True:
            time.sleep(update_interval_seconds)
            display_system_info_on_oled()
    except KeyboardInterrupt:
        print("\nStopping OLED display script.")
    except Exception as e:
        print(f"An error occurred in the main loop: {e}", exc_info=True) # 添加 exc_info
    finally:
        try:
            with canvas(device) as draw:
                draw.rectangle(device.bounding_box, outline="black", fill="black")
            print("OLED screen cleared on exit.")
        except Exception as e_clear:
            print(f"Error clearing screen on exit: {e_clear}")

