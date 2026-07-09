# Real-Time Multi-Mode Telemetry Station (NI-DAQmx & Power BI Pipeline)

This repository contains a high-speed, asynchronous data acquisition (DAQ) and telemetry system engineered to stream and visualize multi-channel physical measurements in near-real-time. The application couples a lightweight Python control interface with National Instruments (NI) hardware, a dedicated SQL Server caching engine, and a dynamic Power BI live-updating intelligence dashboard.

## 🏗️ System Architecture Overview

The system is split into three decoupled operational layers designed to eliminate thread bottlenecks, optimize processor overhead, and achieve continuous high-frequency sampling:

### 1. Edge Hardware & Management Layer (`cDAQ_Manager.py`)

* **Hardware Interface:** Manages an **NI 9219** universal analog input module, dynamically grouping channels based on their electrical parameters.
* **Polymorphic Configurations:** Configures physical channels on-the-fly to handle a diverse array of physical inputs, such as **Voltages, Thermocouples (TCs), RTDs, Currents, Resistance Bridges, and Strain Gauges**.
* **Vectorized Codecs:** Utilizes an optimized, string-less lookup cache to scale and process raw measurement arrays directly inside hardware buffers, completely bypassing Python interpreter overhead.

### 2. High-Speed Asynchronous Headless Router (`cDAQ_GUI.py`)

To prevent data-drop and UI freezing at fast sample rates (50Hz+), the Python control deck utilizes a **Dual-Thread Producer-Consumer Architecture**:

* **The Control UI:** A streamlined Tkinter application providing an operator workspace to select channel types, read wiring pinpoint instructions natively, and start/stop live capture. It performs *Zero-Overhead UI Polling* by locking a snapshot of active parameters into memory before launching pipelines.
* **Thread A (The Producer Loop):** A dedicated hardware loop that continuously extracts raw values from the NI driver and immediately offloads them to an in-memory `queue.Queue()`. It never interacts with the visual UI or network layers, keeping its cycle time $<2\text{ ms}$.
* **Thread B (The SQL Consumer Loop):** Runs asynchronously in the background. It extracts batches of rows from the queue, pools them, and executes massive bulk database uploads using Microsoft SQL Server's high-speed network protocols (`fast_executemany = True` with disabled transactional auto-commits).
* **Reset Engine:** Features a structural "Clear Dashboard" macro button that allows the user to truncate active server records on a single click, instantly wiping downstream graphs for a clean testing session.

### 3. Business Intelligence Presentation Layer (Power BI Desktop)

Rather than wasting CPU cycles forcing Python to draw heavy Matplotlib animations, visualization is fully offloaded to a dedicated reporting canvas.

* **DirectQuery Stream Integration:** Bypasses Power BI's restrictive "Import Mode" by linking directly to SQL Server as a live data pipe. This forces Power BI to unlock high-frequency **Auto-Page Refresh** loops (set to 1–2 second intervals).
* **Dynamic Title & Unit Tracking:** Uses advanced DAX measures to track the latest incoming database metadata per channel. The graphs dynamically update their chart banners and vertical Y-axes text layout labels (e.g., swapping labels seamlessly from `Voltage (V)` to `Thermocouple (°C)`) to instantly reflect physical adjustments made on the Tkinter control deck.

---

## 🛠️ Tech Stack & Dependencies

* **Language:** Python 3.x
* **Hardware Driver:** `nidaqmx` (National Instruments DAQmx API wrapper)
* **GUI Framework:** `tkinter` (TTK styled widgets)
* **Database Interface:** `pyodbc` (SQL Server Native Client connection pipeline)
* **Database Engine:** Microsoft SQL Server (SSMS)
* **Visualization Engine:** Power BI Desktop (DirectQuery Engine + DAX Expression Matrix)

---

## 🚀 Key Performance Enhancements Implemented

* **Headless Optimization:** Removed Matplotlib chart drawing and offline analytics processing agents directly from the local execution application, resulting in a **~75% reduction in CPU core load**.
* **Persistent Connections:** Reused a single active database handshake instead of creating/closing network connections inside high-speed loops.
* **Asynchronous Processing:** Divided hardware ingestion from network writing via thread queues to prevent I/O blocking from stalling sensitive hardware timers.
