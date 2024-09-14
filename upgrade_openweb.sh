#!/bin/bash

# Check the status of the service

# Change to the application directory
echo "Changing to /usr/openweb/ directory..."
cd /usr/openweb/ || { echo "Failed to change directory to /usr/openweb/"; exit 1; }

# Stop the service before upgrading
echo "Stopping run_script.service..."
sudo systemctl stop run_script.service

# Backup the current configuration
echo "Backing up config.json..."
cp ./venv/lib64/python3.11/site-packages/data/webui.db /usr/webui.old

# Activate the virtual environment
echo "Activating the virtual environment..."
source ./venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Upgrade open-webui
echo "Upgrading open-webui..."
pip install --upgrade open-webui 

# Check the new version of open-webui
echo "Checking the new version of open-webui..."
pip show open-webui 

# Restart the service after upgrades
echo "Starting run_script.service..."
sudo systemctl start run_script.service

echo "Upgrade process completed successfully!"
