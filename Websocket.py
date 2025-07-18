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
        self.max_data_points = 50  # Keep only last 100 points in memory
        self.data_buffer = []  # Buffer to store recent data points

    def setup_serial(self):
        """Initialize serial connection"""
        try:
            # List available ports
            ports = serial.tools.list_ports.comports()
            logger.info("Available ports:")
            for port in ports:
                logger.info(f"  {port.device} - {port.name}")

            # Try to find Arduino port automatically
            arduino_ports = []
            for port in ports:
                if 'arduino' in port.name.lower() or 'usb' in port.name.lower():
                    arduino_ports.append(port.device)

            if arduino_ports:
                self.port = arduino_ports[0]
                logger.info(f"Auto-detected Arduino port: {self.port}")
            else:
                logger.warning(f"No Arduino port detected, using default: {self.port}")

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

            # Write header for 8 ports
            header = ['timestamp', 'data_point', 'left_1', 'left_2', 'left_3', 'left_4', 'right_1', 'right_2', 'right_3', 'right_4']
            self.csv_writer.writerow(header)

            logger.info(f"CSV file '{filename}' initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to setup CSV file: {e}")
            return False

    def parse_arduino_data(self, raw_data):
        """Parse the Arduino data string for 8 ports"""
        try:
            data = raw_data.split(",")
            # Pad with zeros if not enough data
            while len(data) < 8:
                data.append('0')

            # Convert to float, defaulting to 0 if conversion fails
            def safe_float(value):
                try:
                    return float(value.strip()) if value.strip() else 0
                except:
                    return 0

            parsed_data = {
                'timestamp': time.time(),
                'raw': raw_data,
                'left_1': safe_float(data[0]),
                'left_2': safe_float(data[1]),
                'left_3': safe_float(data[2]),
                'left_4': safe_float(data[3]),
                'right_1': safe_float(data[4]),
                'right_2': safe_float(data[5]),
                'right_3': safe_float(data[6]),
                'right_4': safe_float(data[7]),
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
                                    parsed_data['left_1'],
                                    parsed_data['left_2'],
                                    parsed_data['left_3'],
                                    parsed_data['left_4'],
                                    parsed_data['right_1'],
                                    parsed_data['right_2'],
                                    parsed_data['right_3'],
                                    parsed_data['right_4']
                                ]
                                self.csv_writer.writerow(row)
                                self.csv_file.flush()

                            # Add to data buffer (keep only recent points)
                            self.data_buffer.append(parsed_data)
                            if len(self.data_buffer) > self.max_data_points:
                                self.data_buffer.pop(0)  # Remove oldest data point

                            # Emit to WebSocket clients
                            socketio.emit('arduino_data', parsed_data)

                            # Print to console
                            logger.info(f"Data #{self.data_count}: {parsed_data}")

                            self.data_count += 1

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
        <script src="https://cdnjs.cloudflare.com/ajax/libs/p5.js/1.7.0/p5.min.js"></script>
    </head>
    <body>
        <h1>Arduino Data Stream</h1>
        <div id="status">Connecting...</div>
        <div id="data-display"></div>
        <div id="overlay-graph-container" style="margin-bottom: 40px;"></div>
        <script>
            const socket = io();
            const statusDiv = document.getElementById('status');
            const dataDiv = document.getElementById('data-display');

            // Data for plotting
            window.dataPoints = [];
            let isPaused = false;
            let maxDataPoints = 50;

            // Port colors and labels
            const colors = {
                left_1: [255, 107, 107], // Red
                left_2: [255, 159, 67], // Orange
                left_3: [255, 221, 89], // Yellow
                left_4: [38, 222, 129], // Green
                right_1: [78, 205, 196], // Teal
                right_2: [69, 183, 209], // Blue
                right_3: [75, 123, 236], // Indigo
                right_4: [165, 94, 234], // Purple
            };
            const portLabels = [
                "Left 1",
                "Left 2",
                "Left 3",
                "Left 4",
                "Right 1",
                "Right 2",
                "Right 3",
                "Right 4",
            ];
            const portKeys = [
                "left_1",
                "left_2",
                "left_3",
                "left_4",
                "right_1",
                "right_2",
                "right_3",
                "right_4",
            ];

            socket.on('connect', function() {
                statusDiv.innerHTML = 'Connected to server';
                console.log('Connected to server');
            });

            socket.on('disconnect', function() {
                statusDiv.innerHTML = 'Disconnected from server';
                console.log('Disconnected from server');
            });

            socket.on('arduino_data', function(data) {
                if (!isPaused) {
                    window.dataPoints.push(data);
                    if (window.dataPoints.length > maxDataPoints) {
                        window.dataPoints.shift();
                    }
                }
                // Display latest data
                dataDiv.innerHTML = `
                    <p><strong>Data Point #${data.data_count}</strong></p>
                    <p>Timestamp: ${new Date(data.timestamp * 1000).toLocaleTimeString()}</p>
                    <p>Left 1: ${data.left_1}</p>
                    <p>Left 2: ${data.left_2}</p>
                    <p>Left 3: ${data.left_3}</p>
                    <p>Left 4: ${data.left_4}</p>
                    <p>Right 1: ${data.right_1}</p>
                    <p>Right 2: ${data.right_2}</p>
                    <p>Right 3: ${data.right_3}</p>
                    <p>Right 4: ${data.right_4}</p>
                    <p>Raw: ${data.raw}</p>
                    <hr>
                `;
            });

            socket.on('server_status', function(data) {
                statusDiv.innerHTML = `Server Status: ${data.message}`;
            });
        </script>
        <script>
        // Overlay plot for all 8 ports
        new p5(function (p) {
            let overlayWidth = 1000;
            let overlayHeight = 300;
            let overlayGraphX = 60;
            let overlayGraphY = 40;
            let overlayGraphWidth = overlayWidth - 80;
            let overlayGraphHeight = overlayHeight - 80;

            p.setup = function () {
                let c = p.createCanvas(overlayWidth, overlayHeight);
                c.parent('overlay-graph-container');
            };

            p.draw = function () {
                p.background(26, 26, 26);

                // Draw background
                p.fill(40, 40, 40);
                p.noStroke();
                p.rect(overlayGraphX, overlayGraphY, overlayGraphWidth, overlayGraphHeight);

                // Draw grid
                p.stroke(60, 60, 60);
                p.strokeWeight(1);
                for (let i = 0; i <= 10; i++) {
                    let y = overlayGraphY + (i * overlayGraphHeight / 10);
                    p.line(overlayGraphX, y, overlayGraphX + overlayGraphWidth, y);
                }
                for (let i = 0; i <= 10; i++) {
                    let x = overlayGraphX + (i * overlayGraphWidth / 10);
                    p.line(x, overlayGraphY, x, overlayGraphY + overlayGraphHeight);
                }

                // Draw axes
                p.stroke(200);
                p.strokeWeight(2);
                p.line(overlayGraphX, overlayGraphY, overlayGraphX, overlayGraphY + overlayGraphHeight);
                p.line(overlayGraphX, overlayGraphY + overlayGraphHeight, overlayGraphX + overlayGraphWidth, overlayGraphY + overlayGraphHeight);

                // Y-axis labels
                p.fill(200);
                p.noStroke();
                p.textAlign(p.RIGHT, p.CENTER);
                p.textSize(12);
                let minY = 0, maxY = 5000;
                if (window.dataPoints && window.dataPoints.length > 1) {
                    minY = Infinity; maxY = -Infinity;
                    window.dataPoints.forEach(point => {
                        for (let key of portKeys) {
                            minY = Math.min(minY, point[key]);
                            maxY = Math.max(maxY, point[key]);
                        }
                    });
                    let padding = (maxY - minY) * 0.1;
                    minY -= padding;
                    maxY += padding;
                    if (maxY - minY < 10) {
                        let center = (maxY + minY) / 2;
                        minY = center - 5;
                        maxY = center + 5;
                    }
                }
                for (let i = 0; i <= 5; i++) {
                    let y = overlayGraphY + (i * overlayGraphHeight / 5);
                    let value = window.dataPoints && window.dataPoints.length > 1
                        ? p.map(i, 0, 5, maxY, minY)
                        : 0;
                    p.text(value.toFixed(0), overlayGraphX - 10, y);
                }
                // X-axis label
                p.textAlign(p.CENTER, p.TOP);
                p.text('Time →', overlayGraphX + overlayGraphWidth / 2, overlayGraphY + overlayGraphHeight + 20);

                // Legend
                let legendX = overlayGraphX + 20;
                let legendY = overlayGraphY - 30;
                for (let i = 0; i < portKeys.length; i++) {
                    let key = portKeys[i];
                    let color = colors[key];
                    p.fill(color[0], color[1], color[2]);
                    p.noStroke();
                    p.rect(legendX + i * 110, legendY, 20, 6, 2);
                    p.fill(220);
                    p.textAlign(p.LEFT, p.CENTER);
                    p.textSize(12);
                    p.text(portLabels[i], legendX + i * 110 + 25, legendY + 3);
                }

                // Draw all 8 signals if data exists
                if (window.dataPoints && window.dataPoints.length > 1) {
                    let minY = Infinity, maxY = -Infinity;
                    window.dataPoints.forEach(point => {
                        for (let key of portKeys) {
                            minY = Math.min(minY, point[key]);
                            maxY = Math.max(maxY, point[key]);
                        }
                    });
                    let padding = (maxY - minY) * 0.1;
                    minY -= padding;
                    maxY += padding;
                    if (maxY - minY < 10) {
                        let center = (maxY + minY) / 2;
                        minY = center - 5;
                        maxY = center + 5;
                    }

                    for (let i = 0; i < portKeys.length; i++) {
                        let key = portKeys[i];
                        let color = colors[key];
                        p.stroke(color[0], color[1], color[2]);
                        p.strokeWeight(2);
                        p.noFill();
                        p.beginShape();
                        for (let j = 0; j < window.dataPoints.length; j++) {
                            let x = p.map(j, 0, maxDataPoints - 1, overlayGraphX, overlayGraphX + overlayGraphWidth);
                            let y = p.map(window.dataPoints[j][key], minY, maxY, overlayGraphY + overlayGraphHeight, overlayGraphY);
                            p.vertex(x, y);
                        }
                        p.endShape();
                    }
                } else {
                    // No data: show placeholder message
                    p.fill(180);
                    p.textAlign(p.CENTER, p.CENTER);
                    p.textSize(20);
                    p.text('No data yet', overlayGraphX + overlayGraphWidth / 2, overlayGraphY + overlayGraphHeight / 2);
                }
            };
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
