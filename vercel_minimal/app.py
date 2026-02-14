from flask import Flask, render_template_string, jsonify, request, Response
import os
from datetime import datetime
import base64
import threading
import time

from functools import wraps

app = Flask(__name__)

SEND_TOKEN = os.environ.get('SEND_TOKEN', 'khk-send-2026')
VIEW_TOKEN = os.environ.get('VIEW_TOKEN', 'khk-view-2026')

# Multi-channel image storage
channel_frames = {}  # {channel_number: base64_data}
last_update = 0
current_channels = []
data_lock = threading.Lock()

ALLOWED_ORIGINS = ['kirii-portfolio-1.vercel.app', 'kirii-portfolio-1-kirii.vercel.app']

def require_view_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Already has session cookie -> allow
        if request.cookies.get('vpass') == '1':
            return f(*args, **kwargs)
        # Came from portfolio (Referer check) -> set cookie and allow
        ref = request.referrer or ''
        for origin in ALLOWED_ORIGINS:
            if origin in ref:
                resp = f(*args, **kwargs)
                if isinstance(resp, Response):
                    resp.set_cookie('vpass', '1', max_age=86400, samesite='None', secure=True)
                else:
                    resp = Response(resp)
                    resp.set_cookie('vpass', '1', max_age=86400, samesite='None', secure=True)
                return resp
        # Token in URL -> set cookie and allow
        if request.args.get('token') == VIEW_TOKEN:
            resp = f(*args, **kwargs)
            if isinstance(resp, Response):
                resp.set_cookie('vpass', '1', max_age=86400, samesite='None', secure=True)
            return resp
        return Response('Unauthorized', status=401)
    return decorated

@app.route('/')
@require_view_auth
def index():
    return render_template_string('''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KHK AI-DETECT MONITOR</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#111;color:#fff;font-family:Arial,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:8px}
.top{display:flex;justify-content:space-between;align-items:center;padding:4px 0}
.title{font-size:13px;color:#888}
.mode-btns button{background:#333;color:#ccc;border:1px solid #555;padding:4px 14px;cursor:pointer;font-size:12px;border-radius:3px;margin-left:4px}
.mode-btns button.active{background:#1a6;color:#fff;border-color:#1a6}
.grid{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(2,1fr);gap:3px;height:calc(100vh - 50px)}
.cell{background:#000;position:relative;overflow:hidden;border-radius:3px}
.cell img{width:100%;height:100%;object-fit:cover;display:block}
.cell .ch{position:absolute;bottom:4px;left:6px;font-size:11px;color:#aaa;text-shadow:0 0 3px #000}
.cell .nosig{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#444;font-size:14px}
.status{position:fixed;bottom:4px;right:8px;font-size:11px;color:#555}
</style>
</head>
<body>
<div class="wrap">
    <div class="top">
        <span class="title">KHK AI-DETECT MONITOR</span>
        <div class="mode-btns">
            <button id="btnA" class="active" onclick="setMode('A')">Group A</button>
            <button id="btnB" onclick="setMode('B')">Group B</button>
        </div>
    </div>
    <div class="grid" id="grid"></div>
</div>
<div class="status" id="st">Loading...</div>
<script>
var mode='A';
var groupA=[2,3,4,7,11,14];
var groupB=[1,5,10,13,14,15];
var grid=document.getElementById('grid');
var st=document.getElementById('st');

function setMode(m){
    mode=m;
    document.getElementById('btnA').className=m==='A'?'active':'';
    document.getElementById('btnB').className=m==='B'?'active':'';
}

function buildGrid(channels){
    grid.innerHTML='';
    for(var i=0;i<6;i++){
        var ch=channels[i];
        var cell=document.createElement('div');
        cell.className='cell';
        cell.id='cell'+ch;
        cell.innerHTML='<div class="nosig" id="ns'+ch+'">CH'+ch+'</div><img id="img'+ch+'" style="display:none"><div class="ch">CH'+ch+'</div>';
        grid.appendChild(cell);
    }
}

function refresh(){
    var t=new Date();
    fetch('/api/frames?t='+t.getTime())
    .then(function(r){return r.json();})
    .then(function(data){
        if(!data.frames){st.textContent='No data - '+t.toLocaleTimeString();return;}
        var channels=mode==='A'?groupA:groupB;
        buildGrid(channels);
        var count=0;
        for(var i=0;i<channels.length;i++){
            var ch=String(channels[i]);
            var f=data.frames[ch];
            if(f){
                var img=document.getElementById('img'+ch);
                var ns=document.getElementById('ns'+ch);
                if(img){img.src='data:image/jpeg;base64,'+f;img.style.display='block';}
                if(ns)ns.style.display='none';
                count++;
            }
        }
        st.textContent='Live '+count+'/6 - '+t.toLocaleTimeString();
    })
    .catch(function(){
        st.textContent='Connection error - '+t.toLocaleTimeString();
    });
}

buildGrid(groupA);
setInterval(refresh,2000);
refresh();
</script>
</body>
</html>''')

@app.route('/receive_multi', methods=['POST'])
def receive_multi():
    global channel_frames, last_update, current_channels
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'no data'}), 400
        t = data.get('token')
        if t != SEND_TOKEN:
            return jsonify({'error': 'unauthorized'}), 401
        frames = data.get('frames', {})
        channels = data.get('channels', [])
        with data_lock:
            for ch, frame in frames.items():
                channel_frames[str(ch)] = frame
            current_channels = channels
            last_update = data.get('timestamp', time.time())
        return jsonify({'status': 'ok', 'received': len(frames)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/receive_image', methods=['POST'])
def receive_image():
    """Single image receive - backward compatibility"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'no data'}), 400
        t = data.get('token')
        if t != SEND_TOKEN:
            return jsonify({'error': 'unauthorized'}), 401
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/frames')
@require_view_auth
def api_frames():
    with data_lock:
        return jsonify({
            'frames': dict(channel_frames),
            'channels': current_channels,
            'last_update': last_update
        })

@app.route('/vercel/frame')
@require_view_auth
def get_frame():
    with data_lock:
        if not channel_frames:
            return Response('no image', status=404)
        first_key = next(iter(channel_frames))
        try:
            image_data = base64.b64decode(channel_frames[first_key])
            return Response(image_data, content_type='image/jpeg',
                           headers={'Cache-Control': 'no-cache'})
        except:
            return Response('decode error', status=500)

@app.route('/status')
def get_status():
    return jsonify({
        'has_frames': len(channel_frames) > 0,
        'channels': list(channel_frames.keys()),
        'last_update': last_update,
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
