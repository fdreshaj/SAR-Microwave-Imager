import socket
import threading
import os
import time 
import re
import math
from datetime import datetime
from scanner.probe_controller import ProbePlugin
from scanner.plugin_setting import PluginSettingString, PluginSettingInteger
from scanner.motion_controller import MotionControllerPlugin

# Regex to extract data from the CyBot stream
_SCAN_RE = re.compile(
    r'Data:\s*Ultrasound\s*([\d.]+)\s*,\s*IR\s*([\d.]+)\s*,\s*Angle\s*(\d+)',
    re.IGNORECASE
)

class cyBot_Plugin(ProbePlugin):
    # (Existing ProbePlugin implementation remains unchanged)
    def __init__(self):
        super().__init__()
        self.cybot = None
        self.read_thread = None
        self.read_thread_cond = False
        self.address = PluginSettingString("IP Address", "192.168.1.1")
        self.port = PluginSettingInteger("Port", 288)
        self.timeout = PluginSettingInteger("Timeout (ms)", 10000)
        self.add_setting_pre_connect(self.address)
        self.add_setting_pre_connect(self.port)
        self.add_setting_pre_connect(self.timeout)
        self.log_filename = "cybot_data_log.txt"

    def connect(self):
        try:
            self.cybot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cybot.settimeout(self.timeout.value / 1000)
            self.cybot.connect((self.address.value, self.port.value))
            self.read_thread_cond = True
            self.read_thread = threading.Thread(target=self.read_thread_interrupt, daemon=True)
            self.read_thread.start()
        except Exception as e:
            print(f"Connection failed: {e}")

    def read_thread_interrupt(self):
        with open(self.log_filename, "a") as f:
            while self.read_thread_cond:
                try:
                    data = self.cybot.recv(1024)
                    if data:
                        decoded = data.decode('utf-8', errors='ignore').strip()
                        f.write(f"[{datetime.now()}] RX: {decoded}\n")
                        f.flush()
                    else: break
                except: continue

    def disconnect(self):
        self.read_thread_cond = False
        if self.cybot: self.cybot.close()

    def send_command(self, cmd):
        if self.cybot: self.cybot.send(cmd.encode('utf-8'))

class motion_controller_plugin(MotionControllerPlugin):
    def __init__(self):
        super().__init__()
        self.address = PluginSettingString("IP Address", "192.168.1.1")
        self.port = PluginSettingInteger("Port", 288)
        self.timeout = PluginSettingInteger("Timeout (ms)", 10000)
        self.add_setting_pre_connect(self.address)
        self.add_setting_pre_connect(self.port)
        self.add_setting_pre_connect(self.timeout)
        
        self.cybot = None
        self.read_thread_cond = False
        self._scan_event = threading.Event()
        self._latest_scan = None
        self.log_filename = "cybot_data_log.txt"

    def connect(self):
        try:
            self.cybot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cybot.settimeout(self.timeout.value / 1000)
            self.cybot.connect((self.address.value, self.port.value))
            self.read_thread_cond = True
            self.read_thread = threading.Thread(target=self.read_thread_interrupt, daemon=True)
            self.read_thread.start()
        except Exception as e:
            print(f"Failed to connect: {e}")

    def read_thread_interrupt(self):
        buffer = ""
        while self.read_thread_cond:
            try:
                raw = self.cybot.recv(1024)
                if not raw: break
                decoded = raw.decode('utf-8', errors='ignore')
                buffer += decoded
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    m = _SCAN_RE.search(line)
                    if m:
                        self._latest_scan = {'us': float(m.group(1)), 'ir': float(m.group(2)), 'angle': int(m.group(3))}
                        self._scan_event.set()
            except: continue

    def do_sweep_and_target(self):
        print("Starting Sweep 0-180...")
        scan_data = []
        # 1. Perform Sweep
        for angle in range(0, 181, 2):
            self.send_gcode_command(f"11{angle}")
            self._scan_event.clear()
            if self._scan_event.wait(timeout=2.0):
                scan_data.append(self._latest_scan.copy())

        # 2. Object Detection (Threshold < 100cm)
        objects = []
        current_obj = []
        for pt in scan_data:
            if pt['us'] < 100: # Detection threshold
                current_obj.append(pt)
            else:
                if len(current_obj) >= 2:
                    objects.append(current_obj)
                current_obj = []
        
        if not objects:
            print("No objects detected.")
            return

        # 3. Identify object with smallest angular width
        best_obj = None
        min_width = 999

        for obj in objects:
            width = obj[-1]['angle'] - obj[0]['angle']
            if width < min_width:
                min_width = width
                best_obj = obj

        # 4. Face the object
        if best_obj:
            mid_angle = (best_obj[0]['angle'] + best_obj[-1]['angle']) / 2
            # Assuming 90 is center/forward. Adjust rotation relative to center.
            # CyBot 'r' command usually handles rotation. 
            print(f"Smallest object at {mid_angle} deg (Width: {min_width}). Rotating...")
            
            # Use the rotation command logic from move_absolute
            # Calculate offset from current center (90)
            turn_angle = int(mid_angle - 90)
            self.send_gcode_command(f"11{turn_angle}")

    def home(self, axes=None):
        """Triggered by the GUI Scan/Home button."""
        threading.Thread(target=self.do_sweep_and_target, daemon=True).start()

    def send_gcode_command(self, command):
        if self.cybot:
            self.cybot.send((str(command) + "\n").encode('utf-8'))

    def move_absolute(self, move_dist: dict[int, float]):
        for key, val in move_dist.items():
            raw_value = int(abs(val))
            if key == 0: # Rotation
                # Command '10' followed by value (based on your original move_absolute)
                cmd = f"10{raw_value}"
                print(f"Rotating to object: {cmd}")
                self.send_gcode_command(cmd)
            elif key == 1: # Linear
                prefix = "01" if val < 0 else "00"
                self.send_gcode_command(f"{prefix}{raw_value}")

    def disconnect(self):
        self.read_thread_cond = False
        if self.cybot: self.cybot.close()

    # Stub implementations for base class requirements
    def get_axis_display_names(self): return ("Rotation", "Travel")
    def get_axis_units(self): return ("deg", "mm")
    def set_velocity(self, v=None): pass
    def set_acceleration(self, a=None): pass
    def move_relative(self, p=None): pass
    def get_current_positions(self): return (0.0, 0.0)
    def is_moving(self, a=None): return False
    def get_endstop_minimums(self): return (0.0, 0.0)
    def get_endstop_maximums(self): return (180.0, 1000.0)
    def emergency_stop(self):
        return super().emergency_stop()
    def set_config(self, amps, idle_p, idle_time):
        return super().set_config(amps, idle_p, idle_time)
    