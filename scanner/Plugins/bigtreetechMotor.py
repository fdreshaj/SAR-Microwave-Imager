#Gcode motion controller plugin for BigTreeTech motor controllers using PyVISA

from scanner.motion_controller import MotionControllerPlugin
from scanner.plugin_setting import PluginSettingString, PluginSettingInteger, PluginSettingFloat
import serial
from serial.tools import list_ports
import pyvisa
import threading

class motion_controller_plugin(MotionControllerPlugin):
    def __init__(self):
        super().__init__()

        # Scanner type selection for boundary checking
        self.scanner_type = PluginSettingString(
            "Scanner Type",
            "N-d Scanner",
            select_options=["Big Scanner", "N-d Scanner"],
            restrict_selections=True
        )

        self.add_setting_pre_connect(self.scanner_type)

        # Position tracking variables
        self.current_position = [0.0, 0.0, 0.0]  # [X, Y, Z]
        self.is_homed = False

        # Boundary limits based on scanner type
        self.x_min = 0.0
        self.x_max = 0.0
        self.y_min = 0.0
        self.y_max = 0.0
        self.z_min = 0.0
        self.z_max = 0.0

        self.rm = None
        self.driver = None
        self.resource_name = None
        self.timeout = 5000
        self.rm = pyvisa.ResourceManager()
        print("PyVISA ResourceManager initialized.")
        self.devices = self.rm.list_resources()
        
    def connect(self):
        """
        Connect to GCODE motion controller with auto-detection.
        Loops through available VISA devices until a GCODE device responds.
        """

        # Set boundary limits based on scanner type
        scanner_type_str = self.scanner_type.value
        if scanner_type_str == "Big Scanner":
            # Big Scanner: 600x600 mm (X, Y only)
            self.x_min = 0.0
            self.x_max = 600.0
            self.y_min = 0.0
            self.y_max = 600.0
            self.z_min = 0.0
            self.z_max = 0.0  # No Z axis for Big Scanner
            print("Scanner boundaries set: Big Scanner (600x600 mm, X-Y only)")
        else:  # "N-d Scanner"
            # N-d Scanner: 300x300x300 mm cube
            self.x_min = 0.0
            self.x_max = 300.0
            self.y_min = 0.0
            self.y_max = 300.0
            self.z_min = 0.0
            self.z_max = 300.0
            print("Scanner boundaries set: N-d Scanner (300x300x300 mm cube)")

        self.timeout = 1000
        # Auto-detect GCODE device by trying all VISA resources
        if not self.devices:
            raise ConnectionError("No VISA devices found on system")

        print(f"\nAttempting to auto-detect GCODE device on {len(self.devices)} available VISA resource(s)...")
        print("Found the following VISA devices:")
        for device in self.devices:
            print(f"  - {device}")

        connected = False
        last_error = None

        # Loop through all VISA devices until GCODE device found
        for device in self.devices:
            try:
                print(f"\n  Trying {device}...")

                # Attempt to open VISA resource
                test_driver = self.rm.open_resource(device)
                test_driver.timeout = self.timeout

                # Send a test GCODE command to verify it's a GCODE device
                # G91 sets relative positioning - a safe, standard GCODE command
                test_driver.write("M115\n")  # Request firmware info
                response = test_driver.read()

                # Check if we got a valid GCODE response (contains "ok" or firmware info)
                if "ok" in response.lower() or "firmware" in response.lower():
                    print(f"  ✓ GCODE device detected on {device}")
                    self.driver = test_driver
                    self.resource_name = device
                    connected = True
                    break
                else:
                    # Not a GCODE device
                    test_driver.close()
                    print(f"  ✗ Not a GCODE device (unexpected response: {response[:50]})")

            except (pyvisa.errors.VisaIOError, Exception) as e:
                last_error = e
                print(f"  ✗ Failed to connect: {e}")
                try:
                    test_driver.close()
                except:
                    pass
                continue

        if not connected:
            error_msg = f"Failed to detect GCODE device on any available VISA resource. Last error: {last_error}"
            print(f"\n✗ {error_msg}")
            raise ConnectionError(error_msg)

        print(f"\n✓ Successfully connected to GCODE device: {self.resource_name}")
        print(f"Communication timeout set to {self.timeout} ms.")
        test_driver.timeout = 5000
        # Set to relative positioning mode
        response = self.send_gcode_command("G91")
        
        
        
    def disconnect(self):
        self.driver.close()
        print(f"Connection to {self.resource_name} closed.")
        self.driver = None
    
    
    def get_axis_display_names(self) -> tuple[str, ...]:
        pass
    
    def get_axis_units(self) -> tuple[str, ...]:
        pass

    
    def set_velocity(self, velocities: dict[int, float] = None) -> None:
        pass
 
    def set_acceleration(self, accels: dict[int, float] = None) -> None:
        pass


    def move_absolute(self, move_dist: dict[int, float]) -> dict[int, float] | None:
        
        if not self.is_homed:
            raise RuntimeError("Motors must be homed before movement to establish a coordinate system.")

        
        for axis_idx, delta in move_dist.items():
            new_potential_pos = self.current_position[axis_idx] + delta
            
            if axis_idx == 0:  # X axis
                if new_potential_pos < self.x_min or new_potential_pos > self.x_max:
                    raise ValueError(f"LIMIT VIOLATION: X move of {delta} would reach {new_potential_pos}, exceeding [{self.x_min}, {self.x_max}]")
            elif axis_idx == 1:  # Y axis
                if new_potential_pos < self.y_min or new_potential_pos > self.y_max:
                    raise ValueError(f"LIMIT VIOLATION: Y move of {delta} would reach {new_potential_pos}, exceeding [{self.y_min}, {self.y_max}]")
            elif axis_idx == 2:  # Z axis
                if new_potential_pos < self.z_min or new_potential_pos > self.z_max:
                    raise ValueError(f"LIMIT VIOLATION: Z move of {delta} would reach {new_potential_pos}, exceeding [{self.z_min}, {self.z_max}]")

        
        for axis_idx, delta in move_dist.items():
            axis_map = {0: 'X', 1: 'Y', 2: 'Z'}
            if axis_idx in axis_map:
                
                
                move_command = f"G0 {axis_map[axis_idx]}{delta} F1000" 
                self.send_gcode_command(move_command)
                movement = self.is_moving()
                print(movement)
                while movement[0] == True:
                    movement= self.is_moving()
                    print(movement)
               
                self.current_position[axis_idx] += delta

        print(f"Position updated (Relative): X={self.current_position[0]:.2f}, Y={self.current_position[1]:.2f}, Z={self.current_position[2]:.2f}")
        return {i: self.current_position[i] for i in range(3)}
     
    def move_relative(self, move_pos: dict[int, float]) -> dict[int, float] | None:
        # split_response = self.get_current_positions()
        
        # if self.response == 'ok':
        #     print("response ok, need to retry to get actual position  ")
        #     split_response = self.get_current_positions()
            
        # else:
        #     print("got position")
        
       
        # z = float(split_response[2][2:])
        

        
        
        
        # if not self.is_homed:
        #     raise RuntimeError("Motors must be homed before absolute movement. Call home() first.")

        # if not isinstance(move_pos, dict) or not move_pos:
        #     raise ValueError("Error: Input must be a non-empty dictionary.")

        # # Check boundaries BEFORE executing movement
        # for axis_idx, target_pos in move_pos.items():
        #     if axis_idx == 0:  # X axis
        #         if target_pos < self.x_min or target_pos > self.x_max:
        #             raise ValueError(
        #                 f"ENDSTOP VIOLATION: X-axis movement to {target_pos:.2f} mm "
        #                 f"exceeds boundaries [{self.x_min:.2f}, {self.x_max:.2f}] mm. "
        #                 f"Command stopped."
        #             )
        #     elif axis_idx == 1:  # Y axis
        #         if target_pos < self.y_min or target_pos > self.y_max:
        #             raise ValueError(
        #                 f"ENDSTOP VIOLATION: Y-axis movement to {target_pos:.2f} mm "
        #                 f"exceeds boundaries [{self.y_min:.2f}, {self.y_max:.2f}] mm. "
        #                 f"Command stopped."
        #             )
        #     elif axis_idx == 2:  # Z axis
        #         if target_pos < self.z_min or target_pos > self.z_max:
        #             raise ValueError(
        #                 f"ENDSTOP VIOLATION: Z-axis movement to {target_pos:.2f} mm "
        #                 f"exceeds boundaries [{self.z_min:.2f}, {self.z_max:.2f}] mm. "
        #                 f"Command stopped."
        #             )

        # # Execute movements for each axis
        # for axis_idx, target_pos in move_pos.items():
        #     if axis_idx not in [0, 1, 2]:
        #         print(f"Warning: Unexpected axis index '{axis_idx}'. Skipping.")
        #         continue

        #     raw_value = int(target_pos)

        #     if axis_idx == 0:
        #         move_command = f"G0 X{raw_value}"
        #     elif axis_idx == 1:
        #         move_command = f"G0 Y{raw_value}"
        #     elif axis_idx == 2:
        #         move_command = f"G0 Z{raw_value}"

        #     # Send GCODE command
        #     self.response = self.send_gcode_command(move_command)

        #     # Wait for movement to complete
        #     movement = self.is_moving()
        #     print(movement)
        #     while movement[0] == True:
        #         movement = self.is_moving()
        #         print(movement)

        # # Only update tracked positions after ALL movements complete successfully
        # for axis_idx, target_pos in move_pos.items():
        #     if axis_idx in [0, 1, 2]:
        #         self.current_position[axis_idx] = target_pos

        # print(f"Position updated: X={self.current_position[0]:.2f}, Y={self.current_position[1]:.2f}, Z={self.current_position[2]:.2f}")
        pass

    def get_current_positions(self) -> tuple[float, ...]:
        """
        Return current tracked positions.

        Returns:
            tuple: (x, y, z) positions in mm
        """
        return tuple(self.current_position)
 
    def is_moving(self,axis=None) -> bool:
        
        movement=[True,True,True]
        res = self.send_gcode_command("M400") 
        print("/////")
        
        
        if res == 'ok':
        
            movement[0] = False
            movement[1] = False
            movement[2] = False
        

        return movement
        
        
    def get_endstop_minimums(self) -> tuple[float, ...]:
        """Return minimum position limits for all axes."""
        return (self.x_min, self.y_min, self.z_min)

    def get_endstop_maximums(self) -> tuple[float, ...]:
        """Return maximum position limits for all axes."""
        return (self.x_max, self.y_max, self.z_max)
    
    def set_config(self, amps,idle_p, idle_time):
        pass
    
    
    def send_gcode_command(self, command):
    
        if not self.driver:
            print("Not connected to a device. Please call connect() first.")
            return None

        
        # if not command.endswith('\n'):
        #     command += '\n'

        q_response = None
        try:
            print(f"Sending G-code command: '{command.strip()}'")
          
            q_response = self.driver.query(command)
            print(f"Received response: '{q_response.strip()}'")
            while q_response.strip() != 'ok':
                q_response = self.driver.read()
                print(f"{q_response.strip()}")

            return q_response.strip()
            

        except pyvisa.errors.VisaIOError as e:
            print(f"VISA I/O Error during command '{command.strip()}': {e}")
        except Exception as e:
            print(f"An unexpected error occurred while sending command: {e}")
        return None
    
    def emergency_stop(self):
        print("EMERGENCY STOP ACTIVATED! Sending M112 to halt all motion immediately.")
        self.send_gcode_command("M112")
        print("All motion should now be stopped. Please check the device and reset if necessary.")


    def home(self, axes=None):
        """
        Home the specified axes and initialize position tracking.

        After homing:
        - Big Scanner: Position is (0, 0, 0)
        - N-d Scanner: Position is (0, 0, 300) - Z starts at top

        Args:
            axes: List of axis indices to home (e.g., [0, 1, 2])

        Returns:
            Dictionary of homed positions
        """
        # Uncomment back after done testing
        if axes is None:
            axes = [0, 1, 2]  # Home all axes by default

        print(f"Homing axes {axes}")
        response = self.send_gcode_command("G28")

        # Wait for homing to complete
        movement = self.is_moving()
        while movement[0] == True:
            movement = self.is_moving()

        # # Set initial position based on scanner type
        scanner_type_str = self.scanner_type.value
        if scanner_type_str == "N-d Scanner":
            # N-d Scanner: Z starts at 300 mm (top of cube)
            self.current_position = [0.0, 0.0, 300.0]
            print("Homing complete. Position initialized to (0, 0, 300) mm")
        else:
            # Big Scanner: All axes at 0
            self.current_position = [0.0, 0.0, 0.0]
            print("Homing complete. Position initialized to (0, 0, 0) mm")

        self.is_homed = True

        if scanner_type_str == "N-d Scanner":
            
            self.move_absolute({0:150,1:150})
            
        else:
            # Big Scanner: All axes at 0
            self.move_absolute({0:300,1:300})
            



        return {axis: self.current_position[axis] for axis in axes}
    def show_radar(self):
        return super().show_radar() 