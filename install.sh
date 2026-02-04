#!/bin/bash
set -e

echo "=== Installing Pi5 PTP Node Base System ==="

# Set hostname
echo "ptp" > /etc/hostname
hostnamectl set-hostname ptp

# Configure static IP
if ! grep -q "interface eth0" /etc/dhcpcd.conf; then
cat <<EOF >> /etc/dhcpcd.conf

hostname ptp

interface eth0
static ip_address=192.168.1.10/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1
EOF
fi

# Create config directory
mkdir -p /etc/pi5-ptp-node
mkdir -p /var/spool/pi5-ptp-node

# Copy example env if none exists
if [ ! -f /etc/pi5-ptp-node/streamer.env ]; then
    cp gps/streamer.env.example /etc/pi5-ptp-node/streamer.env
fi

# Install packages
apt update
apt install -y gpsd gpsd-clients chrony pps-tools python3 python3-pip

# Enable PPS overlay
if ! grep -q "dtoverlay=pps-gpio" /boot/firmware/config.txt; then
    echo "dtoverlay=pps-gpio,gpiopin=18" >> /boot/firmware/config.txt
fi

# Enable UART for HAT
if ! grep -q "enable_uart=1" /boot/firmware/config.txt; then
    echo "enable_uart=1" >> /boot/firmware/config.txt
    echo "dtoverlay=uart0" >> /boot/firmware/config.txt
fi

# Install udev rules
cp gps/99-gnss.rules /etc/udev/rules.d/
udevadm control --reload-rules

# Install systemd overrides
mkdir -p /etc/systemd/system/gpsd.service.d
cp systemd/gpsd.service.d/override.conf /etc/systemd/system/gpsd.service.d/

mkdir -p /etc/systemd/system/chrony.service.d
cp systemd/chrony.service.d/override.conf /etc/systemd/system/chrony.service.d/

# Install chrony config
cp chrony/chrony.conf /etc/chrony/chrony.conf

# Enable services
systemctl daemon-reload
systemctl enable gpsd
systemctl enable chrony

echo "=== Base install complete. Reboot recommended. ==="
