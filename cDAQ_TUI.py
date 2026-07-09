import os
import time
import cutie
import nidaqmx.constants as const
import cDAQ_Functions as daq
import matplotlib.pyplot as plt

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def configure_and_run_tui():
    # State Parameters
    selected_channel = "cDAQ1Mod1/ai0"
    selected_mode = "Voltage"
    
    # Mode-specific parameters
    v_max, v_min = 60.0, -60.0
    tc_type = const.ThermocoupleType.K

    rtd_type = const.RTDType.PT_3750
    wire_config = const.ResistanceConfiguration.FOUR_WIRE
    bridge_config = const.BridgeConfiguration.FULL_BRIDGE

    while True:

        clear_screen()
        print("=============================================")
        print("        cDAQ UNIVERSAL TUI DASHBOARD         ")
        print("=============================================")
        print(f" Current Channel : {selected_channel}")
        print(f" Selected Mode   : {selected_mode}")
        print("---------------------------------------------")
        
        options = [
            "1. Select Target Channel/Device",
            "2. Select Acquisition Mode",
            "3. Adjust Parameter Thresholds / Constraints",
            "4. [START] Live Acquisition Loop",
            "5. Exit Program"
        ]
        
        choice = cutie.select(options)
        
        if choice == 0: # Select Channel
            clear_screen()
            ch_list = daq.check_active_channels()
            print("Select a physical target input channel:")
            ch_idx = cutie.select(ch_list)
            selected_channel = ch_list[ch_idx]
            

        elif choice == 1: # Select Mode
            clear_screen()
            modes = ["Voltage", "Thermocouple (TC)", "Current", "Raw Resistance", "2-Wire RTD (Workaround)", "Native RTD (3/4 Wire)", "Wheatstone Bridge"]
            print("Select physical DAQ calculation model:")
            m_idx = cutie.select(modes)
            selected_mode = modes[m_idx]
             

        elif choice == 2: # Set Parameters
            
            clear_screen()
            print(f"--- Adjusting Properties for {selected_mode} ---")
            
            if selected_mode == "Voltage":
                v_max = cutie.get_number("Enter Max Voltage limit:", default=60.0)
                v_min = cutie.get_number("Enter Min Voltage limit:", default=-60.0)
            
            elif selected_mode == "Thermocouple (TC)":
                tc_options = ["Type K", "Type J", "Type T", "Type E"]
                idx = cutie.select(tc_options)
                tc_type = [const.ThermocoupleType.K, const.ThermocoupleType.J, const.ThermocoupleType.T, const.ThermocoupleType.E][idx]
            
            elif selected_mode in ["Raw Resistance", "Native RTD (3/4 Wire)"]:
                wire_options = ["3-Wire Setup", "4-Wire Setup"] if "Native" in selected_mode else ["2-Wire Setup", "4-Wire Setup"]
                w_idx = cutie.select(wire_options)
            
                if "Native" in selected_mode:
                    
                    wire_config  = const.ResistanceConfiguration.THREE_WIRE if w_idx == 0 else const.ResistanceConfiguration.FOUR_WIRE
            
                else:
                    wire_config = const.ResistanceConfiguration.TWO_WIRE if w_idx == 0 else const.ResistanceConfiguration.FOUR_WIRE
            
            elif selected_mode == "Wheatstone Bridge":
                b_options = ["Full Bridge", "Half Bridge", "Quarter Bridge"]
                b_idx = cutie.select(b_options)
                bridge_config = [const.BridgeConfiguration.FULL_BRIDGE, const.BridgeConfiguration.HALF_BRIDGE, const.BridgeConfiguration.QUARTER_BRIDGE][b_idx]
            
            else:
                print("No parameters required for this specific mode selection.")
                time.sleep(1)

        elif choice == 3: # START
            clear_screen()
            
            print("=============================================")
            print(f" RUNNING LIVE ACQUISITION ON: {selected_channel}")
            print(" Press [Ctrl + C] anytime to simulate [STOP]")
            print("=============================================\n")
            
            try:
                i = 0
            
                while True:
                    # Executing single-read queries depending on current settings
            
                    if selected_mode == "Voltage":
                        val = daq.read_voltage(selected_channel, v_min, v_max)
                        print(f"{i} [LIVE] Signal Amplitude: {val:.5f} V")
                        plt.scatter(i, val, c='r')
                        i+=1
            
                    elif selected_mode == "Thermocouple (TC)":
                        val = daq.read_temperature_tc(selected_channel, tc_type)
                        print(f"{i} [LIVE] Sensor Thermal Core: {val:.3f} °C")
                        plt.scatter(i, val, c='r')
                        i+=1
            
                    elif selected_mode == "Current":
                        val = daq.read_current(selected_channel)
                        print(f"{i} [LIVE] Loop Current: {val * 1000.0:.6f} mA")
                        plt.scatter(i, val, c='r')
                        i+=1

                    elif selected_mode == "Raw Resistance":
                        val = daq.read_resistance_raw(selected_channel, wire_config)
                        print(f"{i} [LIVE] Resistance Value: {val:.2f} Ohms")
                        plt.scatter(i, val, c='r')
                        i+=1

                    elif selected_mode == "2-Wire RTD (Workaround)":
                        val = daq.read_rtd_workaround_2wire(selected_channel)
                        print(f"{i} [LIVE] Linearized Matrix Temp: {val:.2f} °C")
                        plt.scatter(i, val, c='r')
                        i+=1

                    elif selected_mode == "Native RTD (3/4 Wire)":
                        val = daq.read_rtd_native(selected_channel, rtd_type, wire_config)
                        print(f"{i} [LIVE] Native RTD Core Temp: {val:.2f} °C")
                        plt.scatter(i, val, c='r')
                        i+=1

                    elif selected_mode == "Wheatstone Bridge":
                        val = daq.read_bridge(selected_channel, bridge_config)
                        print(f"{i} [LIVE] Ratiometric Bridge Strain: {val:.4f} mV/V")
                        plt.scatter(i, val, c='r')
                        i+=1
                        
                    time.sleep(0.4) # Interval time delay

                

            except KeyboardInterrupt:
                print("\n\n[STOP DETECTED] Relinquishing hardware task channels...")
                time.sleep(1.5)
                plt.show()

        elif choice == 4: # Exit
            print("\n shut down")
            break

if __name__ == "__main__":
    configure_and_run_tui()
    