# pi5-ptp
PTP server using NEO-M8T with hot data streaming to influxdb


# Pi5 GNSS Timing Node  
Professional‑grade GNSS → PPS → Chrony → PTP timing appliance for Raspberry Pi 5

This repository contains a complete, turnkey timing node built for the Raspberry Pi 5.  
It integrates:

- GNSS receiver (USB or UART HAT)
- PPS discipline via GPIO18
- gpsd for GNSS ingest
- chrony for oscillator discipline
- PTP (ptp4l + phc2sys) for network time distribution
- InfluxDB telemetry streaming
- Local disk‑backed spooler for offline buffering
- Watchdog for autonomous recovery

The result is a **self‑healing, operator‑grade timing node** suitable for labs, observatories, and distributed timing networks.

---

## 🚀 Features

### GNSS + PPS
- Supports USB GNSS receivers  
- Supports Waveshare NEO‑M8T HAT via UART  
- PPS discipline via GPIO18  
- Automatic device detection via udev rules  

### Timing Stack
- gpsd for GNSS ingest  
- chrony for oscillator discipline  
- PPS lock  
- PTP (ptp4l + phc2sys) ready  

### Telemetry Pipeline
- High‑rate GNSS satellite metrics  
- Fix‑level epoch metrics  
- Chrony tracking metrics  
- InfluxDB v2 write API  
- Hybrid spooler (live data prioritized, backlog drains in background)  

### Resilience
- Local 20 GB FIFO spool  
- Automatic service restarts  
- Automatic recovery from GNSS outages  
- Automatic recovery from Influx outages  
- Optional reboot after prolonged unhealthy state  

---

## 📦 Repository Structure
