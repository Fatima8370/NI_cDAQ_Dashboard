import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import nidaqmx
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import os
import csv
import zipfile
import shutil
from datetime import datetime
import queue
import pyodbc
import cDAQ_Agent
from cDAQ_Manager import DAQManager

# Wiring Instructions dictionary
WIRING_INSTRUCTIONS = {
    "Voltage": "Pin 1 (T+) | Pin 2 (T-)\nPin 4 (HI) | Pin 5 (LO)",
    "Thermocouple (TC)": "Pin 1 (T+) | Pin 2 (T-)\nPin 4 (HI) | Pin 5 (LO)",
    "Current": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (HI) | Pin 5 (LO)",
    "Raw Resistance (2-Wire)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (HI) | Pin 5 (LO)",
    "Raw Resistance (4-Wire)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (EX+) | Pin 4 (HI)\nPin 5 (EX-) | Pin 6 (LO)",
    "2-Wire RTD (Workaround)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (HI) | Pin 5 (LO)",
    "Native RTD (3-Wire)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (EX+) | Pin 5 (EX-)\nPin 6 (LO)",
    "Native RTD (4-Wire)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (EX+) | Pin 4 (HI)\nPin 5 (EX-) | Pin 6 (LO)",
    "Wheatstone Bridge (Full)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (EX+) | Pin 4 (HI)\nPin 5 (EX-) | Pin 6 (LO)",
    "Wheatstone Bridge (Half)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (EX+) | Pin 4 (HI)\nPin 5 (EX-)",
    "Wheatstone Bridge (Quarter)": "Pin 1 (T+) | Pin 2 (T-)\nPin 3 (HI) | Pin 5 (LO)"
}

def get_connected_devices():
    system = nidaqmx.system.System.local()
    return [d.name for d in system.devices]

def check_active_channels(device_name):
    system = nidaqmx.system.System.local()
    try:
        return [chan.name for chan in system.devices[device_name].ai_physical_chans]
    except Exception:
        return [f"{device_name}/ai0", f"{device_name}/ai1", f"{device_name}/ai2", f"{device_name}/ai3"]

class AppSession:
    def __init__(self):
        self.start_time = datetime.now()
        self.session_str = self.start_time.strftime("%Y-%m-%d_%H-%M-%S")
        self.temp_dir = os.path.join(os.getcwd(), f"temp_session_{self.session_str}")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.files = set()
        self.run_count = 0

