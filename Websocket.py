import serial
import serial.tools.list_ports
import csv
import time
import json
import threading
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class ArduinoDataReader:
    def __init__(self, port='/dev/cu.usbserial-110', baud_rate=115200):
        self.port = port
        self.baud_rate = baud_rate
        self.serial_com = None
        self.running = False
        self.csv_file = None
        self.csv_writer = None
        self.data_count = 0
        self.max_data_points = 150

    def setup_serial(self):
        """Initialize serial connection"""
        try:
            # List available ports
            ports = serial.tools.list_ports.comports()
            logger.info("Available ports:")
            for port in ports:
                logger.info(f"  {port.device} - {port.name}")

            # Open serial connection
            self.serial_com = serial.Serial(self.port, self.baud_rate)

            # Toggle DTR to reset Arduino
            self.serial_com.dtr = False
            time.sleep(1)
            self.serial_com.reset_input_buffer()
            self.serial_com.dtr = True

            logger.info(f"Serial connection established on {self.port}")
            return True

        except Exception as e:
            logger.error(f"Failed to setup serial connection: {e}")
            return False

    def setup_csv(self, filename="data.csv"):
        """Initialize CSV file for data logging"""
        try:
            self.csv_file = open(filename, "w", newline='')
            self.csv_file.truncate()
            self.csv_writer = csv.writer(self.csv_file)

            # Write header
            header = ['timestamp', 'data_point', 'far_left', 'top_left', 'top_right', 'far_right']
            self.csv_writer.writerow(header)

            logger.info(f"CSV file '{filename}' initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to setup CSV file: {e}")
            return False

    def parse_arduino_data(self, raw_data):
        """Parse the Arduino data string"""
        try:
            data = raw_data.split(",")

            # Extract the four data points (adjust based on your Arduino output format)
            parsed_data = {
                'timestamp': time.time(),
                'raw': raw_data,
                'far_left': float(data[0]) if len(data) > 0 and data[0].strip() else 0,
                'top_left': float(data[1]) if len(data) > 1 and data[1].strip() else 0,
                'top_right': float(data[2]) if len(data) > 2 and data[2].strip() else 0,
                'far_right': float(data[3]) if len(data) > 3 and data[3].strip() else 0,
                'data_count': self.data_count
            }

            return parsed_data

        except Exception as e:
            logger.error(f"Failed to parse data '{raw_data}': {e}")
            return None

    def read_data_loop(self):
        """Main data reading loop"""
        logger.info("Starting data reading loop...")

        while self.running:
            try:
                if self.serial_com and self.serial_com.is_open:
                    # Clear input buffer and read line
                    self.serial_com.reset_input_buffer()
                    s_bytes = self.serial_com.readline()
                    decoded_bytes = s_bytes.decode("utf-8").strip('\r\n')

                    if decoded_bytes:
                        # Parse the data
                        parsed_data = self.parse_arduino_data(decoded_bytes)

                        if parsed_data:
                            # Log to CSV
                            if self.csv_writer:
                                row = [
                                    parsed_data['timestamp'],
                                    self.data_count,
                                    parsed_data['far_left'],
                                    parsed_data['top_left'],
                                    parsed_data['top_right'],
                                    parsed_data['far_right']
                                ]
                                self.csv_writer.writerow(row)
                                self.csv_file.flush()

                            # Emit to WebSocket clients
                            socketio.emit('arduino_data', parsed_data)

                            # Print to console
                            logger.info(f"Data #{self.data_count}: {parsed_data}")

                            self.data_count += 1

                            # Stop if max data points reached
                            if self.data_count >= self.max_data_points:
                                logger.info("Max data points reached, stopping...")
                                self.running = False

                time.sleep(0.1)  # Small delay to prevent overwhelming the system

            except Exception as e:
                logger.error(f"Error in data reading loop: {e}")
                time.sleep(1)  # Wait before retrying

    def start(self):
        """Start the data reader"""
        if self.setup_serial() and self.setup_csv():
            self.running = True
            # Run data reading in separate thread
            data_thread = threading.Thread(target=self.read_data_loop)
            data_thread.daemon = True
            data_thread.start()
            return True
        return False

    def stop(self):
        """Stop the data reader"""
        self.running = False
        if self.serial_com:
            self.serial_com.close()
        if self.csv_file:
            self.csv_file.close()
        logger.info("Data reader stopped")

# Global data reader instance
data_reader = ArduinoDataReader()

@app.route('/')
def index():
    """Serve a simple test page"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Arduino Data Stream</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    </head>
    <body>
        <h1>Arduino Data Stream</h1>
        <div id="status">Connecting...</div>
        <div id="data-display"></div>

        <script>
            const socket = io();
            const statusDiv = document.getElementById('status');
            const dataDiv = document.getElementById('data-display');

            socket.on('connect', function() {
                statusDiv.innerHTML = 'Connected to server';
                console.log('Connected to server');
            });

            socket.on('disconnect', function() {
                statusDiv.innerHTML = 'Disconnected from server';
                console.log('Disconnected from server');
            });

            socket.on('arduino_data', function(data) {
                console.log('Received data:', data);
                dataDiv.innerHTML = `
                    <p><strong>Data Point #${data.data_count}</strong></p>
                    <p>Timestamp: ${new Date(data.timestamp * 1000).toLocaleTimeString()}</p>
                    <p>Far Left: ${data.far_left}</p>
                    <p>Top Left: ${data.top_left}</p>
                    <p>Top Right: ${data.top_right}</p>
                    <p>Far Right: ${data.far_right}</p>
                    <p>Raw: ${data.raw}</p>
                    <hr>
                `;
            });

            socket.on('server_status', function(data) {
                statusDiv.innerHTML = `Server Status: ${data.message}`;
            });
        </script>
    </body>
    </html>
    '''

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('server_status', {'message': 'Connected to Arduino data stream'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')

@socketio.on('start_data_stream')
def handle_start_stream():
    """Handle request to start data stream"""
    if not data_reader.running:
        if data_reader.start():
            emit('server_status', {'message': 'Data stream started'})
        else:
            emit('server_status', {'message': 'Failed to start data stream'})
    else:
        emit('server_status', {'message': 'Data stream already running'})

@socketio.on('stop_data_stream')
def handle_stop_stream():
    """Handle request to stop data stream"""
    data_reader.stop()
    emit('server_status', {'message': 'Data stream stopped'})

if __name__ == '__main__':
    try:
        # Start the data reader
        logger.info("Starting Arduino WebSocket server...")
        data_reader.start()

        # Start the Flask-SocketIO server
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        data_reader.stop()
    except Exception as e:
        logger.error(f"Server error: {e}")
        data_reader.stop()
