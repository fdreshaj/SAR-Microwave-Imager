
## IMPORTS 
#region Imports
import os
from scanner.plugin_setting import PluginSettingString, PluginSettingInteger, PluginSettingFloat
from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
import tkinter as tk
from tkinter import simpledialog
from tkinter import filedialog as fd
from tkinter import messagebox
import threading
from gui.scanner_qt import ScannerQt
from gui.ui_scanner import Ui_MainWindow
from gui.qt_util import QPluginSetting
import gui.select_plot_style as select_plot_style
import gui.select_plot_hide as select_plot_hide
import raster_pattern_generator as scan_pattern_gen
import numpy as np
import matplotlib
import qdarktheme
import datetime
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolButton
from PySide6.QtWidgets import QWidget, QHBoxLayout
matplotlib.use('QtAgg') 
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas 
from matplotlib.figure import Figure
from  gui.plotter import plotter_system
from scanner.scan_pattern_1 import ScanPattern
from scanner.scan_pattern_controller import ScanPatternControllerPlugin
from scanner.scan_file_1 import ScanFile
from scanner.cam_testing_2 import CameraApp as CameraApp
import time     
from PySide6.QtWidgets import QToolButton, QDialog, QVBoxLayout, QLabel
from scanner.Signal_Scope import SignalScope 
from scanner.S_param_visualizer import VisualizerWindow
from scanner.step_file_importer import ndwindow
import shutil
import webbrowser
#endregion

