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

# -------------------------------------------------------------
# HARDWARE UTILITY FUNCTIONS
# -------------------------------------------------------------

def get_connected_devices():
    """Scans system and returns list of device names."""
    system = nidaqmx.system.System.local()
    return [d.name for d in system.devices]

def check_active_channels(device_name):
    """Returns list of physical channels for the specified device."""
    system = nidaqmx.system.System.local()
    try:
        device = system.devices[device_name]
        return [chan.name for chan in device.ai_physical_chans]
    except Exception:
        # Fallback to default NI 9219 mapping slots if device not found
        return [f"{device_name}/ai0", f"{device_name}/ai1", f"{device_name}/ai2", f"{device_name}/ai3"]

# -------------------------------------------------------------
# CORE ACQUISITION FUNCTIONS (SINGLE-READ PATTERN FOR GUI/TUI)
# -------------------------------------------------------------

def read_voltage(channel="cDAQ1Mod1/ai0", min_v=-60.0, max_v=60.0):
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_voltage_chan(
            physical_channel=channel,
            min_val=min_v,
            max_val=max_v,
            name_to_assign_to_channel="TaskVoltage"
        )
        return task.read()

def read_temperature_tc(channel="cDAQ1Mod1/ai0", tc_type=ThermocoupleType.K, min_t=-100.0, max_t=100.0):
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_thrmcpl_chan(
            physical_channel=channel,
            min_val=min_t,
            max_val=max_t,
            thermocouple_type=tc_type,
            units=TemperatureUnits.DEG_C,
            name_to_assign_to_channel="TaskTC"
        )
        return task.read()

def read_current(channel="cDAQ1Mod1/ai0", min_i=-0.025, max_i=0.025):
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_current_chan(
            physical_channel=channel,
            min_val=min_i,
            max_val=max_i,
            name_to_assign_to_channel="TaskCurrent",
            units= CurrentUnits.AMPS
        )
        return task.read()

def read_resistance_raw(channel="cDAQ1Mod1/ai0", wires=ResistanceConfiguration.TWO_WIRE, max_r=10000.0):
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_resistance_chan(
            physical_channel=channel,
            min_val=0.0,
            max_val=max_r,
            resistance_config=wires,
            current_excit_source=ExcitationSource.INTERNAL,
            current_excit_val=500e-6, # Locked driver value for NI 9219
            units=ResistanceUnits.OHMS,
            name_to_assign_to_channel="TaskRes"
        )
        return task.read()

def read_rtd_workaround_2wire(channel="cDAQ1Mod1/ai0", max_r=10000.0):
    raw_ohms = read_resistance_raw(channel=channel, wires=ResistanceConfiguration.TWO_WIRE, max_r=max_r)
    temperature = (raw_ohms - 100.0) / 0.385
    return temperature

def read_rtd_native(channel="cDAQ1Mod1/ai0", rtd_type=RTDType.PT_3750, wires=ResistanceConfiguration.FOUR_WIRE):
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_rtd_chan(
            physical_channel=channel,
            rtd_type=rtd_type,
            resistance_config=wires,
            current_excit_source=ExcitationSource.INTERNAL,
            current_excit_val=500e-6, # Locked driver value for NI 9219
            units=TemperatureUnits.DEG_C,
            name_to_assign_to_channel="TaskNativeRTD"
        )
        return task.read()

def read_bridge(channel="cDAQ1Mod1/ai0", config=BridgeConfiguration.FULL_BRIDGE):
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_bridge_chan(
            physical_channel=channel,
            min_val=-0.025,
            max_val=0.025,
            bridge_config=config,
            units=BridgeUnits.VOLTS_PER_VOLT,
            name_to_assign_to_channel="TaskBridge"
        )
        raw_ratio = task.read()
        return raw_ratio * 1000.0  # Output normalized directly to mV/V