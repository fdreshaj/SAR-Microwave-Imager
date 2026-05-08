
from abc import ABC, abstractmethod
from typing import Sequence

from scanner.plugin_setting import PluginSetting
import time

class MotionControllerPlugin(ABC):
    settings_pre_connect: list[PluginSetting]
    settings_post_connect: list[PluginSetting]

    def __init__(self) -> None:
        self.settings_pre_connect = []
        self.settings_post_connect = []

    def add_setting_pre_connect(self, setting: PluginSetting):
        self.settings_pre_connect.append(setting)
    
    def add_setting_post_connect(self, setting: PluginSetting):
        self.settings_post_connect.append(setting)

    @abstractmethod
    def connect(self) -> None:
        pass
    @abstractmethod
    def disconnect(self) -> None:
        pass
    @abstractmethod
    def get_axis_display_names(self) -> tuple[str, ...]:
        pass
    @abstractmethod
    def get_axis_units(self) -> tuple[str, ...]:
        pass

    @abstractmethod
    def set_velocity(self, velocities: dict[int, float]) -> None:
        pass
    @abstractmethod
    def set_acceleration(self, accels: dict[int, float]) -> None:
        pass

    @abstractmethod
    def move_relative(self, move_dist: dict[int, float]) -> dict[int, float] | None:
        pass
    @abstractmethod
    def move_absolute(self, move_pos: dict[int, float]) -> dict[int, float] | None:
        pass
    @abstractmethod
    def home(self, axes: list[int]) -> dict[int, float]:
        pass

    @abstractmethod
    def get_current_positions(self) -> tuple[float, ...]:
        pass
    @abstractmethod
    def is_moving(self,axis) -> bool:
        pass
    @abstractmethod
    def get_endstop_minimums(self) -> tuple[float, ...]:
        pass
    @abstractmethod
    def get_endstop_maximums(self) -> tuple[float, ...]:
        pass
    @abstractmethod 
    def set_config(self, amps,idle_p, idle_time):
        pass
    @abstractmethod
    def emergency_stop(self):
        pass
    @abstractmethod
    def show_radar(self):
        pass

class MotionController:
    _axis_labels: tuple[str, ...]
    _target_positions: list[float]
    # axis_velocities: list[float]
    # axis_accels: list[float]
    _endstop_minimums: tuple[float, ...]
    _endstop_maximums: tuple[float, ...]

    _driver: MotionControllerPlugin
    _is_driver_connected: bool

    def __init__(self, motion_plugin: MotionControllerPlugin) -> None:
        self._driver = motion_plugin
        self._is_driver_connected = False
        self.disconnect()

    def connect(self) -> None:
        self._driver.connect()
        self._is_driver_connected = True
        self._axis_labels = self._driver.get_axis_display_names()
        #self._target_positions = list(self._driver.get_current_positions())
        
        self._endstop_minimums = self._driver.get_endstop_minimums()
        self._endstop_maximums = self._driver.get_endstop_maximums()
        #time.sleep(2)
        #self._endstop_maximums = self._driver.home()
        self._driver.set_velocity()
        self._driver.set_acceleration()
        
    def show_radar(self):
        """Passes the show_radar call to the active plugin driver."""
        if hasattr(self._driver, 'show_radar'):
            self._driver.show_radar()
        else:
            print("The current plugin does not support a radar view.")
    def is_connected(self) -> bool:
        return self._is_driver_connected
    
    def disconnect(self) -> None:
        was_connected = self._is_driver_connected
        self._is_driver_connected = False
        self._axis_labels = ()
        self._target_positions = []
        self._endstop_minimums = ()
        self._endstop_maximums = ()
        if was_connected:
            self._driver.disconnect()
    
    def must_be_connected(self) -> None:
        if not self._is_driver_connected:
            raise ConnectionError("Motion driver must be connected to use this functionality.")
    
    def must_be_valid_index(self, inds: Sequence[int]) -> None:
        if min(inds) < 0:
            raise ValueError(f"Axis index '{min(inds)}' is invalid.")
        if max(inds) >= len(self._axis_labels):
            raise ValueError(f"Axis index '{max(inds)}' is invalid.")

    def swap_motion_plugin(self, motion_plugin: MotionControllerPlugin) -> None:
        self.disconnect()
        self._driver = motion_plugin
    
    def set_velocity(self, axis_velocties: dict[int, float]) -> None:
        self.must_be_connected()
        self._driver.set_velocity(axis_velocties)

    def set_acceleration(self, axis_accels: dict[int, float]) -> None:
        self.must_be_connected()
        self._driver.set_acceleration(axis_accels)

    def set_config(self, amps,idle_p, idle_time):
        self.must_be_connected()
        self._driver.set_config(amps,idle_p, idle_time)
    #TODO:
    def move_absolute(self, axis_positions: dict[int, float]) -> None:
        self.must_be_connected()
        

        
        # for ind in axis_positions:
        #     if axis_positions[ind] > self._endstop_maximums[ind]:
        #         axis_positions[ind] = self._endstop_maximums[ind]
        #     if axis_positions[ind] < self._endstop_minimums[ind]:
        #         axis_positions[ind] = self._endstop_minimums[ind]
        ret_positions = self._driver.move_absolute(axis_positions)
        
        if ret_positions is None:
            ret_positions = axis_positions
        for ind,val in axis_positions.items():
            #self._target_positions[ind] = val 
            #TODO:
        
            pass
        

    def move_relative(self, axis_offsets: dict[int, float]) -> None:
        for axis,pos in enumerate(self._target_positions):
            if axis in axis_offsets:
                axis_offsets[axis] += pos
        self.move_absolute(axis_offsets)

    def is_moving(self,axis=None) -> bool:
        self.must_be_connected()
        return self._driver.is_moving()
    
    def get_current_positions(self) -> tuple[float, ...]:
        return self._driver.get_current_positions()

    def home(self) -> None:
        self.must_be_connected()
        return self._driver.home()
    def emergency_stop(self):
        self.must_be_connected()
        self._driver.emergency_stop()