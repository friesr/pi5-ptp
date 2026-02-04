#!/bin/bash

set -e

echo "Creating spool directory..."
sudo mkdir -p /var/spool/pi5-ptp-node
sudo chown pi:pi /var/spool/pi5-ptp-node

echo "Installing gps_streamer.service..."
sudo cp services/gps_streamer.service /etc/systemd/system/

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Enabling and starting gps_streamer..."
sudo systemctl enable --now gps_streamer.service

echo "Installation complete."
