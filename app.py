# FIX: If you see "ModuleNotFoundError", run the corresponding pip install command.
# pip install flask twilio

from flask import Flask, request, jsonify, Response, render_template_string
from twilio.rest import Client
import xml.et.ree.ElementTree as ET
import uuid
import os
import sys

# --- Configuration ---------------------------------------------------
# This section REQUIRES environment variables to be set for security.
try:
    TWILIO_ACCOUNT_SID = os.environ['TWILIO_ACCOUNT_SID']
    TWILIO_AUTH_TOKEN = os.environ['TWILIO_AUTH_TOKEN']
    TWILIO_PHONE_NUMBER = os.environ['TWILIO_PHONE_NUMBER']
except KeyError as e:
    print(f"FATAL ERROR: Environment variable {e} is not set.")
    print("Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER before running.")
    sys.exit(1) # Exit the script if secrets are missing.

# Define a directory to store the resulting XML files.
# Render provides a temporary disk at /data for this.
RESULTS_DIR = "/data/location_results"

# --- Initialization --------------------------------------------------
app = Flask(__name__)

# Initialize Twilio client
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
except Exception as e:
    print(f"Error initializing Twilio client: {e}. Please check if your credentials are correct.")
    twilio_client = None

# In-memory dictionary to track only the status of requests.
REQUEST_DB = {}

# --- Helper Functions ------------------------------------------------
def generate_xml_response(request_id, status, location=None, error_msg=None):
    """A helper function to generate the XML string."""
    root = ET.Element("LocationRequest")
    ET.SubElement(root, "RequestID").text = request_id
    ET.SubElement(root, "Status").text = status

    if status == "completed" and location:
        coords_el = ET.SubElement(root, "Coordinates")
        ET.SubElement(coords_el, "Latitude").text = str(location.get("lat"))
        ET.SubElement(coords_el, "Longitude").text = str(location.get("lon"))
    elif status == "denied" and error_msg:
        ET.SubElement(root, "Message").text = error_msg
    elif status == "pending":
         ET.SubElement(root, "Message").text = "Location has not been provided by the user yet."

    return ET.tostring(root, encoding='unicode')

# --- API Endpoints -----------------------------------------------------
@app.route('/')
def index():
    return "Location Request Service is running. API is live."

@app.route('/request-location', methods=['POST'])
def request_location():
    """Generates a link and sends it to the target phone number via Twilio."""
    if not twilio_client:
        return jsonify({"error": "Twilio client not initialized. Check credentials."}), 500

    data = request.json
    phone_number = data.get('phone_number')
    if not phone_number:
        return jsonify({"error": "'phone_number' is required"}), 400

    request_id = str(uuid.uuid4())
    REQUEST_DB[request_id] = {"status": "pending"}

    base_url = request.url_root.rstrip('/')
    consent_url = f"{base_url}/consent/{request_id}"

    try:
        message_body = (
            "Please share your location by clicking the link. "
            "An internet connection (Wi-Fi or mobile data) is required.\n\n"
            f"Click here: {consent_url}"
        )
        message = twilio_client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number
        )
        print(f"SMS sent to {phone_number}, SID: {message.sid}")
        return jsonify({
            "status": "pending",
            "message": f"Location request SMS sent to {phone_number}.",
            "request_id": request_id
        }), 202

    except Exception as e:
        print(f"Error sending Twilio SMS: {e}")
        if request_id in REQUEST_DB:
            del REQUEST_DB[request_id]
        return jsonify({"error": f"Failed to send SMS: {str(e)}"}), 500

