import logging
import nidaqmx
from nidaqmx.constants import (
    ThermocoupleType,
    TemperatureUnits,
    ResistanceConfiguration,
    RTDType,
    ResistanceUnits,
    BridgeConfiguration,
    ExcitationSource,
    BridgeUnits,
    CurrentUnits
)

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] DAQManager: %(message)s')
logger = logging.getLogger(__name__)

class DAQManager:
    """
    Abstracts NI-DAQmx complexity for multi-channel, multi-mode acquisition.
    Groups channels by measurement type into distinct DAQmx tasks,
    as NI-DAQmx does not allow mixed measurement types in a single task.
    """

    def __init__(self):
        self.tasks = {}           # dict of measurement_type -> nidaqmx.Task
        self.task_channels = {}   # dict of measurement_type -> list of physical channel names
        self.bridge_channels = [] # cache for fast scaling
        self.is_connected = False

    def configure(self, config: dict):
        """
        Parses configuration, groups channels by measurement type, and initializes NI-DAQmx tasks.
        
        Args:
            config: dict mapping physical channel strings to their configuration parameters.
                    Example:
                    {
                        "cDAQ1Mod1/ai0": {"mode": "Voltage", "min_v": -10, "max_v": 10},
                        "cDAQ1Mod1/ai1": {"mode": "Thermocouple (TC)", "tc_type": ThermocoupleType.K}
                    }
        """
        self.disconnect()  # clean up any existing state

        # Group channels by base measurement category
        grouped_config = {}
        for channel, params in config.items():
            mode = params.get("mode")
            if not mode or mode == "None":
                continue
                
            # Categorize the specific GUI mode into a broad DAQmx task type
            task_type = self._get_task_type_for_mode(mode)
            if task_type not in grouped_config:
                grouped_config[task_type] = []
            grouped_config[task_type].append((channel, params))

        if not grouped_config:
            raise ValueError("Configuration contains no active channels.")

        # Create tasks
        try:
            for task_type, channels_info in grouped_config.items():
                task = nidaqmx.Task(new_task_name=f"Task_{task_type}")
                self.tasks[task_type] = task
                self.task_channels[task_type] = []

                for channel, params in channels_info:
                    mode = params.get("mode")
                    if mode == "Voltage":
                        self._create_voltage_channel(task, channel, params)
                    elif mode == "Current":
                        self._create_current_channel(task, channel, params)
                    elif mode == "Thermocouple (TC)":
                        self._create_temperature_tc_channel(task, channel, params)
                    elif mode == "Raw Resistance":
                        self._create_resistance_channel(task, channel, params)
                    elif mode == "2-Wire RTD (Workaround)":
                        # We read as resistance and linearize later in read_all()
                        self._create_resistance_channel(task, channel, {"wire": "2-Wire"})
                    elif mode == "Native RTD (3/4 Wire)":
                        self._create_rtd_channel(task, channel, params)
                    elif mode == "Wheatstone Bridge":
                        self._create_bridge_channel(task, channel, params)
                        self.bridge_channels.append(channel)
                    
                    self.task_channels[task_type].append(channel)
                    
            self.is_connected = True
            logger.info("Successfully configured tasks: %s", list(self.tasks.keys()))
            
        except Exception as e:
            logger.error("Failed to configure tasks. Cleaning up. Error: %s", e)
            self.disconnect()
            raise

    def _get_task_type_for_mode(self, mode: str) -> str:
        if mode == "Voltage": return "voltage"
        if mode == "Current": return "current"
        if mode == "Thermocouple (TC)": return "temperature_tc"
        if mode in ["Raw Resistance", "2-Wire RTD (Workaround)"]: return "resistance"
        if mode == "Native RTD (3/4 Wire)": return "temperature_rtd"
        if mode == "Wheatstone Bridge": return "bridge"
        return "unknown"

    def _create_voltage_channel(self, task: nidaqmx.Task, channel: str, params: dict):
        min_v = params.get("min_v", -60.0)
        max_v = params.get("max_v", 60.0)
        task.ai_channels.add_ai_voltage_chan(channel, min_val=min_v, max_val=max_v)

    def _create_current_channel(self, task: nidaqmx.Task, channel: str, params: dict):
        min_i = params.get("min_i", -0.025)
        max_i = params.get("max_i", 0.025)
        task.ai_channels.add_ai_current_chan(channel, min_val=min_i, max_val=max_i, units=CurrentUnits.AMPS)

    def _create_temperature_tc_channel(self, task: nidaqmx.Task, channel: str, params: dict):
        tc_str = params.get("tc_type", "K")
        tc_map = {"K": ThermocoupleType.K, "J": ThermocoupleType.J, "T": ThermocoupleType.T, "E": ThermocoupleType.E}
        tc_type = tc_map.get(tc_str, ThermocoupleType.K)
        task.ai_channels.add_ai_thrmcpl_chan(channel, min_val=-100.0, max_val=100.0, thermocouple_type=tc_type, units=TemperatureUnits.DEG_C)

    def _create_resistance_channel(self, task: nidaqmx.Task, channel: str, params: dict):
        wire_str = params.get("wire", "2-Wire")
        wires = ResistanceConfiguration.TWO_WIRE if wire_str == "2-Wire" else ResistanceConfiguration.FOUR_WIRE
        task.ai_channels.add_ai_resistance_chan(
            channel,
            min_val=0.0,
            max_val=10000.0,
            resistance_config=wires,
            current_excit_source=ExcitationSource.INTERNAL,
            current_excit_val=500e-6,
            units=ResistanceUnits.OHMS
        )

    def _create_rtd_channel(self, task: nidaqmx.Task, channel: str, params: dict):
        wire_str = params.get("wire", "4-Wire")
        wires = ResistanceConfiguration.THREE_WIRE if wire_str == "3-Wire" else ResistanceConfiguration.FOUR_WIRE
        type_str = params.get("type", "PT3750")
        if type_str == "PT3851": rtd_t = RTDType.PT_3851
        elif type_str == "PT3916": rtd_t = RTDType.PT_3916
        else: rtd_t = RTDType.PT_3750
        
        task.ai_channels.add_ai_rtd_chan(
            channel,
            rtd_type=rtd_t,
            resistance_config=wires,
            current_excit_source=ExcitationSource.INTERNAL,
            current_excit_val=500e-6,
            units=TemperatureUnits.DEG_C
        )

    def _create_bridge_channel(self, task: nidaqmx.Task, channel: str, params: dict):
        b_str = params.get("bridge", "Full Bridge")
        if "Half" in b_str: config = BridgeConfiguration.HALF_BRIDGE
        elif "Quarter" in b_str: config = BridgeConfiguration.QUARTER_BRIDGE
        else: config = BridgeConfiguration.FULL_BRIDGE
        
        task.ai_channels.add_ai_bridge_chan(
            channel,
            min_val=-0.025,
            max_val=0.025,
            bridge_config=config,
            units=BridgeUnits.VOLTS_PER_VOLT
        )

    def connect(self):
        """
        Usually handles hardware connection verification.
        In this implementation, configuration handles creation.
        """
        pass

    def start(self):
        """Starts every configured DAQmx task. If multiple tasks exist, they are started/stopped dynamically during read to avoid resource conflicts."""
        if not self.is_connected:
            raise RuntimeError("Cannot start: DAQManager is not configured/connected.")
            
        # If there is only one task, we can start it once for efficiency.
        # If there are multiple, starting them all at once causes a resource conflict.
        if len(self.tasks) == 1:
            try:
                list(self.tasks.values())[0].start()
            except Exception as e:
                logger.error("Failed to start task: %s", e)
                raise

    def read_all(self) -> dict:
        """
        Loops over every DAQmx Task, reads a single point, 
        and maps the output back to the logical channel names.
        
        Returns:
            dict: Mapping of channel string to its float reading.
                  Example: {"cDAQ1Mod1/ai0": 24.6, "cDAQ1Mod1/ai1": 4.98}
        """
        if not self.is_connected:
            return {}

        results = {}
        multiple_tasks = len(self.tasks) > 1

        for task_type, task in self.tasks.items():
            try:
                if multiple_tasks:
                    task.start()

                # Read 1 sample from the task
                data = task.read()

                if multiple_tasks:
                    task.stop()

                channels = self.task_channels[task_type]
                
                # If a task has only 1 channel, data is a float. If multiple, it's a list.
                if len(channels) == 1:
                    data = [data]
                    
                for idx, channel in enumerate(channels):
                    results[channel] = data[idx]
                    
            except Exception as e:
                logger.error("Error reading from task %s: %s", task_type, e)
                if multiple_tasks:
                    try:
                        task.stop()
                    except:
                        pass
                
        # Bridge channels natively return V/V in this API, let's convert to mV/V if needed, 
        # but the GUI can handle scaling. The original function multiplied by 1000.
        for chan in self.bridge_channels:
            if chan in results:
                results[chan] *= 1000.0
                            
        return results


    def stop(self):
        """Stops every DAQmx task safely."""
        for name, task in self.tasks.items():
            try:
                task.stop()
            except Exception as e:
                logger.warning("Error stopping task %s: %s", name, e)

    def disconnect(self):
        """Stops tasks, closes them, and clears internal dictionaries."""
        self.stop()
        for name, task in self.tasks.items():
            try:
                task.close()
            except Exception as e:
                logger.warning("Error closing task %s: %s", name, e)
                
        self.tasks.clear()
        self.task_channels.clear()
        self.is_connected = False