class ChannelQuadrant(ttk.LabelFrame):
    def __init__(self, master, channel_id, master_app, *args, **kwargs):
        super().__init__(master, text=f"Channel {channel_id}", *args, **kwargs)
        self.channel_id = channel_id
        self.master_app = master_app
        
        self.data_y = []
        self.data_time = []          # relative seconds for graph X axis
        self.data_timestamps = []    # actual system datetime strings for CSV
        self.start_timestamp = 0
        
        self.current_ylabel = "Value"
        self.param_vars = {}
        
        self._create_widgets()
        
    def _create_widgets(self):
        # Top Area to hold controls (left, middle, right)
        top_area = ttk.Frame(self)
        top_area.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)
        
        # --- LEFT: Basic Config ---
        basic_frame = ttk.Frame(top_area)
        basic_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        ttk.Label(basic_frame, text="Device:").grid(row=0, column=0, sticky="e", padx=2, pady=2)
        self.device_combo = ttk.Combobox(basic_frame, state="readonly", width=12)
        self.device_combo.grid(row=0, column=1, padx=2, pady=2)
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_select)
        
        ttk.Label(basic_frame, text="Chan:").grid(row=1, column=0, sticky="e", padx=2, pady=2)
        self.channel_combo = ttk.Combobox(basic_frame, state="readonly", width=12)
        self.channel_combo.grid(row=1, column=1, padx=2, pady=2)
        
        ttk.Label(basic_frame, text="Mode:").grid(row=2, column=0, sticky="e", padx=2, pady=2)
        self.mode_combo = ttk.Combobox(basic_frame, state="readonly", width=16)
        self.mode_combo['values'] = (
            "None", "Voltage", "Thermocouple (TC)", "Current", 
            "Raw Resistance", "2-Wire RTD (Workaround)", 
            "Native RTD (3/4 Wire)", "Wheatstone Bridge"
        )
        self.mode_combo.current(0)
        self.mode_combo.grid(row=2, column=1, padx=2, pady=2, sticky="w")
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_select)

        # --- RIGHT: Digital Display ---
        display_frame = ttk.Frame(top_area)
        display_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        
        self.digital_display = tk.Label(display_frame, bg='black', fg='#39ff14', font=('Consolas', 10, 'bold'), 
                                        width=18, height=6, anchor='nw', justify='left', 
                                        text="Live Data:\n--\n--\n--\n--\n--")
        self.digital_display.pack(side=tk.TOP)

        # --- MIDDLE: Params & Advanced ---
        middle_frame = ttk.Frame(top_area)
        middle_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        # Dynamic Parameters Frame
        self.param_frame = ttk.Frame(middle_frame)
        self.param_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        # Graph Settings (X-Axis label only, graph is unbounded/scaleable)
        settings_frame = ttk.Frame(middle_frame)
        settings_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        ttk.Label(settings_frame, text="X-Axis:").grid(row=0, column=0, sticky="e", padx=2)
        self.xaxis_var = tk.StringVar(value="Sample No")
        ttk.Combobox(settings_frame, textvariable=self.xaxis_var, values=["Sample No", "Time (s)"], state="readonly", width=9).grid(row=0, column=1, padx=2)
        
        # Offset Scale
        offset_frame = ttk.Frame(middle_frame)
        offset_frame.pack(side=tk.TOP, fill=tk.X, pady=2)
        ttk.Label(offset_frame, text="Offset Trim:").pack(side=tk.LEFT, padx=2)
        
        self.offset_var = tk.DoubleVar(value=0.0)
        self.offset_display = tk.StringVar(value="0.00")
        
        def update_disp(*args):
            self.offset_display.set(f"{self.offset_var.get():.2f}")
            
        self.offset_var.trace_add("write", update_disp)
        
        self.offset_scale = tk.Scale(
            offset_frame, 
            from_=-10.0, 
            to=10.0, 
            variable=self.offset_var, 
            orient=tk.HORIZONTAL, 
            length=100,
            resolution=0.01,
            showvalue=False,
            bd=0,
            highlightthickness=0
        )
        self.offset_scale.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Label(offset_frame, textvariable=self.offset_display).pack(side=tk.LEFT, padx=2)

        # Action Frame (Bottom of Top Area)
        action_frame = ttk.Frame(self)
        action_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)
        
        self.wiring_label = ttk.Label(action_frame, text="", foreground="blue", font=("Segoe UI", 8, "italic"), wraplength=450)
        self.wiring_label.pack(side=tk.LEFT, padx=2, fill=tk.BOTH, expand=True)

        # Matplotlib Graph
        self.fig, self.ax = plt.subplots(figsize=(4, 2.8), dpi=100)
        self.line, = self.ax.plot([], [], 'r-')
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(-10, 10)
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.refresh_devices()
        self._on_mode_select()

    def refresh_devices(self):
        try:
            devices = get_connected_devices()
            if devices:
                self.device_combo['values'] = devices
                self.device_combo.current(0)
                self._on_device_select()
        except Exception as e:
            print(f"Error fetching devices: {e}")

    def _on_device_select(self, event=None):
        device = self.device_combo.get()
        if device:
            try:
                chans = check_active_channels(device)
                self.channel_combo['values'] = chans
                if chans:
                    idx = (self.channel_id - 1) % len(chans)
                    self.channel_combo.current(idx)
            except Exception as e:
                print(f"Error fetching channels for {device}: {e}")

    def clear_param_frame(self):
        for widget in self.param_frame.winfo_children():
            widget.destroy()

    def _on_mode_select(self, event=None):
        mode = self.mode_combo.get()
        self.clear_param_frame()
        self.param_vars = {}
        wiring_text = ""
        
        if mode == "None":
            self.current_ylabel = "Value"
            wiring_text = "Channel Inactive"
            
        elif mode == "Voltage":
            self.current_ylabel = "Voltage (V)"
            wiring_text = WIRING_INSTRUCTIONS["Voltage"]
            ttk.Label(self.param_frame, text="Min V:").grid(row=0, column=0, sticky="e")
            self.param_vars["min_v"] = tk.DoubleVar(value=-10.0)
            ttk.Entry(self.param_frame, textvariable=self.param_vars["min_v"], width=6).grid(row=0, column=1)
            ttk.Label(self.param_frame, text="Max V:").grid(row=0, column=2, sticky="e")
            self.param_vars["max_v"] = tk.DoubleVar(value=10.0)
            ttk.Entry(self.param_frame, textvariable=self.param_vars["max_v"], width=6).grid(row=0, column=3)
            
        elif mode == "Thermocouple (TC)":
            self.current_ylabel = "Temp (°C)"
            wiring_text = WIRING_INSTRUCTIONS["Thermocouple (TC)"]
            ttk.Label(self.param_frame, text="Type:").grid(row=0, column=0, sticky="e")
            self.param_vars["tc_type"] = tk.StringVar(value="K")
            ttk.Combobox(self.param_frame, textvariable=self.param_vars["tc_type"], values=["K", "J", "T", "E"], state="readonly", width=4).grid(row=0, column=1)
            
        elif mode == "Current":
            self.current_ylabel = "Current (A)"
            wiring_text = WIRING_INSTRUCTIONS["Current"]
            ttk.Label(self.param_frame, text="Min I:").grid(row=0, column=0, sticky="e")
            self.param_vars["min_i"] = tk.DoubleVar(value=-0.02)
            ttk.Entry(self.param_frame, textvariable=self.param_vars["min_i"], width=6).grid(row=0, column=1)
            ttk.Label(self.param_frame, text="Max I:").grid(row=0, column=2, sticky="e")
            self.param_vars["max_i"] = tk.DoubleVar(value=0.02)
            ttk.Entry(self.param_frame, textvariable=self.param_vars["max_i"], width=6).grid(row=0, column=3)
            
        elif mode == "Raw Resistance":
            self.current_ylabel = "Resistance (Ohms)"
            ttk.Label(self.param_frame, text="Config:").grid(row=0, column=0, sticky="e")
            self.param_vars["wire"] = tk.StringVar(value="2-Wire")
            cb = ttk.Combobox(self.param_frame, textvariable=self.param_vars["wire"], values=["2-Wire", "4-Wire"], state="readonly", width=8)
            cb.grid(row=0, column=1)
            def update_res_wire(event=None):
                self.wiring_label.config(text=WIRING_INSTRUCTIONS[f"Raw Resistance ({self.param_vars['wire'].get()})"])
            cb.bind("<<ComboboxSelected>>", update_res_wire)
            wiring_text = WIRING_INSTRUCTIONS["Raw Resistance (2-Wire)"]
            
        elif mode == "2-Wire RTD (Workaround)":
            self.current_ylabel = "Temp (°C)"
            wiring_text = WIRING_INSTRUCTIONS["2-Wire RTD (Workaround)"]
            ttk.Label(self.param_frame, text="Uses Callendar-Van Dusen linearisation").grid(row=0, column=0, columnspan=4)
            
        elif mode == "Native RTD (3/4 Wire)":
            self.current_ylabel = "Temp (°C)"
            ttk.Label(self.param_frame, text="Config:").grid(row=0, column=0, sticky="e")
            self.param_vars["wire"] = tk.StringVar(value="4-Wire")
            cb = ttk.Combobox(self.param_frame, textvariable=self.param_vars["wire"], values=["3-Wire", "4-Wire"], state="readonly", width=8)
            cb.grid(row=0, column=1)
            def update_rtd_wire(event=None):
                self.wiring_label.config(text=WIRING_INSTRUCTIONS[f"Native RTD ({self.param_vars['wire'].get()})"])
            cb.bind("<<ComboboxSelected>>", update_rtd_wire)
            wiring_text = WIRING_INSTRUCTIONS["Native RTD (4-Wire)"]
            
        elif mode == "Wheatstone Bridge":
            self.current_ylabel = "Strain (mV/V)"
            ttk.Label(self.param_frame, text="Type:").grid(row=0, column=0, sticky="e")
            self.param_vars["bridge_type"] = tk.StringVar(value="Full")
            cb = ttk.Combobox(self.param_frame, textvariable=self.param_vars["bridge_type"], values=["Full", "Half", "Quarter"], state="readonly", width=8)
            cb.grid(row=0, column=1)
            def update_bridge_wire(event=None):
                self.wiring_label.config(text=WIRING_INSTRUCTIONS[f"Wheatstone Bridge ({self.param_vars['bridge_type'].get()})"])
            cb.bind("<<ComboboxSelected>>", update_bridge_wire)
            wiring_text = WIRING_INSTRUCTIONS["Wheatstone Bridge (Full)"]

        self.wiring_label.config(text=wiring_text)
        self.prepare_acquisition()

    def get_config_dict(self):
        if self.mode_combo.get() == "None":
            return None
        cfg = {"mode": self.mode_combo.get()}
        for k, var in self.param_vars.items():
            cfg[k] = var.get()
        return cfg

    def get_params_str(self):
        params = []
        for k, v in self.param_vars.items():
            params.append(f"{k}={v.get()}")
        return ", ".join(params) if params else "None"

    def prepare_acquisition(self):
        self.data_y.clear()
        self.data_time.clear()
        self.data_timestamps.clear()
        self.start_timestamp = time.time()
        self.ax.clear()
        self.ax.set_ylabel(self.current_ylabel)
        self.line, = self.ax.plot([], [], 'r-')
        self.canvas.draw()

    def append_data(self, raw_val, timestamp_str=None):
        """Called by the main global DAQ polling thread."""
        offset = self.offset_var.get()
        
        if self.mode_combo.get() == "2-Wire RTD (Workaround)":
            # Linearize resistance
            raw_val = (raw_val - 100.0) / 0.385
            
        adj_val = raw_val - offset
        
        self.data_y.append(adj_val)
        self.data_time.append(time.time() - self.start_timestamp)
        self.data_timestamps.append(timestamp_str or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])

    def redraw_plot(self):
        if not self.data_y:
            return
            
        mode = self.mode_combo.get()
        if mode == "None":
            return

        is_time_axis = (self.xaxis_var.get() == "Time (s)")
        
        x_data = self.data_time if is_time_axis else list(range(len(self.data_y)))
        
        self.line.set_data(x_data, self.data_y)
        
        x_min, x_max = min(x_data), max(x_data)
        if x_min == x_max: x_max += 1
        
        # Squeeze X axis dynamically starting from 0 with a 10% right margin
        x_min_display = 0
        x_max_display = x_max + (x_max - x_min_display) * 0.1 if x_max > 0 else 1.0
        self.ax.set_xlim(x_min_display, x_max_display)
        self.ax.set_xlabel("Time (s)" if is_time_axis else "Sample No")
        
        # Auto-scale Y axis 
        y_min, y_max = min(self.data_y), max(self.data_y)
        margin = (y_max - y_min) * 0.1 if y_max != y_min else 1.0
        self.ax.set_ylim(y_min - margin, y_max + margin)
        
        self.fig.tight_layout()
        self.canvas.draw()
        
        # Update Digital Display
        last_5 = self.data_y[-5:]
        while len(last_5) < 5:
            last_5.insert(0, None)
            
        disp_text = "Live Data:\n"
        for v in reversed(last_5):
            if v is not None:
                disp_text += f"{v:.6f}\n"
            else:
                disp_text += "--\n"
        self.digital_display.config(text=disp_text)

    def save_graph(self, save_dir, run_no):
        """Save this quadrant's graph as a PNG in the session folder."""
        mode = self.mode_combo.get()
        if mode == "None" or not self.data_y:
            return
        chan_label = self.channel_combo.get().replace('/', '_')
        img_name = f"Run{run_no}_Ch{self.channel_id}_{chan_label}_graph.png"
        img_path = os.path.join(save_dir, img_name)
        try:
            self.fig.savefig(img_path, bbox_inches='tight', dpi=150)
            self.master_app.session.files.add(img_name)
        except Exception as e:
            print(f"Failed to save graph for Ch{self.channel_id}: {e}")


class cDAQApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("cDAQ Universal GUI Dashboard")
        self.geometry("1100x850")
        
        self.is_running = True
        self.session = AppSession()
        self.daq_manager = DAQManager()
        self.is_acquiring = False
        self.acquisition_thread = None
        
        style = ttk.Style(self)
        style.theme_use('clam')
        
        # Top Header Frame
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10, pady=10)
        
        title = ttk.Label(top_frame, text="National Instruments cDAQ Multi-Channel Acquisition", font=("Segoe UI", 16, "bold"))
        title.pack(side=tk.LEFT)
        
        self.btn_agent_review = ttk.Button(top_frame, text="Agent Review", command=self.run_agent_review)
        self.btn_agent_review.pack(side=tk.RIGHT, padx=5)
        
        self.save_session_btn = ttk.Button(top_frame, text="Save Session Logged Data", command=self.save_session)
        self.save_session_btn.pack(side=tk.RIGHT, padx=5)

        self.btn_global_toggle = ttk.Button(top_frame, text="START ACQUISITION", command=self.toggle_acquisition)
        self.btn_global_toggle.pack(side=tk.RIGHT, padx=5)
        
        # Grid container
        grid_frame = ttk.Frame(self)
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.rowconfigure(0, weight=1)
        grid_frame.rowconfigure(1, weight=1)
        
        # 4 quadrants
        self.quadrants = []
        self.q1 = ChannelQuadrant(grid_frame, 1, master_app=self)
        self.q1.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.quadrants.append(self.q1)
        
        self.q2 = ChannelQuadrant(grid_frame, 2, master_app=self)
        self.q2.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.quadrants.append(self.q2)
        
        self.q3 = ChannelQuadrant(grid_frame, 3, master_app=self)
        self.q3.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.quadrants.append(self.q3)
        
        self.q4 = ChannelQuadrant(grid_frame, 4, master_app=self)
        self.q4.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        self.quadrants.append(self.q4)
        
        # Threading Queues & Caches
        self.db_queue = queue.Queue()
        self.active_channels = []
        self.db_consumer_thread = None
        
        # Insights Panel
        self.insights_text = tk.Text(state=tk.NORMAL, height=6)
        self.insights_text.pack(fill=tk.X, padx=10, pady=5)
        
        self.agent_queue = queue.Queue()
        self.agent = cDAQ_Agent.LiveReviewAgent(self.session.temp_dir, self.agent_queue)
        self.agent.start()
        
        self.poll_agent_queue()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def reset_sql_table(self):
        """Truncates the SQL Server table at application startup."""
        conn_str = (
            "Driver={ODBC Driver 17 for SQL Server};"
            "Server=DESKTOP-2B3BEA7\\SQLEXPRESS;"
            "Database=cDAQ_Telemetry;"
            "Trusted_Connection=yes;"
        )
        try:
            with pyodbc.connect(conn_str) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("TRUNCATE TABLE LiveStream;")
                    conn.commit()
            print("[LOG] SQL Table 'LiveStream' reset successfully.")
        except Exception as e:
            print(f"SQL Reset Warning: {e}")

    def set_gui_state(self, state):
        for q in self.quadrants:
            q.device_combo.config(state="readonly" if state == tk.NORMAL else tk.DISABLED)
            q.channel_combo.config(state="readonly" if state == tk.NORMAL else tk.DISABLED)
            q.mode_combo.config(state="readonly" if state == tk.NORMAL else tk.DISABLED)
            for child in q.param_frame.winfo_children():
                if isinstance(child, ttk.Combobox):
                    child.config(state="readonly" if state == tk.NORMAL else tk.DISABLED)
                elif isinstance(child, ttk.Scale):
                    child.config(state=state)
                    
        # Toggle button text is managed by toggle_acquisition / stop_acquisition

    def toggle_acquisition(self):
        if self.is_acquiring:
            self.stop_acquisition()
        else:
            self.start_acquisition()

    def start_acquisition(self):
        # 1. Build master config & cache active channels
        master_config = {}
        self.active_channels = []
        
        for q in self.quadrants:
            cfg = q.get_config_dict()
            if cfg is not None:
                chan = q.channel_combo.get()
                master_config[chan] = cfg
                
                # Cache static UI info to avoid cross-thread .get() penalties
                self.active_channels.append({
                    'quadrant': q,
                    'chan': chan,
                    'mode': cfg['mode']
                })
                
                q.prepare_acquisition()
                
        if not master_config:
            messagebox.showwarning("Warning", "No active channels configured to start.")
            return
            
        # 2. Pass to DAQManager
        try:
            self.daq_manager.configure(master_config)
            self.daq_manager.start()
        except Exception as e:
            messagebox.showerror("DAQ Error", f"Failed to start hardware tasks:\n{e}")
            return
            
        self.is_acquiring = True
        self.btn_global_toggle.config(text="STOP ACQUISITION")
        self.set_gui_state(tk.DISABLED)
        
        # Clear queue from previous runs
        while not self.db_queue.empty():
            try:
                self.db_queue.get_nowait()
            except queue.Empty:
                break
                
        # 3. Start Database Consumer Thread
        self.db_consumer_thread = threading.Thread(target=self.database_consumer_loop, daemon=True)
        self.db_consumer_thread.start()
        
        # 4. Start High-Speed Acquisition Producer Thread
        self.acquisition_thread = threading.Thread(target=self.acquisition_loop, daemon=True)
        self.acquisition_thread.start()
        
        self.gui_update_loop()

    def acquisition_loop(self):
        """Producer Thread: Strictly reads DAQ hardware and enqueues data."""
        while self.is_acquiring:
            try:
                results = self.daq_manager.read_all()
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                
                tick_data = []
                for channel_info in self.active_channels:
                    chan = channel_info['chan']
                    if chan in results:
                        val = results[chan]
                        q = channel_info['quadrant']
                        mode = channel_info['mode']
                        
                        # 1. Update internal graph memory natively
                        q.append_data(val, timestamp_str=ts)
                        
                        # 2. Package for the SQL consumer thread
                        tick_data.append((ts, chan, mode, float(val)))
                        
                if tick_data:
                    self.db_queue.put(tick_data)
                    
                time.sleep(0.05)  # 50 ms loop execution window (20 Hz polling)
                
            except Exception as e:
                print(f"Acquisition loop error: {e}")
                break
                
        self.daq_manager.stop()

    def database_consumer_loop(self):
        """Consumer Thread: Pulls from queue and pushes bulk batches to SQL Server."""
        conn_str = (
            "Driver={ODBC Driver 17 for SQL Server};"
            "Server=DESKTOP-2B3BEA7\\SQLEXPRESS;"
            "Database=cDAQ_Telemetry;"
            "Trusted_Connection=yes;"
        )
        db_batch = []
        
        try:
            self.reset_sql_table()
            
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            cursor.fast_executemany = True  # Activates high-speed bulk inserts
            conn.autocommit = False
            
            while self.is_acquiring or not self.db_queue.empty():
                try:
                    # Pull from queue (timeout allows it to check `self.is_acquiring` flag to exit gracefully)
                    tick_data = self.db_queue.get(timeout=1.0)
                    db_batch.extend(tick_data)
                    
                    # Commit every 100 rows
                    if len(db_batch) >= 100:
                        cursor.executemany(
                            "INSERT INTO LiveStream (Timestamp, Channel, Mode, Value) VALUES (?, ?, ?, ?)",
                            db_batch
                        )
                        conn.commit()
                        db_batch.clear()
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Database insertion error: {e}")
                    
            # Safe structural flush when queue is empty and acquisition stopped
            if db_batch:
                cursor.executemany(
                    "INSERT INTO LiveStream (Timestamp, Channel, Mode, Value) VALUES (?, ?, ?, ?)", 
                    db_batch
                )
                conn.commit()
                db_batch.clear()
                
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Database connection error: {e}")
            self.after(0, self.stop_acquisition)

    def gui_update_loop(self):
        if self.is_acquiring:
            for q in self.quadrants:
                q.redraw_plot()
            # Downsample heavy Matplotlib redrawing to 1 Hz (every 1000ms)
            self.after(1000, self.gui_update_loop)

    def stop_acquisition(self):
        if not self.is_acquiring: return
        self.is_acquiring = False
        
        # daq_manager.stop() is now handled by acquisition_loop exiting
        self.daq_manager.disconnect()
        
        self.btn_global_toggle.config(text="START ACQUISITION")
        self.set_gui_state(tk.NORMAL)
        
        # Auto-save unified CSV + per-channel graphs
        self.save_run_data()

    def save_run_data(self):
        """Write a single unified CSV for this run with all 4 channels, plus per-channel graph PNGs."""
        self.session.run_count += 1
        run_no = self.session.run_count
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # --- Build column headers ---
        # Format: Sample No, Timestamp, Ch1_Mode, Ch2_Mode, Ch3_Mode, Ch4_Mode
        col_modes = []
        for q in self.quadrants:
            mode = q.mode_combo.get()
            if mode == "None":
                col_modes.append(f"Ch{q.channel_id}_Inactive")
            else:
                mode_str = mode.replace(' ', '_').replace('/', '_')
                col_modes.append(f"Ch{q.channel_id}_{mode_str}")
        
        headers = ["Sample No", "Timestamp"] + col_modes
        
        # --- Build conditions row ---
        cond_parts = []
        for q in self.quadrants:
            mode = q.mode_combo.get()
            if mode == "None":
                cond_parts.append(f"Ch{q.channel_id}: Inactive")
            else:
                cond_parts.append(f"Ch{q.channel_id}: {mode} | {q.get_params_str()} | Offset: {q.offset_var.get():.2f}")
        conditions_row = [" | ".join(cond_parts)]
        
        # --- Determine max sample count across all channels ---
        max_samples = max((len(q.data_y) for q in self.quadrants), default=0)
        
        if max_samples == 0:
            return  # Nothing to save
        
        # --- Collect timestamps from any active channel ---
        # All active channels share the same timestamps (written from acquisition_loop)
        all_timestamps = []
        for q in self.quadrants:
            if q.data_timestamps:
                all_timestamps = q.data_timestamps
                break
        
        # Pad if needed
        while len(all_timestamps) < max_samples:
            all_timestamps.append("")
        
        # --- Write CSV ---
        csv_name = f"Run{run_no}_{run_ts}.csv"
        csv_path = os.path.join(self.session.temp_dir, csv_name)
        
        try:
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(conditions_row)
                writer.writerow(headers)
                for i in range(max_samples):
                    row = [i + 1, all_timestamps[i] if i < len(all_timestamps) else ""]
                    for q in self.quadrants:
                        if q.mode_combo.get() == "None" or i >= len(q.data_y):
                            row.append("")  # Inactive or no data yet
                        else:
                            row.append(q.data_y[i])
                    writer.writerow(row)
            
            self.session.files.add(csv_name)
            print(f"[LOG] Run {run_no} data saved: {csv_name}")
        except Exception as e:
            print(f"Failed to save run CSV: {e}")
        
        # --- Save per-channel graphs ---
        for q in self.quadrants:
            q.save_graph(self.session.temp_dir, run_no)

    def run_agent_review(self):
        """Open a popup window showing per-channel analysis of all current session CSVs."""
        temp_dir = self.session.temp_dir
        if not os.path.exists(temp_dir):
            messagebox.showinfo("Agent Review", "No session data to review yet.")
            return

        csv_files = sorted([
            os.path.join(temp_dir, f)
            for f in os.listdir(temp_dir)
            if f.endswith('.csv')
        ])
        if not csv_files:
            messagebox.showinfo("Agent Review", "No CSV files found. Run an acquisition first.")
            return

        # Run analysis (no debounce, immediate, all files)
        results = self.agent.review_all_files(csv_files)

        # --- Build popup ---
        popup = tk.Toplevel(self)
        popup.title("Agent Review — Session Analysis")
        popup.geometry("950x500")
        popup.resizable(True, True)

        ttk.Label(popup,
                  text="Live Review Agent — Per-Channel Analysis",
                  font=("Segoe UI", 13, "bold")).pack(pady=(12, 4), padx=12, anchor="w")
        ttk.Label(popup,
                  text=f"Session folder: {temp_dir}  |  Files analysed: {len(results)}",
                  font=("Segoe UI", 9), foreground="grey").pack(padx=12, anchor="w")

        # Treeview
        cols = ("status", "channel", "n", "mean", "std", "min", "max", "dvdt", "conditions")
        col_labels = ("Status", "Channel / Mode", "N", "Mean", "Std Dev", "Min", "Max", "dv/dt Max", "Conditions")

        frame = ttk.Frame(popup)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        vsb = ttk.Scrollbar(frame, orient="vertical")
        hsb = ttk.Scrollbar(frame, orient="horizontal")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                            yscrollcommand=vsb.set, xscrollcommand=hsb.set, height=14)
        vsb.config(command=tree.yview)
        hsb.config(command=tree.xview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(fill=tk.BOTH, expand=True)

        widths = (80, 200, 55, 90, 90, 90, 90, 90, 300)
        for col, label, w in zip(cols, col_labels, widths):
            tree.heading(col, text=label)
            tree.column(col, width=w, anchor="center" if col != "conditions" else "w", minwidth=50)

        # Tag colours
        tree.tag_configure("ok",      background="#d4edda", foreground="#155724")
        tree.tag_configure("anomaly", background="#f8d7da", foreground="#721c24")
        tree.tag_configure("error",   background="#fff3cd", foreground="#856404")

        for r in results:
            if r["error"]:
                tree.insert("", tk.END, values=(
                    "[ERROR]", r["filename"], "-", "-", "-", "-", "-", "-",
                    r["error"]
                ), tags=("error",))
            else:
                status = "[ANOMALY]" if r["anomaly"] else "[OK]"
                tag    = "anomaly"  if r["anomaly"] else "ok"
                tree.insert("", tk.END, values=(
                    status,
                    r["channel_label"],
                    r["n_samples"],
                    f"{r['mean']:.4f}",
                    f"{r['std']:.4f}",
                    f"{r['min']:.4f}",
                    f"{r['max']:.4f}",
                    f"{r['max_gradient']:.2f}",
                    r["conditions"],
                ), tags=(tag,))

        # Summary bar
        n_anomalies = sum(1 for r in results if r["anomaly"] and not r["error"])
        n_ok        = sum(1 for r in results if not r["anomaly"] and not r["error"])
        n_errors    = sum(1 for r in results if r["error"])
        summary_fg  = "red" if n_anomalies else "green"
        ttk.Label(popup,
                  text=f"Summary:  [OK] {n_ok}   [ANOMALY] {n_anomalies}   [ERROR] {n_errors}",
                  font=("Segoe UI", 10, "bold"), foreground=summary_fg
                  ).pack(pady=(0, 10))

    def poll_agent_queue(self):
        if not self.is_running:
            return
            
        try:
            while True:
                msg = self.agent_queue.get_nowait()
                self.insights_text.config(state=tk.NORMAL)
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.insights_text.insert(tk.END, f"[{timestamp}] {msg}\n")
                self.insights_text.see(tk.END)
                self.insights_text.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.after(500, self.poll_agent_queue)

    def save_session(self):
        if not self.session.files:
            messagebox.showinfo("Empty Session", "No data has been logged yet in this session.")
            return
            
        dialog = tk.Toplevel(self)
        dialog.title("Select Session Files to Zip")
        dialog.geometry("400x300")
        
        ttk.Label(dialog, text="Select the CSV files to package into the session ZIP:", font=("Segoe UI", 10)).pack(pady=10)
        
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, yscrollcommand=scrollbar.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        
        for f in sorted(list(self.session.files)):
            listbox.insert(tk.END, f)
            listbox.select_set(tk.END)
            
        def on_confirm():
            selected = listbox.curselection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select at least one file.")
                return
                
            selected_files = [listbox.get(i) for i in selected]
            zip_filename = f"cDAQ_{self.session.session_str}.zip"
            
            zip_path = filedialog.asksaveasfilename(
                initialfile=zip_filename,
                defaultextension=".zip", 
                filetypes=[("ZIP Archive", "*.zip")]
            )
            
            if zip_path:
                try:
                    with zipfile.ZipFile(zip_path, 'w') as zf:
                        for f in selected_files:
                            file_path = os.path.join(self.session.temp_dir, f)
                            if os.path.exists(file_path):
                                zf.write(file_path, arcname=f)
                    messagebox.showinfo("Success", f"Session saved successfully to:\n{zip_path}")
                    dialog.destroy()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save zip: {e}")
                    
        ttk.Button(dialog, text="Package Selected to ZIP", command=on_confirm).pack(pady=15)

    def on_closing(self):
        self.is_running = False
        self.stop_acquisition()
        try:
            self.agent.stop()
        except:
            pass
            
        try:
            if os.path.exists(self.session.temp_dir):
                shutil.rmtree(self.session.temp_dir)
        except Exception as e:
            print(f"Failed to cleanup temp dir: {e}")
        self.destroy()
        exit()

if __name__ == "__main__":
    app = cDAQApp()
    app.mainloop()
