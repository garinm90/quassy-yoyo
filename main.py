#! /usr/bin/python3
import serial
import requests
import subprocess
import logging
from logging.handlers import TimedRotatingFileHandler
from time import sleep
from pathlib import Path
from serial.tools.list_ports import comports


# Setup logger add a rotating file handler every one day create a backup after 10 days we will delete the oldest log
logger = logging.getLogger(__name__)
fh = TimedRotatingFileHandler(
    filename="/media/usb/output.log",
    when="D",
    interval=1,
    backupCount=10,
    encoding="utf-8",
    delay=False,
)

formatter = logging.Formatter(
    fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
fh.setFormatter(formatter)
logger.addHandler(fh)
logger.setLevel(logging.DEBUG)


# Baud rate and get a list of the serial devices.
BAUD_RATE = 115200
PORT_LIST = comports()


# See if we have a firmware file on the Flash drive.
# Look for a file indicating if we are a Master or Slave
# Open the playlist file so we know what we're supposed to play
if Path("/media/usb/firmware.hex").exists():
    firmware_file = Path("/media/usb/firmware.hex")
else:
    firmware_file = False
mode = b"MST\r\n" if Path("/media/usb/MST").exists() else b"SLV\r\n"

with open("/media/usb/playlist.cfg") as file:
    playlist = file.readline().strip("\n\r")


# Open Serial device.
ser = serial.Serial()


def check_status():
    # Check the time remaining for the last item in the playlist. If its less than a second we need to sync up
    status = requests.get("http://localhost/api/fppd/status")
    if (
        status.json()["current_playlist"]["count"]
        == status.json()["current_playlist"]["index"]
    ):
        time_remaining = int(status.json()["seconds_remaining"])
        if time_remaining < 1:
            ser.write(b"SYNC\r\n")
            # print("Writing Sync")
            sleep(1)


def set_mode(mode):
    # Write to the serial device what mode we're in.
    # This informs the radio if it should listen or send messages
    ser.write(mode)
    while not (ser.in_waiting):
        pass
    current_mode = ser.read_until("\r\n").decode("utf-8").replace("\r\n", "")
    logger.info(current_mode)


def check_version_number():
    # Logic from before for handling updates...Needs to be removed
    ser.write(b"VERSION\r\n")
    while not (ser.in_waiting):
        pass
    version = (
        ser.read_until(
            "\r\n",
        )
        .decode("UTF-8")
        .replace("\r\n", "")
    )
    # If we have a firmware file on the usb drive use avrdude to update the radio
    if firmware_file:
        logger.info("Update needed")
        output = subprocess.run(
            [
                "avrdude",
                "-P",
                ser.port,
                "-c",
                "arduino",
                "-C",
                "/media/usb/avrdude.conf",
                "-p",
                "atmega328p",
                "-b",
                "115200",
                "-D",
                "-U",
                f"flash:w:{firmware_file.as_posix()}:i",
            ],
            capture_output=True,
            text=True,
        )
        # Check the output from subprocess for errors
        # Delete the file from the usb drive so we're not constantly updating the device.
        logger.info(output.stdout)
        logger.error(output.stderr)
        firmware_file.unlink()


for port in PORT_LIST:
    # Check for a serial port that isn't the standard Pi serial device.
    if port.manufacturer == "FTDI":
        ser.baudrate = BAUD_RATE
        ser.port = port.device
        ser.timeout = 0.1
        ser.open()
        # Wait for serial port to be ready before we let other functions use it!
        sleep(2)


# This calls the updater
check_version_number()
sleep(2)
# Sets the mode based on the file on the Flash Drive
set_mode(mode)

while True:
    try:
        # If we're the master constantly check the time left in the playlist
        if mode == b"MST\r\n":
            check_status()
        if ser.in_waiting:
            # Look at serial from the hardware and Parse it.
            command = ser.read_all().decode("utf-8").replace("\r\n", "")
            logger.info(command)
            if command == "SYNC" and mode == b"SLV\r\n":
                r = requests.get("http://localhost/api/playlists/stop")
                r = requests.get(f"http://localhost/api/playlist/{playlist}/start")

    except Exception as e:
        logger.error(e)
