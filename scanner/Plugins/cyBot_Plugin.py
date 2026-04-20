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
import math
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
        self.ok_received = threading.Event()
        
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
                    
                    if "OK" in decoded_data:
                        print("Robot confirmed: Path clear, no corrections made.")
                        self.ok_received.set() 
                    
                    # Check for collision/correction flag (if your robot sends one)
                    elif "CORRECTION" in decoded_data:
                        print("Warning: Robot made a course correction.")
                        
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
                prefix = "rr" if is_negative else "rl"
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
            if prefix == 'rl':
                command_buffer_2 = "10"+raw_value_str 
            if prefix == 'rr':
                command_buffer_2 = "11" + raw_value_str
                
            print(f"sending this command: {command_buffer_2}")
            self.send_gcode_command(command_buffer_2)


    def create_grid(self, anchorsx: list[float], anchorsy: list[float], targetx: float, targety: float, hqx: float, hqy: float):
        """
        Generates a 1mm grid and calculates the polar trajectory from HQ to Target.
        """
        if len(anchorsx) < 3 or len(anchorsy) < 3:
            raise ValueError("Three anchors are required.")

        # --- 1. Grid Generation Logic (Vector-Based) ---
        ox, oy = anchorsx[0], anchorsy[0] # The Origin corner
        
        # Vectors to the other two anchors (creating the sides of the grid)
        v1_x, v1_y = anchorsx[1] - ox, anchorsy[1] - oy
        v2_x, v2_y = anchorsx[2] - ox, anchorsy[2] - oy

        # Distances
        dist_1 = math.sqrt(v1_x**2 + v1_y**2)
        dist_2 = math.sqrt(v2_x**2 + v2_y**2)

        # 1mm step vectors (Normalize)
        step1_x, step1_y = v1_x / dist_1, v1_y / dist_1
        step2_x, step2_y = v2_x / dist_2, v2_y / dist_2

        num_steps1 = int(dist_1) + 1
        num_steps2 = int(dist_2) + 1

        grid = []
        all_points_flat = [] # Flat list useful for plotting

        for i in range(num_steps1):
            row = []
            for j in range(num_steps2):
                # Calculate: Origin + (i * step1_vector) + (j * step2_vector)
                px = ox + (i * step1_x) + (j * step2_x)
                py = oy + (i * step1_y) + (j * step2_y)
                
                point = (round(px, 3), round(py, 3))
                row.append(point)
                all_points_flat.append(point)
            grid.append(row)

        # --- 2. Trajectory Logic (HQ to Target, Polar in Degrees) ---
        dx = targetx - hqx
        dy = targety - hqy

        # Radius (mm)
        radius = math.sqrt(dx**2 + dy**2)

        # Angle in Degrees (0° is East, 90° is North)
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        return grid, (radius, angle_deg), all_points_flat

    def visualize(self, anchorsx, anchorsy, target, hq, grid_points_flat):
        """
        Plots the anchors, grid, HQ, Target, and the resulting vector.
        """
        plt.figure(figsize=(10, 10))
        ax = plt.gca() # Get current axes

        # 1. Plot the Grid Points (small grey dots)
        gx, gy = zip(*grid_points_flat) if grid_points_flat else ([],[])
        plt.scatter(gx, gy, color='lightgrey', s=1, label='1mm Grid')

        # 2. Plot Anchors (Large Black X's)
        # We connect them to visualize the right-angle shape
        plt.plot(anchorsx, anchorsy, 'kX-', markersize=10, label='Anchors (A0 corner)')
        for i in range(len(anchorsx)):
            plt.text(anchorsx[i], anchorsy[i], f'A{i}', fontsize=12, fontweight='bold')

        # 3. Plot HQ (Blue Circle)
        plt.plot(hq[0], hq[1], 'bo', markersize=10, label='HQ')
        
        # 4. Plot Target (Red Star)
        plt.plot(target[0], target[1], 'r*', markersize=15, label='Target')

        # 5. Plot the Trajectory Vector (Arrow from HQ to Target)
        # Using annotate makes drawing an arrow very clean
        plt.annotate('', xy=(target[0], target[1]), xytext=(hq[0], hq[1]),
                    arrowprops=dict(facecolor='blue', shrink=0.05, width=2, headwidth=8))

        # --- Plot Styling ---
        plt.title('Grid and HQ-to-Target Trajectory', fontsize=16)
        plt.xlabel('X (mm)', fontsize=12)
        plt.ylabel('Y (mm)', fontsize=12)
        
        plt.axis('equal') 
        
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)
        plt.legend(loc='upper right')
        
        print("Displaying plot... (Close window to continue)")
        plt.show()
    
    def execute_trajectory(self, radius: float, angle_deg: float):
        """
        Executes trajectory in 100mm increments, waiting for the robot's OK flag
        after each segment before proceeding.
        """
        # 1. Handle Rotation
        self.ok_received.clear()
        target_angle = int(angle_deg)
        self.send_gcode_command(f"10{target_angle:03d}")
        
        # Wait for rotation to finish
        print(f"Waiting for OK after rotating to {target_angle}...")
        self.ok_received.wait(timeout=5.0) 

        # 2. Incremental Movement
        remaining_dist = radius
        step_size = 100.0

        while remaining_dist > 0:
            current_step = min(remaining_dist, step_size)
            
            # Reset flag and send move command
            self.ok_received.clear()
            command = f"00{int(current_step):03d}"
            print(f"Moving {current_step}mm... Waiting for robot OK.")
            self.send_gcode_command(command)


            if not self.ok_received.wait(timeout=10.0):
                print("Error: Timed out waiting for OK from robot. Potential collision or loss of signal.")
                break

            remaining_dist -= current_step

        print("Trajectory sequence finished.")
    
        
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
        
        
        pass
            # prefix = "11"
            # angles = []
            # avg_ir_raw = []
            # avg_distance_cm = []
            
            # print("Starting Scan")
            
            # for i in range(0, 181, 10): 
            #     command = f"{prefix}{i:03d}" 
            #     print(f"Moving to angle: {i}")
            #     self.send_gcode_command(command)
                
                
            #     time.sleep(0.7) 
                
            #     raw_samples = []
            #     cm_samples = []

            #     # Collect 5 measurements
            #     while len(raw_samples) < 5:
            #         raw_val = self.get_latest_ir_from_log()
            #         if raw_val is not None:
            #             raw_samples.append(raw_val)
            #             cm_samples.append(self.ir_to_cm(raw_val))
            #         time.sleep(0.1) 

                
            #     mean_raw = sum(raw_samples) / 5
            #     mean_cm = sum(cm_samples) / 5
                
            #     angles.append(i)
            #     avg_ir_raw.append(mean_raw)
            #     avg_distance_cm.append(mean_cm)
                
            #     print(f"Angle {i} -> Raw: {mean_raw:.1f}, Dist: {mean_cm:.2f} cm")

            # self.plot_scan_results(angles, avg_ir_raw)
            # self.plot_distance_results(angles, avg_distance_cm)
            # obj = self.analyze_data(angles, avg_distance_cm)
            # self.smallest_obj(obj)
            
            
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