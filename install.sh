#!/bin/bash
set -e

echo "=== Pi5 PTP Node Installer ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ----------------------------------------------------------------------
#  Hostname + Networking
# ----------------------------------------------------------------------
echo "Setting hostname..."
echo "ptp" > /etc/hostname
hostnamectl set-hostname ptp

if ! grep -q "interface eth0" /etc/dhcpcd.conf; then
cat <<EOF >> /etc/dhcpcd.conf

hostname ptp

interface eth0
static ip_address=192.168.1.10/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1
EOF
fi

# ----------------------------------------------------------------------
#  Directories
# ----------------------------------------------------------------------
echo "Creating directories..."
mkdir -p /etc/pi5-ptp-node
mkdir -p /var/spool/pi5-ptp-node
mkdir -p /opt/pi5-ptp-node/gps
mkdir -p /var/log/pi5-ptp-node

# ----------------------------------------------------------------------
#  Copy Python modules
# ----------------------------------------------------------------------
echo "Installing Python modules..."
cp "$SCRIPT_DIR/gps/"*.py /opt/pi5-ptp-node/gps/

# ----------------------------------------------------------------------
#  Environment file
# ----------------------------------------------------------------------
if [ ! -f /etc/pi5-ptp-node/streamer.env ]; then
    echo "Installing example environment file..."
    cp "$SCRIPT_DIR/gps/streamer.env.example" /etc/pi5-ptp-node/streamer.env
fi

# ----------------------------------------------------------------------
#  Packages
# ----------------------------------------------------------------------
echo "Installing packages..."
apt update
apt install -y gpsd gpsd-clients chrony pps-tools python3 python3-pip

# ----------------------------------------------------------------------
#  Device overlays
# ----------------------------------------------------------------------
echo "Configuring overlays..."

if ! grep -q "dtoverlay=pps-gpio" /boot/firmware/config.txt; then
    echo "dtoverlay=pps-gpio,gpiopin=18" >> /boot/firmware/config.txt
fi

if ! grep -q "enable_uart=1" /boot/firmware/config.txt; then
    echo "enable_uart=1" >> /boot/firmware/config.txt
    echo "dtoverlay=uart0" >> /boot/firmware/config.txt
fi

# ----------------------------------------------------------------------
#  Udev rules
# ----------------------------------------------------------------------
echo "Installing udev rules..."
cp "$SCRIPT_DIR/gps/99-gnss.rules" /etc/udev/rules.d/
udevadm control --reload-rules

# ----------------------------------------------------------------------
#  gpsd config
# ----------------------------------------------------------------------
echo "Installing gpsd configs..."
cp "$SCRIPT_DIR/gps/gpsd.usb.conf" /etc/default/gpsd.usb.conf
cp "$SCRIPT_DIR/gps/gpsd.hat.conf" /etc/default/gpsd.hat.conf

# ----------------------------------------------------------------------
#  chrony config
# ----------------------------------------------------------------------
echo "Installing chrony config..."
cp "$SCRIPT_DIR/chrony/chrony.conf" /etc/chrony/chrony.conf

# ----------------------------------------------------------------------
#  systemd overrides
# ----------------------------------------------------------------------
echo "Installing systemd overrides..."
mkdir -p /etc/systemd/system/gpsd.service.d
cp "$SCRIPT_DIR/systemd/gpsd.service.d/override.conf" /etc/systemd/system/gpsd.service.d/

mkdir -p /etc/systemd/system/chrony.service.d
cp "$SCRIPT_DIR/systemd/chrony.service.d/override.conf" /etc/systemd/system/chrony.service.d/

# ----------------------------------------------------------------------
#  systemd services
# ----------------------------------------------------------------------
echo "Installing systemd services..."
cp "$SCRIPT_DIR/systemd/gps-streamer.service" /etc/systemd/system/
cp "$SCRIPT_DIR/systemd/gps-watchdog.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable gpsd
systemctl enable chrony
systemctl enable gps-streamer
systemctl enable gps-watchdog

# ----------------------------------------------------------------------
#  Final
# ----------------------------------------------------------------------
echo "=== Installation complete. A reboot is recommended. ==="