@app.route('/consent/<request_id>', methods=['GET'])
def get_consent(request_id):
    if request_id not in REQUEST_DB:
        return "<h1>Invalid or expired request.</h1>", 404
    if REQUEST_DB[request_id]["status"] != "pending":
         return "<h1>This location request has already been completed.</h1>", 200
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Location Consent</title>
        <style>
            body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; background-color: #f0f0f0; text-align: center; margin: 20px; }
            .container { background: white; padding: 2.5rem; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.1); max-width: 450px; }
            h1 { color: #333; }
            p { color: #555; font-size: 1.1rem; line-height: 1.6; }
            button { background-color: #007bff; color: white; border: none; padding: 15px 30px; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: background-color 0.2s; }
            button:disabled { background-color: #ccc; }
        </style>
    </head>
    <body>
        <div class="container" id="container">
            <h1>Share Your Location</h1>
            <p>A request has been made for your location. Click the button to share.</p>
            <button id="share-btn">Share Location</button>
            <p id="status"></p>
        </div>
        <script>
            const requestId = '{{ request_id }}';
            const shareBtn = document.getElementById('share-btn');
            const statusEl = document.getElementById('status');
            const containerEl = document.getElementById('container');
            shareBtn.addEventListener('click', () => {
                shareBtn.disabled = true;
                statusEl.textContent = 'Requesting location...';
                navigator.geolocation.getCurrentPosition(
                    (p) => { 
                        statusEl.textContent = 'Location captured! Sending...';
                        sendLocation({ lat: p.coords.latitude, lon: p.coords.longitude }, null);
                    },
                    (e) => {
                        const msgs = { 1: 'Permission denied. You must click \\"Allow\\".', 2: 'Location unavailable.', 3: 'Request timed out.' };
                        const errorMsg = msgs[e.code] || 'An unknown error occurred.';
                        statusEl.textContent = 'Error: ' + errorMsg;
                        sendLocation(null, errorMsg);
                    }
                );
            });
            async function sendLocation(location, error) {
                try {
                    await fetch('/submit-location', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ token: requestId, location: location, error: error })
                    });
                    containerEl.innerHTML = location ? '<h1>Thank You!</h1><p>Your location has been securely shared.</p>' : '<h1>Request Denied</h1><p>Your location was not shared.</p>';
                } catch (err) {
                    statusEl.textContent = 'Failed to submit location. Please try again.';
                    shareBtn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_content, request_id=request_id)

@app.route('/submit-location', methods=['POST'])
def submit_location():
    data = request.json
    request_id = data.get('token')
    location = data.get('location')
    error = data.get('error')

    if not request_id or request_id not in REQUEST_DB:
        return jsonify({"error": "Invalid token"}), 400
    if REQUEST_DB[request_id]["status"] != "pending":
        return jsonify({"message": "Request already processed"}), 200

    if location:
        status = "completed"
        xml_data = generate_xml_response(request_id, status, location=location)
        REQUEST_DB[request_id]['status'] = status
        print(f"Location received for {request_id}: {location}")
    else:
        status = "denied"
        xml_data = generate_xml_response(request_id, status, error_msg=error)
        REQUEST_DB[request_id]['status'] = status
        print(f"Location denied for {request_id}: {error}")
    
    filepath = os.path.join(RESULTS_DIR, f"{request_id}.xml")
    try:
        # Create directory if it doesn't exist (important for Render)
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(xml_data)
        print(f"Successfully saved result to {filepath}")
    except Exception as e:
        print(f"FATAL ERROR: Could not write to file {filepath}. Error: {e}")

    return jsonify({"status": "received"}), 200

@app.route('/get-location/<request_id>', methods=['GET'])
def get_location_xml(request_id):
    filepath = os.path.join(RESULTS_DIR, f"{request_id}.xml")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return Response(f.read(), mimetype='application/xml')
        except Exception as e:
            return f"Error reading result file: {e}", 500
    elif request_id in REQUEST_DB and REQUEST_DB[request_id]['status'] == 'pending':
        return Response(generate_xml_response(request_id, "pending"), mimetype='application/xml')
    else:
        return Response(generate_xml_response(request_id, "error", error_msg="Request ID not found."), mimetype='application/xml'), 404

# No app.run() block needed for production servers like Gunicorn
