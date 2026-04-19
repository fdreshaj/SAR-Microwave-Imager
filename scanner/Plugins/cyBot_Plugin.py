import socket
import threading
import os
import time 
from datetime import datetime
from scanner.probe_controller import ProbePlugin
from scanner.plugin_setting import PluginSettingString, PluginSettingInteger
from scanner.motion_controller import MotionControllerPlugin
import statistics   
import matplotlib.pyplot as plt
class cyBot_Plugin(ProbePlugin):
    def __init__(self):
        super().__init__()
        self.cybot = None
        self.read_thread = None
        self.read_thread_cond = False
        
        # Settings
        self.address = PluginSettingString("IP Address", "192.168.1.1")
        self.port = PluginSettingInteger("Port", 288)
        self.timeout = PluginSettingInteger("Timeout (ms)", 10000)
        
        self.add_setting_pre_connect(self.address)
        self.add_setting_pre_connect(self.port)
        self.add_setting_pre_connect(self.timeout)

        # File Logging Setup
        self.log_filename = "cybot_data_log.txt"

    def connect(self):
        try:
            self.cybot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.cybot.settimeout(self.timeout.value / 1000)
            self.cybot.connect((self.address.value, self.port.value))
            
            print(f"Connected to cyBot at {self.address.value}:{self.port.value}")
            
            # Start the "Interrupt" Thread
            self.read_thread_cond = True
            self.read_thread = threading.Thread(target=self.read_thread_interrupt, daemon=True)
            self.read_thread.start()
            
        except Exception as e:
            print(f"Failed to connect to cyBot: {e}")
            self.cybot = None

    def read_thread_interrupt(self):
        """
        Acts as the interrupt handler. Continuously polls the socket
        and logs data to both console and text file.
        """
        print(f"Logging started. Saving to {self.log_filename}")
        
        # Open file in append mode ('a')
        with open(self.log_filename, "a") as f:
            f.write(f"\n--- Session Started: {datetime.now()} ---\n")
            
            while self.read_thread_cond:
                try:
                    
                    data = self.cybot.recv(1024)
                    
                    if data:
                        
                        decoded_data = data.decode('utf-8', errors='ignore').strip()
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        log_entry = f"[{timestamp}] RX: {decoded_data}"

                        print(log_entry)
                        
                        f.write(log_entry + "\n")
                        f.flush()
                    else:
                       
                        break

                except socket.timeout:
                    continue 
                except Exception as e:
                    if self.read_thread_cond:
                        print(f"Read Error: {e}")
                    break
                    
        print("Logging thread stopped.")

    def disconnect(self):
        self.read_thread_cond = False
        
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        
        if self.cybot:
            try:
                self.cybot.close()
            except:
                pass
            print("Disconnected from cyBot.")

    def send_command(self, cmd):
        if self.cybot:
            self.cybot.send(cmd.encode('utf-8'))
            
    def get_channel_names(self):
        return super().get_channel_names()
    def get_xaxis_coords(self):
        return super().get_xaxis_coords()
    def get_xaxis_units(self):
        return super().get_xaxis_units()
    
    def get_yaxis_units(self):
        return super().get_yaxis_units()

    def scan_begin(self):
        return super().scan_begin()
    def scan_end(self):
        return super().scan_end()
    def scan_read_measurement(self, scan_index, scan_location):
        return super().scan_read_measurement(scan_index, scan_location)
    
    def scan_trigger_and_wait(self, scan_index, scan_location):
        return super().scan_trigger_and_wait(scan_index, scan_location)
