# app.py
from flask import Flask, send_from_directory, jsonify, request
import os

app = Flask(__name__, static_folder='frontend')

# Serve frontend
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

# Placeholder API endpoints
@app.route('/api/stations')
def get_stations():
    return jsonify({'stations': []})

@app.route('/api/investigate/<station_id>')
def investigate(station_id):
    return jsonify({'upstream': []})

@app.route('/api/history/<station_id>')
def history(station_id):
    return jsonify({'history': []})

@app.route('/api/reports')
def reports():
    q = request.args.get('q', '')
    return jsonify({'results': []})

@app.route('/api/integrity/check', methods=['POST'])
def integrity_check():
    data = request.json or {}
    return jsonify({'verified': False})

if __name__ == '__main__':
    app.run(debug=True)

