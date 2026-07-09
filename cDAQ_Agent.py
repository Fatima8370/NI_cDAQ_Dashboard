import os
import time
import pandas as pd
import numpy as np
import queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class DAQAgentHandler(FileSystemEventHandler):
    def __init__(self, agent):
        self.agent = agent

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.csv'):
            self.agent.process_csv_to_queue(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.csv'):
            self.agent.process_csv_to_queue(event.src_path)


class LiveReviewAgent:
    def __init__(self, watch_dir, message_queue):
        self.watch_dir = watch_dir
        self.message_queue = message_queue
        self.observer = Observer()
        self.last_process_time = {}  # debounce for watchdog events only

    def start(self):
        if not os.path.exists(self.watch_dir):
            os.makedirs(self.watch_dir, exist_ok=True)

        event_handler = DAQAgentHandler(self)
        self.observer.schedule(event_handler, self.watch_dir, recursive=False)
        self.observer.start()
        self.message_queue.put("[INFO] Live Review Agent active. Awaiting data...")

    def stop(self):
        self.observer.stop()
        self.observer.join()

    def _analyse_file(self, filepath) -> list:
        """
        Core analysis: reads a unified multi-channel CSV and returns a list
        of result dicts, one per channel column.
        
        New CSV format:
            Row 0: Conditions string (one merged cell)
            Row 1: Sample No, Timestamp, Ch1_Mode, Ch2_Mode, Ch3_Mode, Ch4_Mode
            Row 2+: Data rows
            
        Inactive channels have header like "Ch1_Inactive" and blank data cells.
        """
        results = []
        filename = os.path.basename(filepath)

        try:
            with open(filepath, 'r') as f:
                conditions_line = f.readline().strip()

            df = pd.read_csv(filepath, skiprows=1)

            if len(df) < 2:
                results.append({
                    "filepath": filepath,
                    "filename": filename,
                    "channel_label": "All Channels",
                    "conditions": conditions_line,
                    "n_samples": len(df),
                    "mean": None, "std": None, "min": None, "max": None,
                    "max_gradient": None, "anomaly": False,
                    "error": "Not enough data (< 2 samples)."
                })
                return results

            # Identify channel columns (everything except 'Sample No' and 'Timestamp')
            channel_cols = [c for c in df.columns if c not in ("Sample No", "Timestamp")]

            for col in channel_cols:
                r = {
                    "filepath": filepath,
                    "filename": filename,
                    "channel_label": col.replace("_", " "),
                    "conditions": conditions_line,
                    "n_samples": 0,
                    "mean": None, "std": None, "min": None, "max": None,
                    "max_gradient": None, "anomaly": False,
                    "error": None,
                }

                # Check if channel is inactive (header contains "Inactive")
                if "Inactive" in col:
                    r["error"] = "Channel inactive"
                    results.append(r)
                    continue

                # Get numeric values, drop blanks / NaN
                values = pd.to_numeric(df[col], errors='coerce').dropna()

                if len(values) < 2:
                    r["error"] = "Not enough data (< 2 samples)."
                    results.append(r)
                    continue

                r["n_samples"] = len(values)
                r["mean"] = float(values.mean())
                r["std"] = float(values.std())
                r["min"] = float(values.min())
                r["max"] = float(values.max())

                # First-derivative anomaly detection
                dv = np.diff(values.to_numpy())
                dt = 0.2  # nominal sampling interval (s)
                dv_dt = np.abs(dv / dt)
                max_grad = float(np.max(dv_dt))
                r["max_gradient"] = max_grad

                # Flag if max dv/dt is 10x the std AND exceeds 1.0 unit/s
                if r["std"] > 0 and max_grad > (r["std"] * 10) and max_grad > 1.0:
                    r["anomaly"] = True

                results.append(r)

        except Exception as e:
            results.append({
                "filepath": filepath,
                "filename": filename,
                "channel_label": "File Error",
                "conditions": "",
                "n_samples": 0,
                "mean": None, "std": None, "min": None, "max": None,
                "max_gradient": None, "anomaly": False,
                "error": str(e),
            })

        return results

    # ------------------------------------------------------------------
    # Background watchdog path (debounced, pushes to queue)
    # ------------------------------------------------------------------
    def process_csv_to_queue(self, filepath):
        """Called by watchdog observer. Debounced to avoid duplicate events."""
        current_time = time.time()
        if filepath in self.last_process_time and (current_time - self.last_process_time[filepath] < 2.0):
            return
        self.last_process_time[filepath] = current_time
        time.sleep(0.5)

        channel_results = self._analyse_file(filepath)
        for r in channel_results:
            if r["error"]:
                if r["error"] != "Channel inactive":
                    self.message_queue.put(f"[AGENT ERROR] {r['filename']} | {r['channel_label']}: {r['error']}")
            else:
                status = "[ANOMALY]" if r["anomaly"] else "[OK]"
                if r["anomaly"]:
                    msg = (f"{status} {r['channel_label']} | "
                           f"dv/dt max: {r['max_gradient']:.2f} -> Possible loose terminal / EMI.")
                else:
                    msg = (f"{status} {r['channel_label']} | "
                           f"Mean: {r['mean']:.4f}, Std: {r['std']:.4f}, N={r['n_samples']}")
                self.message_queue.put(msg)

    # ------------------------------------------------------------------
    # On-demand review path (no debounce, returns structured results)
    # ------------------------------------------------------------------
    def review_all_files(self, csv_files: list) -> list:
        """
        Analyse a list of CSV file paths immediately (no debounce).
        Returns a flat list of result dicts (multiple per file — one per channel).
        Also pushes a summary line per channel into message_queue.
        """
        all_results = []
        for fp in csv_files:
            channel_results = self._analyse_file(fp)
            for r in channel_results:
                all_results.append(r)
                if r["error"]:
                    if r["error"] != "Channel inactive":
                        self.message_queue.put(f"[AGENT ERROR] {r['filename']} | {r['channel_label']}: {r['error']}")
                else:
                    status = "[ANOMALY]" if r["anomaly"] else "[OK]"
                    self.message_queue.put(
                        f"{status} {r['channel_label']} | "
                        f"Mean: {r['mean']:.4f}, Std: {r['std']:.4f}, "
                        f"N={r['n_samples']}, dv/dt max: {r['max_gradient']:.2f}"
                    )
        return all_results
