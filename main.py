import serial
import serial.tools.list_ports
import csv
import time

# Identify the correct port
ports = serial.tools.list_ports.comports()
for port in ports: print(port.device, port.name)

# Create CSV file
f = open("data.csv","w",newline='')
f.truncate()

# Open the serial com
serialCom = serial.Serial('/dev/cu.usbserial-110',115200)

# Toggle DTR to reset the Arduino
serialCom.dtr = False
time.sleep(1)
serialCom.reset_input_buffer()
serialCom.dtr = True

# How many data points to record (if stopping)
kmax = 150
# Loop through and collect data as it is available
dataVariable = 0

running = True

while running: 
    serialCom.reset_input_buffer()  # Clear the input buffer
    s_bytes = serialCom.readline()
    decoded_bytes = s_bytes.decode("utf-8").strip('\r\n')
    #print(f"decoded bytes: {decoded_bytes}")
    farLeftData = []
    topLeftData = []
    topRightData = []
    farRightData = []
    
    data = decoded_bytes.split(",")
    print(f"data: {data}")
    