class MainWindow(QMainWindow):
    scanner: ScannerQt
    ui: Ui_MainWindow
    pluginChosen_probe = False
    pluginChosen_motion = False

    # Debug mode for testing disk space validation
    # Set to True to simulate low disk space scenarios
    DEBUG_DISK_SPACE_TEST = False
    DEBUG_SIMULATED_DISK_SPACE_MB = 5  # Simulated available space in MB

    ## SETUP FUNCTIONS
    #region Setup
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Initialize Signal Scope (hidden by default)
        self.signal_scope = SignalScope()

        self.scanner = ScannerQt(signal_scope=self.signal_scope)
        self.plotter = plotter_system()
        self.back_btn_check = False
        self.scan_controller = ScanPattern()
        self.file_controller = ScanFile()
        self.motion_config_counter = 0
        self.current_theme = "dark"
        self.camera_app = None  # Will be set when camera is opened
        self.setup_theme_toggle()
        self.setup_settings_button()
        self.setup_top_controls()
        app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
        try:
            self.setup_plotting_canvas()
            self.setup_connections()
            self.show()
        except:
            self.scanner.close()
            raise
    
    def setup_connections(self) -> None:
        self.ui.xy_move_amount.valueChanged.connect(self.scanner.set_xy_move)
        self.ui.z_move_amount.valueChanged.connect(self.scanner.set_z_move)
        self.scanner.set_xy_move(self.ui.xy_move_amount.value())
        self.scanner.set_z_move(self.ui.z_move_amount.value())

        self.ui.x_plus_button.clicked.connect(self.scanner.clicked_move_x_plus)
        self.ui.x_minus_button.clicked.connect(self.scanner.clicked_move_x_minus)
        self.ui.y_plus_button.clicked.connect(self.scanner.clicked_move_y_plus)
        self.ui.y_minus_button.clicked.connect(self.scanner.clicked_move_y_minus)
        self.ui.z_plus_button.clicked.connect(self.scanner.clicked_move_z_plus)
        self.ui.z_minus_button.clicked.connect(self.scanner.clicked_move_z_minus)
        
        self.ui.configure_motion_button.clicked.connect(self.configure_pressed)
        self.ui.configure_probe_button.clicked.connect(self.configure_pressed)
        self.ui.configure_pattern_button.clicked.connect(self.configure_pressed)
        self.ui.configure_file_button.clicked.connect(self.configure_pressed)

        self.ui.configure_motion_button.clicked.connect(self.configure_motion)
        self.ui.configure_probe_button.clicked.connect(self.configure_probe)
        self.ui.configure_pattern_button.clicked.connect(self.configure_pattern)
        self.ui.configure_file_button.clicked.connect(self.configure_file)

        # Connect start scan button to run scan function
        self.ui.start_scan_button.clicked.connect(self.test_scan_bt)
        

        self.scanner.current_position_x.connect(self.ui.x_axis_slider.setSliderPosition)
        self.scanner.current_position_y.connect(self.ui.y_axis_slider.setSliderPosition)
        self.scanner.current_position_z.connect(self.ui.z_axis_slider.setSliderPosition)

        self.display_timer = QTimer()
        self.display_timer.setInterval(1000 // 60)
        # Don't update motion continuously - only on movement commands
        # self.display_timer.timeout.connect(self.scanner.update_motion)
        self.display_timer.start()
    #endregion
    
    
    
    ## CONFIG M/P/SP/SF 
    #region config functions
    @Slot(bool)
    def configure_pressed(self, was_selected: bool) -> None:
        self.sender().blockSignals(True)
        self.ui.configure_motion_button.setChecked(False)
        self.ui.configure_probe_button.setChecked(False)
        self.ui.configure_pattern_button.setChecked(False)
        self.ui.configure_file_button.setChecked(False)
        self.sender().setChecked(was_selected)
        self.sender().blockSignals(False)
        
    @Slot(bool)
    def configure_motion(self, was_selected: bool) -> None:

        if was_selected:
            # Check if a plugin has been selected yet
            from scanner.plugin_switcher_motion import PluginSwitcherMotion

            if PluginSwitcherMotion.plugin_name == "":
                # No plugin selected - show file dialog
                if PluginSwitcherMotion.select_plugin():
                    # Plugin was selected, swap to it
                    self.scanner.scanner.swap_motion_plugin()
                    self.pluginChosen_motion = True
                else:
                    # User cancelled - uncheck the configure button
                    self.ui.configure_motion_button.setChecked(False)
                    return

            # Now show the configuration UI
            controller = self.scanner.scanner.motion_controller
            self.set_configuration_settings_motion(controller._driver, controller.is_connected(), self.connect_motion, self.disconnect_motion)

        else:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                self.ui.config_layout.removeRow(i)
    
    @Slot(bool)
    def configure_probe(self, was_selected: bool) -> None:
        if was_selected:
            # Check if a plugin has been selected yet
            from scanner.plugin_switcher import PluginSwitcher

            if PluginSwitcher.plugin_name == "":
                # No plugin selected - show file dialog
                if PluginSwitcher.select_plugin():
                    # Plugin was selected, swap to it
                    self.scanner.scanner.swap_probe_plugin()
                    self.pluginChosen_probe = True
                else:
                    # User cancelled - uncheck the configure button
                    self.ui.configure_probe_button.setChecked(False)
                    return

            
            controller = self.scanner.scanner.probe_controller
            self.set_configuration_settings_probe(controller._probe, controller.is_connected(), self.connect_probe, self.disconnect_probe)
        else:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                self.ui.config_layout.removeRow(i)


        self.back_btn_check = False
    
    @Slot(bool)
    def configure_pattern(self, was_selected: bool) -> None:
        if was_selected:               
            
            connected = self.scan_controller.is_connected()
            self.set_configuration_setting_pattern(connected)
        else:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                self.ui.config_layout.removeRow(i)

        
        

    @Slot(bool)
    def configure_file(self, was_selected: bool) -> None:
        if was_selected:
            connected = self.file_controller.is_connected()
            self.set_configuration_setting_file(connected)
                
        else:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                self.ui.config_layout.removeRow(i)
    
    #endregion
    
    
    
    #####
    #
    #     
    #####
    ## CONFIG SETTINGS M/P/SP/SF
    #region config settings
    def set_configuration_setting_file(self,connected):
        
        self.file_display_label_text =[]
        if connected == True:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                    self.ui.config_layout.removeRow(i)
            for setting in self.file_controller.settings_pre_connect:
                    plug = QPluginSetting(setting)
                    plug.setDisabled(True)
                    self.ui.config_layout.addRow(setting.display_label, plug)
                    self.file_display_label_text.append(f"{setting.display_label}")
                    
            for setting in self.file_controller.settings_post_connect:
                    
                    #PluginSettingString.set_value_from_string(self.file_controller.file_directory,f"{self.file_directory}")
                    plug = QPluginSetting(setting)
                    
                    self.ui.config_layout.addRow(setting.display_label, plug)
                
            go_back_file = QPushButton("Back")
            go_back_file.clicked.connect(self.go_back_file)
            self.ui.config_layout.addRow(go_back_file)

            pause_btn = QPushButton("Pause Scan")
            pause_btn.clicked.connect(self.pause_scan)
            self.ui.config_layout.addRow(pause_btn)  
        
        else:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                    self.ui.config_layout.removeRow(i)
            for setting in self.file_controller.settings_pre_connect:
                        self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))
            get_file_dir = QPushButton("Choose File Directory")
            get_file_dir.clicked.connect(self.get_file_dir)
            self.ui.config_layout.addRow(get_file_dir)

            finish_config = QPushButton("Finish Config")
            finish_config.clicked.connect(self.finish_config)
            self.ui.config_layout.addRow(finish_config)

            camera_pop_up = QPushButton("Camera Pop Up")
            camera_pop_up.clicked.connect(self.camera_pop_up)
            self.ui.config_layout.addRow(camera_pop_up)

            

            
            
            
            
    def camera_pop_up(self):
        root = tk.Tk()
        self.camera_app = CameraApp(root)
        root.mainloop()
    def set_configuration_settings_motion(self, controller, connected, connect_function, disconnect_function):
        """Configure motion controller settings UI - SIMPLIFIED VERSION."""
        # Clear the config layout
        for i in reversed(range(self.ui.config_layout.rowCount())):
            self.ui.config_layout.removeRow(i)

        if connected:
            # Motion controller is connected - show settings and controls
            self.settings_motion_list = []

            # Show pre-connect settings (disabled, just for display)
            for setting in controller.settings_pre_connect:
                plug = QPluginSetting(setting)
                plug.setDisabled(True)
                self.ui.config_layout.addRow(setting.display_label, plug)
                # Save values for later use
                self.settings_motion_list.append(PluginSettingFloat.get_value_as_string(setting))

            # Disconnect button
            disconnect_button = QPushButton("Disconnect")
            disconnect_button.clicked.connect(disconnect_function)
            self.ui.config_layout.addRow(disconnect_button)

            # Post-connect settings (editable)
            for setting in controller.settings_post_connect:
                self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))

            # Add utility buttons
            self.scan_testing()
            self.home_button()

            # Back button for resetting plugin selection
            back_btn = QPushButton("Reset Plugin")
            back_btn.clicked.connect(self.back_function_motion)
            self.ui.config_layout.addRow(back_btn)

        else:
            # Motion controller not connected - show connection UI
            # Pre-connect settings (editable before connection)
            for setting in controller.settings_pre_connect:
                self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))

            # Connect button
            connect_button = QPushButton("Connect")
            connect_button.clicked.connect(connect_function)
            self.ui.config_layout.addRow(connect_button)

            # Post-connect settings (disabled until connected)
            for setting in controller.settings_post_connect:
                plug = QPluginSetting(setting)
                plug.setDisabled(True)
                self.ui.config_layout.addRow(setting.display_label, plug)

            # Change Plugin button (only for non-switcher plugins)
            from scanner.plugin_switcher_motion import PluginSwitcherMotion
            if PluginSwitcherMotion.plugin_name != "":
                change_plugin_btn = QPushButton("Change Plugin")
                change_plugin_btn.clicked.connect(self.change_motion_plugin)
                self.ui.config_layout.addRow(change_plugin_btn)

            estop_butt = QPushButton("E-Stop")
            estop_butt.clicked.connect(self.estop_button)
            self.ui.config_layout.addRow(estop_butt)
        
    def set_configuration_settings_probe(self, controller, connected, connect_function, disconnect_function):
    
        # Clear the config layout
        for i in reversed(range(self.ui.config_layout.rowCount())):
            self.ui.config_layout.removeRow(i)

        if connected:
            # Probe controller is connected - show settings and controls
            
            for setting in controller.settings_pre_connect:
                plug = QPluginSetting(setting)
                plug.setDisabled(True)
                self.ui.config_layout.addRow(setting.display_label, plug)

            # Disconnect button
            disconnect_button = QPushButton("Disconnect")
            disconnect_button.clicked.connect(disconnect_function)
            self.ui.config_layout.addRow(disconnect_button)

            # Post-connect settings 
            for setting in controller.settings_post_connect:
                self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))

            # Setup plotter with connected VNA
            self.plotter = plotter_system(connected_vna_plugin=self.scanner.scanner.probe_controller._probe)
            self.setup_plotting_canvas()

            # Plot button
            plot_btn = QPushButton("Plot")
            plot_btn.clicked.connect(self.plot_btn)
            self.ui.config_layout.addRow(plot_btn)

            # Save button
            save_btn = QPushButton("Save Data")
            save_btn.clicked.connect(self.save_btn)
            self.ui.config_layout.addRow(save_btn)

            # Reset Plugin button
            back_btn = QPushButton("Reset Plugin")
            back_btn.clicked.connect(self.back_function)
            self.ui.config_layout.addRow(back_btn)

        else:
            # Probe controller not connected - show connection UI
            # Pre-connect settings (editable before connection)
            for setting in controller.settings_pre_connect:
                self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))

            # Connect button
            connect_button = QPushButton("Connect")
            connect_button.clicked.connect(connect_function)
            self.ui.config_layout.addRow(connect_button)

            # Post-connect settings (disabled until connected)
            for setting in controller.settings_post_connect:
                plug = QPluginSetting(setting)
                plug.setDisabled(True)
                self.ui.config_layout.addRow(setting.display_label, plug)

            # Change Plugin button (only for non-switcher plugins)
            from scanner.plugin_switcher import PluginSwitcher
            if PluginSwitcher.plugin_name != "":
                change_plugin_btn = QPushButton("Change Plugin")
                change_plugin_btn.clicked.connect(self.change_probe_plugin)
                self.ui.config_layout.addRow(change_plugin_btn)
            estop_butt = QPushButton("E-Stop")
            estop_butt.clicked.connect(self.estop_button)
            self.ui.config_layout.addRow(estop_butt)

    def set_configuration_setting_pattern(self,connected) -> None:
        
        
        if connected == True:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                    self.ui.config_layout.removeRow(i)
            for setting in self.scan_controller.settings_pre_connect:
                    plug = QPluginSetting(setting)
                    plug.setDisabled(True)
                    self.ui.config_layout.addRow(setting.display_label, plug)
                
            for setting in self.scan_controller.settings_post_connect:
                    self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))
            planar_slope_button = QPushButton("Apply Planar Slope")
            planar_slope_button.clicked.connect(self.run_slope_logic)
            self.ui.config_layout.addRow(planar_slope_button)

            # STEP File Importer button
            step_importer_button = QPushButton("STEP/STL File Importer")
            step_importer_button.clicked.connect(self.open_step_importer)
            self.ui.config_layout.addRow(step_importer_button)

            disconnect_button = QPushButton("Back")
            disconnect_button.clicked.connect(self.disconnect_pat)
            self.ui.config_layout.addRow(disconnect_button)
            
            estop_butt = QPushButton("E-Stop")
            estop_butt.clicked.connect(self.estop_button)
            self.ui.config_layout.addRow(estop_butt)
            ### TESTING
            self.step_size = self.scan_controller.float_step_size
            self.length = self.scan_controller.y_axis_len
            matrix = self.scan_controller.matrix 
            self.scan_testing()      
            ### TESTING
        else:
            for i in reversed(range(self.ui.config_layout.rowCount())):
                    self.ui.config_layout.removeRow(i)
            for setting in self.scan_controller.settings_pre_connect:
                        self.ui.config_layout.addRow(setting.display_label, QPluginSetting(setting))


            connect_button = QPushButton("Generate")
            connect_button.clicked.connect(self.connect_pat)
            self.ui.config_layout.addRow(connect_button)

            # Add back button for scan pattern pre-connect state
            back_button = QPushButton("Back")
            back_button.clicked.connect(self.disconnect_pat)
            self.ui.config_layout.addRow(back_button)
            
            
    #endregion
    
    
    
    
    
    
    ## CONNECT DISCONNECT M/P/SP/SF
    #region c/dc functions
    @Slot()
    def connect_motion(self):
        # Plugin is already swapped when selected via configure_motion
        # Just connect to the hardware
        self.scanner.scanner.motion_controller.connect()
        self.configure_motion(True)

    @Slot()
    def disconnect_motion(self):
        self.scanner.scanner.motion_controller.disconnect()
        self.configure_motion(True)

    @Slot()
    def connect_probe(self):
        # Plugin is already swapped when selected via configure_probe
        # Just connect to the hardware
        self.scanner.scanner.probe_controller.connect()
        self.configure_probe(True)

    @Slot()
    def disconnect_probe(self):
        self.scanner.scanner.probe_controller.disconnect()
        self.configure_probe(True)
        
    @Slot()
    def finish_config(self):
        #connect button for scan file config
        self.file_controller.connect()
        self.configure_file(True)
        
    @Slot()
    def go_back_file(self):

        self.file_controller.disconnect()
        self.configure_file(True)
        
    @Slot()
    def connect_pat(self):
        # Validate memory requirements before connecting
        if not self.validate_scan_memory():
            # Validation failed - keep in pre-connected state
            print("Scan pattern connection aborted due to insufficient disk space")
            return

        # Memory validation passed - proceed with connection
        self.scan_controller.connect()
        self.configure_pattern(True)
    @Slot()
    def disconnect_pat(self):
        self.scan_controller.disconnect()
        self.configure_pattern(True)    
        
    #endregion
    
    
    
    
                    
    ## Helper Functions and Buttons
    #region  helper functions   
    def get_file_dir(self):

        self.file_directory = fd.askdirectory()

    def calculate_scan_memory_requirements(self):
        """
        Calculate the memory required to store scan data and validate against available disk space.

        Returns:
            tuple: (required_bytes, available_bytes, is_sufficient)
        """
        pass

        try:
            # Calculate scan parameters from pattern settings (before matrix is generated)
            # Get x_length, y_length, and step_size from scan pattern settings
            x_length = self.scan_controller.x_length.value
            y_length = self.scan_controller.y_length.value
            step_size = self.scan_controller.step_size.value

            # Calculate number of points, take a look at scan_pattern_1.py
            x_points = int(x_length / step_size + 1)
            y_points = int(y_length / step_size + 1)
            num_scan_points = x_points * y_points

            # Get number of frequencies from probe controller
            if not self.scanner.scanner.probe_controller.is_connected():
                messagebox.showerror(
                    "Probe Not Connected",
                    "Please connect to probe controller before configuring scan pattern."
                )
                return None, None, False

            num_frequencies = len(self.scanner.scanner.probe_controller.get_xaxis_coords())

            # Get number of S-parameters
            num_s_params = len(self.scanner.scanner.probe_controller.get_channel_names())

            # Calculate storage requirements
            # Data type: complex128 (16 bytes per complex number)
            # Storage format: /Data/{s_param}_real and /Data/{s_param}_imag
            # Each complex128 = float64 real (8 bytes) + float64 imag (8 bytes) = 16 bytes
            # Dataset shape: (num_points, num_freqs) for both real and imag
            bytes_per_s_param = 2 * num_scan_points * num_frequencies * 8  # float64 real + float64 imag
            total_s_param_bytes = num_s_params * bytes_per_s_param

            # Coordinates storage: 3 arrays (x, y, z) of float64
            coords_bytes = 3 * num_scan_points * 8

            # Frequencies array: float64
            freq_bytes = num_frequencies * 8

            # Metadata overhead (attributes, group structures, etc.)
            metadata_bytes = 50 * 1024  # 50 KB estimate for metadata

            # Camera image (if present, estimate ~500 KB for PNG)
            camera_bytes = 500 * 1024 if hasattr(self, 'camera') and self.camera else 0

            # Total required storage
            total_required_bytes = (
                total_s_param_bytes +
                coords_bytes +
                freq_bytes +
                metadata_bytes +
                camera_bytes
            )

            # Add 10% safety margin
            total_required_bytes = int(total_required_bytes * 1.1)

            # Get file save location
            save_directory = None
            for setting in self.file_controller.settings_pre_connect:
                if "Directory" in setting.display_label or "directory" in setting.display_label:
                    save_directory = setting.value
                    break

            if not save_directory:
                # Try to get from filename path
                for setting in self.file_controller.settings_pre_connect:
                    if "Filename" in setting.display_label or "filename" in setting.display_label:
                        filename = setting.value
                        if filename:
                            import os
                            save_directory = os.path.dirname(filename) or os.getcwd()
                            break

            if not save_directory:
                save_directory = "."  # Current directory as fallback

            # Get available disk space
            disk_stat = shutil.disk_usage(save_directory)
            available_bytes = disk_stat.free

            # DEBUG MODE: Override available space for testing
            if self.DEBUG_DISK_SPACE_TEST:
                available_bytes = self.DEBUG_SIMULATED_DISK_SPACE_MB * 1024 * 1024
                print(f"⚠️  DEBUG MODE: Simulating {self.DEBUG_SIMULATED_DISK_SPACE_MB} MB available disk space")
                print(f"   Actual available space: {disk_stat.free / (1024**3):.2f} GB")

            # Check if sufficient space available
            is_sufficient = available_bytes > total_required_bytes

            return total_required_bytes, available_bytes, is_sufficient

        except Exception as e:
            print(f"Error calculating memory requirements: {e}")
            import traceback
            traceback.print_exc()
            return None, None, False

    def validate_scan_memory(self):
        """
        Validate that sufficient disk space is available for the scan.
        Show error dialog if insufficient space.

        Returns:
            bool: True if sufficient space, False otherwise
        """
        
        required, available, is_sufficient = self.calculate_scan_memory_requirements()

        if required is None:
            # Error occurred during calculation
            return False

        # Convert bytes to human-readable format
        def format_bytes(bytes_val):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_val < 1024.0:
                    return f"{bytes_val:.2f} {unit}"
                bytes_val /= 1024.0
            return f"{bytes_val:.2f} PB"

        if not is_sufficient:
            # Show error dialog
            # Calculate number of points from settings (matrix not generated yet)
            x_length = self.scan_controller.x_length.value
            y_length = self.scan_controller.y_length.value
            step_size = self.scan_controller.step_size.value
            x_points = int(x_length / step_size + 1)
            y_points = int(y_length / step_size + 1)
            num_points = x_points * y_points

            messagebox.showerror(
                "Insufficient Disk Space",
                f"The scan pattern requires more storage than available on disk.\n\n"
                f"Scan Details:\n"
                f"  • Scan pattern: {x_points} × {y_points} = {num_points:,} points\n"
                f"  • Required storage: {format_bytes(required)}\n"
                f"  • Available storage: {format_bytes(available)}\n"
                f"  • Shortage: {format_bytes(required - available)}\n\n"
                f"Please reduce the number of scan points or free up disk space."
            )
            return False

        # Sufficient space - optionally show info
        x_length = self.scan_controller.x_length.value
        y_length = self.scan_controller.y_length.value
        step_size = self.scan_controller.step_size.value
        x_points = int(x_length / step_size + 1)
        y_points = int(y_length / step_size + 1)
        num_points = x_points * y_points

        print(f"✓ Scan storage validation passed:")
        print(f"  Scan pattern: {x_points} × {y_points} = {num_points:,} points")
        print(f"  Required: {format_bytes(required)}")
        print(f"  Available: {format_bytes(available)}")
        print(f"  Remaining after scan: {format_bytes(available - required)}")

        return True



    ## Fix after 
    def plot_btn(self):
        for i in reversed(range(self.ui.plot_config_wid.rowCount())):
            self.ui.plot_config_wid.removeRow(i)
            
        self.freqs, self.s_param_names,self.all_s_params_data = self.plotter._get_and_process_data("Log Mag")
        self.plot_style = "Log Mag"
        self.processed_data = self.plotter.plot_initial_data(self.plot_style,self.freqs, self.s_param_names,self.all_s_params_data)
        self.plot_settings()

    def scan_testing(self):
        test_scan = QPushButton("Test Scan")
        test_scan.clicked.connect(self.test_scan_bt)
        self.ui.config_layout.addRow(test_scan)
        
    def plot_settings(self):
        
        display_Pop_up = QPushButton("Display Pop Up")
        display_Pop_up.clicked.connect(self.display_Pop_up)
        self.ui.plot_config_wid.addRow(display_Pop_up)  
        
        plot_style = QPushButton("Select Plot Style (Mag dB default)")
        plot_style.clicked.connect(self.plot_style_btn)
        self.ui.plot_config_wid.addRow(plot_style)       
        
        sel_hide_channel = QPushButton("Select/Hide S-Parameters")
        sel_hide_channel.clicked.connect(self.sel_hide_channel)
        self.ui.plot_config_wid.addRow(sel_hide_channel)
        
        dsp_settings = QPushButton("DSP Settings")
        dsp_settings.clicked.connect(self.dsp_settings)
        self.ui.plot_config_wid.addRow(dsp_settings)      
        
        plot_plugins = QPushButton("Import Plot Plugins")
        plot_plugins.clicked.connect(self.plot_plugins)
        self.ui.plot_config_wid.addRow(plot_plugins)
        
        
        
        
    #region scan button func
    def update_plot_during_scan(self, point_index, s_params_data):
        """Callback function to update plotter in real-time during scan."""
        try:
            # Only update plot if plotter is initialized and probe is connected
            if hasattr(self, 'plotter') and self.scanner.scanner.probe_controller.is_connected():
                # Update plotter with new data point
                # This will update the existing plot with the latest measurement
                self.plotter._get_and_process_data("Log Mag")
                self.plotter.canvas.draw()
                self.plotter.canvas.flush_events()
        except Exception as e:
            print(f"Error updating plot during scan: {e}")


    def estop_button(self):
        self.scanner.scanner._motion_controller.emergency_stop()
        self.scanner.scanner.motion_controller.disconnect()
        self.scanner.scanner.probe_controller.disconnect()

    def pause_scan(self):
        self.scanner.scanner.pause = True
        self.scanner.scanner.handle_pause()




    def test_scan_bt(self):
        self.step_size = self.scan_controller.float_step_size
        self.length = self.scan_controller.y_axis_len
        matrix = self.scan_controller.matrix
        self.metaData=[]
        inc = 0
        for setting in self.file_controller.settings_pre_connect:
            plug = QPluginSetting(setting)
            self.metaData.append(PluginSettingString.get_value_as_string(self.file_controller.settings_pre_connect[inc]))
            inc = inc +1

        self.metaData_labels = self.file_display_label_text

        # Collect all scan settings
        scan_settings = {
            'step_size_mm': float(self.step_size),
            'scan_length': float(self.length),
            'matrix_shape': f"{matrix.shape[0]}x{matrix.shape[1]}",
            'num_points': int(matrix.shape[1]),
            'scan_pattern_type': self.scan_controller.pattern_type if hasattr(self.scan_controller, 'pattern_type') else 'unknown',
            'timestamp': datetime.datetime.now().isoformat()
        }

        # Add motion controller settings if available
        if self.pluginChosen_motion and hasattr(self, 'settings_motion_list'):
            for idx, value in enumerate(self.settings_motion_list):
                scan_settings[f'motion_setting_{idx}'] = str(value)

        # Add probe controller settings if available
        if self.pluginChosen_probe:
            try:
                probe = self.scanner.scanner.probe_controller
                if probe.is_connected():
                    scan_settings['probe_connected'] = 'True'
                    scan_settings['probe_plugin'] = probe._probe.__class__.__name__
            except:
                pass

        self.negative_step_size = np.negative(self.step_size)
        if not hasattr(self, 'z_step_size'):
            self.z_step_size = 1
             
        self.scan_thread = threading.Thread(
            target=self.scanner.scanner.run_scan,
            args=(matrix, self.length, self.scan_controller.x_axis_len_int,self.scan_controller.y_axis_len_int, self.step_size, self.negative_step_size,self.z_step_size,self.metaData, self.metaData_labels),
            kwargs={'camera_app': self.camera_app, 'scan_settings': scan_settings, 'scan_point_callback': self.update_plot_during_scan}
        )
        self.scan_thread.start()

        estop_butt = QPushButton("E-Stop")
        estop_butt.clicked.connect(self.estop_button)
        self.ui.config_layout.addRow(estop_butt)
        
            
    def display_Pop_up(self):
        self.plotter.plot_in_popup(self.plot_style,self.freqs, self.s_param_names,self.processed_data)
        
        
    def plot_style_btn(self):
        #Pop up Tkinter asking what style of plot you want
        self.plot_style = select_plot_style.select_plot_style()
        self.processed_data=self.plotter.plot_initial_data(self.plot_style,self.freqs, self.s_param_names,self.all_s_params_data)
    
    def sel_hide_channel(self):
        selected_hidden = select_plot_hide.select_plot_hide(4)
        self.plotter.set_trace_visibility(selected_hidden)
    
    
    def dsp_settings(self):
        self.invfft = self.plotter.invFFT_plot(self.s_param_names,self.processed_data,)
        
    
    def plot_plugins(self):
        self.scanner.scanner._probe_controller.scan_trigger_and_wait()
    
    def save_btn(self):
        self.plotter.save()
    
    def home_button(self):
        home_btn = QPushButton("Home All Axes")
        home_btn.clicked.connect(self.scanner.scanner._motion_controller.home)
        self.ui.config_layout.addRow(home_btn)
        
    
    def run_slope_logic(self):

        new_matrix, z_step_size = self.scan_controller.apply_planar_slope_ui(self.scan_controller.matrix,self.step_size)


        if new_matrix is not None:
            self.scan_controller.matrix = new_matrix
            self.z_step_size = z_step_size

    def open_step_importer(self):
        if not hasattr(self, "ndWindow"):
            self.ndWindow = ndwindow()
        self.ndWindow.show()
        self.ndWindow.raise_()
        self.ndWindow.activateWindow()

    def change_probe_plugin(self):
        """Allow user to select a different probe plugin."""
        from scanner.plugin_switcher import PluginSwitcher

        # Show file dialog to select new plugin
        if PluginSwitcher.select_plugin():
            # Plugin was selected, swap to it
            self.scanner.scanner.swap_probe_plugin()
            self.pluginChosen_probe = True

            # Refresh UI to show new plugin's settings
            self.configure_probe(True)

    def change_motion_plugin(self):
        """Allow user to select a different motion plugin."""
        from scanner.plugin_switcher_motion import PluginSwitcherMotion

        # Show file dialog to select new plugin
        if PluginSwitcherMotion.select_plugin():
            # Plugin was selected, swap to it
            self.scanner.scanner.swap_motion_plugin()
            self.pluginChosen_motion = True

            # Refresh UI to show new plugin's settings
            self.configure_motion(True)

    def back_function(self):
        """Reset probe plugin selection - SIMPLIFIED VERSION using hot-swap."""
        response = messagebox.askyesno(
            "Reset Probe Plugin",
            "Are you sure you want to reset the probe plugin selection?\nThis will disconnect and return to plugin selection."
        )

        if response:
            # Reset PluginSwitcher to default (empty)
            from scanner.plugin_switcher import PluginSwitcher
            PluginSwitcher.plugin_name = ""
            PluginSwitcher.basename = ""

            # Swap to default probe plugin (will read the reset PluginSwitcher)
            self.scanner.scanner.swap_probe_plugin()

            # Reset state and refresh UI
            self.pluginChosen_probe = False
            self.configure_probe(True)


    def back_function_motion(self):
        """Reset motion plugin selection - SIMPLIFIED VERSION using hot-swap."""
        response = messagebox.askyesno(
            "Reset Motion Plugin",
            "Are you sure you want to reset the motion plugin selection?\nThis will disconnect and return to plugin selection."
        )

        if response:
            # Reset PluginSwitcherMotion to default (empty)
            from scanner.plugin_switcher_motion import PluginSwitcherMotion
            PluginSwitcherMotion.plugin_name = ""
            PluginSwitcherMotion.basename = ""

            # Swap to default motion plugin (will read the reset PluginSwitcherMotion)
            self.scanner.scanner.swap_motion_plugin()

            # Reset state and refresh UI
            self.pluginChosen_motion = False
            self.configure_motion(True)
    
    def setup_theme_toggle(self):
        self.theme_btn = QToolButton(self)
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(True) 
        self.theme_btn.setToolTip("Toggle light / dark mode")

        
        self.theme_btn.setText("☀️")
        
        self.theme_btn.clicked.connect(self.toggle_theme)

        # Put it top-left in the title bar area
        #self.theme_btn.raise_()
        #self.ui.main_layout.addWidget(self.theme_btn, 0, 1)

       
    def toggle_theme(self):
        if self.current_theme == "dark":
            app.setStyleSheet(qdarktheme.load_stylesheet("light"))
            self.current_theme = "light"
            self.theme_btn.setText("☀️")
        else:
            app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
            self.current_theme = "dark"
            self.theme_btn.setText("🌙")

    def setup_settings_button(self):
        self.settings_btn = QToolButton(self)
        self.settings_btn.setText("⚙️")
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedSize(28, 28)
        
        self.settings_btn.setStyleSheet("""
            QToolButton {
                border: none;
                font-size: 14px;
            }
            QToolButton:hover {
                background-color: rgba(128,128,128,40);
                border-radius: 4px;
            }
        """)

        self.settings_btn.clicked.connect(self.open_settings)
        #self.settings_btn.raise_()

        # Place next to theme toggle
        #self.ui.main_layout.addWidget(self.settings_btn, 0, 0)
        
    def open_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        open_scope_btn = QPushButton("Signal Scope")
        open_scope_btn.clicked.connect(self.open_signal_scope)
        layout.addWidget(open_scope_btn)
        
        open_visualizer_btn = QPushButton("Visualizer")
        open_visualizer_btn.clicked.connect(self.open_visualizer)
        layout.addWidget(open_visualizer_btn)

        user_manual_btn = QPushButton("User Manual")
        user_manual_btn.clicked.connect(self.open_user_manual)
        layout.addWidget(user_manual_btn)

        dlg.resize(300, 200)
        dlg.exec()
    def open_user_manual(self):
        
        manual_path = os.path.join(os.path.dirname(__file__), "User_Manual.pdf")

        webbrowser.open_new(manual_path)
    
    def open_visualizer(self):
        if not hasattr(self, "VisualizerWindow"):
            self.visualizer_window = VisualizerWindow(f"{self.metaData[1]}.hdf5") 
        self.visualizer_window.show()
        self.visualizer_window.raise_()
        self.visualizer_window.activateWindow()
            
    def open_signal_scope(self):
        # Signal scope is already created in __init__, just show it
        self.signal_scope.show()
        self.signal_scope.raise_()
        self.signal_scope.activateWindow()

    def setup_top_controls(self):
        
        

        self.top_controls = QWidget(self)
        layout = QHBoxLayout(self.top_controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.settings_btn)
        layout.addWidget(self.theme_btn)
        

        self.top_controls.adjustSize()
        self.top_controls.raise_()
    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 8
        self.top_controls.move(margin, margin)

    def setup_plotting_canvas(self) -> None:
       # main_layout = self.ui.main_layout 
       
        # main_layout.addWidget(self.plotter, 1, 5)
        pass
    def closeEvent(self, event: QCloseEvent) -> None:
        self.scanner.close()
        return super().closeEvent(event)
    #endregion 

if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    app.exec()