class motion_controller_plugin(MotionControllerPlugin):
    def __init__(self):
        super().__init__()

        # Scanner type selection for boundary checking
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
            
            print(f"Connected to cyBot at {self.address.value}:{self.port.value}")
            
            self.read_thread_cond = True
            self.read_thread = threading.Thread(target=self.read_thread_interrupt, daemon=True)
            self.read_thread.start()
            
        except Exception as e:
            print(f"Failed to connect to cyBot: {e}")
            self.cybot = None
    def read_thread_interrupt(self):
        print(f"Logging started. Saving to {self.log_filename}")
        with open(self.log_filename, "a") as f:
            f.write(f"\n--- Session Started: {datetime.now()} ---\n")
            
            while self.read_thread_cond:
                try:
                    data = self.cybot.recv(1024)
                    if not data: break
                    
                    decoded_data = data.decode('utf-8', errors='ignore').strip()
                    
                    # Logic to parse the specific C-formatted string
                    if "Data:" in decoded_data:
                        # "Data: Ultrasound 50.0 , IR 1200.0 , Angle 90"
                        try:
                            parts = decoded_data.split(",")
                            u_dist = float(parts[0].split("Ultrasound")[1].strip())
                            ir_val = float(parts[1].split("IR")[1].strip())
                            angle = int(parts[2].split("Angle")[1].strip())
                            
                            print(f"Parsed: Angle {angle} -> Dist: {u_dist}")
                        except Exception as parse_err:
                            print(f"Parse error: {parse_err}")

                    
                    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    log_entry = f"[{timestamp}] RX: {decoded_data}"
                    f.write(log_entry + "\n")
                    f.flush()

                except socket.timeout:
                    continue 
                except Exception as e:
                    break   
    

    def disconnect(self):
        self.read_thread_cond = False
        
        if self.read_thread:
            self.read_thread.join(timeout=2.0)
        
        if self.cybot:
            try:
                self.cybot.close()
            except:
                pass
            print("Disconnected from cyBot.")
    
    def get_axis_display_names(self) -> tuple[str, ...]:
        pass
    
    def get_axis_units(self) -> tuple[str, ...]:
        pass

    
    def set_velocity(self, velocities: dict[int, float] = None) -> None:
        pass
 
    def set_acceleration(self, accels: dict[int, float] = None) -> None:
        pass
    
    def apply_adc_averaging(fp, window_size=5):
        raw_values = []
        try:
            with open(fp, 'r') as f:
                for line in f:
                    if "Data:" in line:
                        parts = line.split("Data:")[1]
                        if len(parts)>1:
                            try:
                                value = float(parts[1].strip().split()[0])
                                raw_values.append(value)
                            except Exception as e:
                                print(f"Error occurred while reading file: {e}")
            if len(raw_values) < window_size:
                print("Not enough data points for averaging.")
                return None
            smoothed_data =[]
            for i in range(len(raw_values)):
                start_index = max(0, i - window_size + 1)
                window = raw_values[start_index:i + 1]
                average = sum(window) / len(window)
                smoothed_data.append(round(average, 4))
            return smoothed_data
        except Exception as e:
            print(f"Error occurred while reading file: {e}")
            return None

    def move_absolute(self, move_dist: dict[int, float]) -> dict[int, float] | None:
        for key, val in move_dist.items():
            # Get absolute integer value for the command string
            raw_value = int(abs(val))
            raw_value_str = str(raw_value)
            is_negative = val < 0
            
            prefix = ""
            if key == 0:    # X Axis (Rotation)
                prefix = "r" if is_negative else "r"
            elif key == 1:  # Y Axis (movement)
                prefix = "mb" if is_negative else "mf"
            else:
                print(f"Warning: Unexpected dictionary key '{key}'.")
                continue

           
            command_buffer = f"{prefix}{raw_value}"
            if prefix == 'mf':
                command_buffer_2 = '00'+raw_value_str
            if prefix == 'mb':
                command_buffer_2 = '01'+raw_value_str 
            if prefix == 'r':
                command_buffer_2 = "10"+raw_value_str 
                
            print(f"sending this command: {command_buffer_2}")
            self.send_gcode_command(command_buffer_2)
            
            
            
    
        
    def move_relative(self, move_pos: dict[int, float]) -> dict[int, float] | None:
        pass
        
       
    def get_current_positions(self) -> tuple[float, ...]:
        pass
 
    def is_moving(self,axis=None) -> bool:
        
        pass
        
        
    def get_endstop_minimums(self) -> tuple[float, ...]:
        pass
    def get_endstop_maximums(self) -> tuple[float, ...]:
        pass
    def set_config(self, amps,idle_p, idle_time):
        pass
    
    
    def send_gcode_command(self, command):
        if isinstance(command, int):
            if self.cybot:
                command = str(command)
                
        if self.cybot:
            self.cybot.send((command + "\n").encode('utf-8'))
    def emergency_stop(self):
        pass
    
    

    def ir_to_cm(self, raw_adc):
   
        if raw_adc <= 0:
            return 80.0

        voltage = raw_adc * (3.3 / 4095.0)  

    
        if voltage < 0.4:
            return 80.0

        distance_cm = (1 / voltage) - 0.42

       
        return max(0.0, min(distance_cm, 80.0))
    def home(self, axes=None):
            prefix = "11"
            angles = []
            avg_ir_raw = []
            avg_distance_cm = []
            
            print("Starting Scan")
            
            for i in range(0, 181, 10): 
                command = f"{prefix}{i:03d}" 
                print(f"Moving to angle: {i}")
                self.send_gcode_command(command)
                
                
                time.sleep(0.7) 
                
                raw_samples = []
                cm_samples = []

                # Collect 5 measurements
                while len(raw_samples) < 5:
                    raw_val = self.get_latest_ir_from_log()
                    if raw_val is not None:
                        raw_samples.append(raw_val)
                        cm_samples.append(self.ir_to_cm(raw_val))
                    time.sleep(0.1) 

                
                mean_raw = sum(raw_samples) / 5
                mean_cm = sum(cm_samples) / 5
                
                angles.append(i)
                avg_ir_raw.append(mean_raw)
                avg_distance_cm.append(mean_cm)
                
                print(f"Angle {i} -> Raw: {mean_raw:.1f}, Dist: {mean_cm:.2f} cm")

            self.plot_scan_results(angles, avg_ir_raw)
            self.plot_distance_results(angles, avg_distance_cm)
            obj = self.analyze_data(angles, avg_distance_cm)
            self.smallest_obj(obj)
            
            
    def analyze_data(self, angles, avg_distance_cm):
        
        objects = []
        thresh = 50.0  
        object_indices = [] 

        for i in range(len(avg_distance_cm)):
            if avg_distance_cm[i] < thresh:
                object_indices.append(i)
            else:
                if len(object_indices) > 0:
                    objects.append(self._create_object_dict(object_indices, angles, avg_distance_cm))
                    object_indices = []

        if len(object_indices) > 0:
            objects.append(self._create_object_dict(object_indices, angles, avg_distance_cm))

        return objects

    def _create_object_dict(self, indices, angles, dists):
        import math
        """Helper to package the object data into a dictionary."""
        start_angle = angles[indices[0]]
        end_angle = angles[indices[-1]]
        center = (start_angle + end_angle) / 2
        
        # Width in degrees
        width_deg = end_angle - start_angle
        if width_deg == 0: width_deg = 2 
        
        avg_dist = sum(dists[i] for i in indices) / len(indices)
        linear_width = (avg_dist * math.pi * width_deg) / 180
        
        obj = {
            "center": center,
            "l_width": linear_width,
            "distance": min(dists[i] for i in indices)
        }
        print(f"Detected Object: Angle {center}°, Linear Width {linear_width:.2f}cm, Dist {obj['distance']:.2f}cm")
        return obj

    def smallest_obj(self, objects):
        # Always check if objects were found before using min()
        if not objects:
            print("No objects found to move to.")
            return

       
        smob = min(objects, key=lambda x: x['l_width'])
        
        tarang = int(smob['center'])
        tardist = int(max(0, smob['distance'] - 6)) # Move to dist minus 6cm
        
        print(f"Navigating to Pillar: {tarang} deg, {tardist} cm")
        self.send_gcode_command(f"10{tarang:03d}") # Rotate
        time.sleep(1.5)
        self.send_gcode_command(f"00{tardist:03d}") # Move Forward
    def smallest_obj(self, objects):
        if not objects:
            print("No objects found to move to.")
            return

        smob = min(objects, key=lambda x: x['l_width'])
        
        tarang = int(smob['center'])
        tardist = int(max(0, smob['distance'] - 6))
        
        print(f"Navigating to Pillar: {tarang} deg, {tardist} cm")
        self.send_gcode_command(f"10{tarang:03d}")   # Rotate
        time.sleep(1.5)
        self.send_gcode_command(f"00{tardist:03d}")  # Move Forward
            
            
    def plot_scan_results(self, angles, ir_values):
        
        plt.figure(figsize=(10, 6))
        plt.plot(angles, ir_values, marker='o', linestyle='-', color='b', label='Raw ADC')
        plt.title('CyBot Scan: Angle vs. Average IR Value (Raw)')
        plt.xlabel('Angle (Degrees)')
        plt.ylabel('Average IR Value (Raw/Filtered)')
        plt.grid(True, linestyle='--')
        
        plot_path = "scan_plot_raw.png"
        plt.savefig(plot_path)
        print(f"Raw plot saved to {plot_path}")
        plt.show()

    def plot_distance_results(self, angles, cm_values):
        
        plt.figure(figsize=(10, 6))
        plt.plot(angles, cm_values, marker='s', linestyle='--', color='r', label='Distance (cm)')
        plt.title('CyBot Scan: Angle vs. Distance (cm)')
        plt.xlabel('Angle (Degrees)')
        plt.ylabel('Distance (cm)')
        plt.grid(True, linestyle='--')
        
        plot_path = "scan_plot_cm.png"
        plt.savefig(plot_path)
        print(f"Distance plot saved to {plot_path}")
        plt.show()
        
    def get_latest_ir_from_log(self):
        
        try:
            with open(self.log_filename, "r") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    if "IR" in line:
                        return float(line.split("IR")[1].split(",")[0].strip())
        except: return None