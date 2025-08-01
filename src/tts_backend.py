import hashlib
import io
import logging
import tempfile
import urllib.parse

import soundfile as sf
from flask import Flask, request, Response, jsonify, stream_with_context, send_file
import sys
import os

from future.backports.test.ssl_servers import threading

# 设置日志基本配置
logging.basicConfig(
    filename='mylog.log',                # 日志文件名
    level=logging.INFO,                  # 设置日志级别
    format='%(asctime)s - %(levelname)s - %(message)s'  # 日志格式
)
# 将当前文件所在的目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from load_infer_info import load_character, character_name, get_wav_from_text_api, models_path, update_character_info

app = Flask(__name__)

# 存储临时文件的字典
temp_files = {}
# 配置文件路径
CONFIG_FILE = "zhonghangMd5.json"

# 从JSON配置文件加载数据
def load_temp_files():
    config_md5_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), CONFIG_FILE)
    if os.path.exists(config_md5_path):
        with open(config_md5_path, 'r', encoding='utf-8') as m:
            return json.load(m)
    return {}
# 用于防止重复请求
def generate_file_hash(*args):
    """生成基于输入参数的哈希值，用于唯一标识一个请求"""
    hash_object = hashlib.md5()
    for arg in args:
        hash_object.update(str(arg).encode())
    return hash_object.hexdigest()

@app.route('/character_list', methods=['GET'])
def character_list():
    return jsonify(update_character_info()['characters_and_emotions'])


@app.route('/tts', methods=['GET', 'POST'])
def tts():
    global character_name
    global models_path

    # 尝试从JSON中获取数据，如果不是JSON，则从查询参数中获取
    if request.is_json:
        data = request.json
    else:
        data = request.args
    print(f'data is {data}')

    text = urllib.parse.unquote(data.get('text', ''))
    #将text转json并获取其中的text
    #text is  {"tag":"javaApi","text":"你好呀","type":"wenda_Hello"}
    if isinstance(text, str) and text.startswith('{') and text.endswith('}'):
        try:
            text_data = json.loads(text)
            text = text_data.get('text', '')
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON format in 'text' parameter."}), 400
    print(f'text is ',text)
    cha_name = data.get('cha_name', None)
    print(f'cha_name is {cha_name}')
    try:
        expected_path = os.path.join(models_path, cha_name) if cha_name else None
    except:
        # 如果cha_name无法构造路径，设置expected_path为None
        expected_path = None
        print(f'Error constructing expected_path for cha_name: {cha_name}')
    print(f'expected_path is {expected_path}, cha_name is {cha_name}, character_name is {character_name}')
    # 检查cha_name和路径
    if cha_name and cha_name != character_name and expected_path and os.path.exists(expected_path):
        character_name = cha_name
        print(f"Loading character {character_name}")
        load_character(character_name)  
    elif expected_path and not os.path.exists(expected_path):
        return jsonify({"error": f"Directory {expected_path} does not exist. Using the current character."}), 400

    text_language = data.get('text_language', '多语种混合')
    try:
        top_k = int(data.get('top_k', 6))
        top_p = float(data.get('top_p', 0.8))
        temperature = float(data.get('temperature', 0.8))
        stream = data.get('stream', 'False').lower() == 'true'
        save_temp = data.get('save_temp', 'False').lower() == 'true'
    except ValueError:
        return jsonify({"error": "Invalid parameters. They must be numbers."}), 400
    character_emotion = data.get('character_emotion', 'default')

    print(f'text: {text}, text_language: {text_language}, top_k: {top_k}, top_p: {top_p}, temperature: {temperature}, character_emotion: {character_emotion}, character_name: {character_name}')
    request_hash = generate_file_hash(text, text_language, top_k, top_p, temperature, character_emotion, character_name)
    print(f'Processing request with hash: {request_hash}')
    logging.info(f'Processing request with hash: {request_hash}')
    if stream == False:
        if save_temp:

            if request_hash in temp_files:
                print(f'temp_files: {temp_files[request_hash]}')
                return send_file(temp_files[request_hash], mimetype='audio/wav')
            else:
                gen = get_wav_from_text_api(text, text_language, top_k=top_k, top_p=top_p, temperature=temperature, character_emotion=character_emotion, stream=stream)
                sampling_rate, audio_data = next(gen)
                temp_dir = tempfile.gettempdir()
                print(f'temp_dir: {temp_dir}')
                temp_file_path = os.path.join(temp_dir, f"{request_hash}.wav")
                os.makedirs(os.path.dirname(temp_file_path), exist_ok=True)
                # 写入文件
                with open(temp_file_path, 'wb') as temp_file:
                    sf.write(temp_file, audio_data, sampling_rate, format='wav')
                temp_files[request_hash] = temp_file_path
                print(f'temp_files: {temp_files[request_hash]}')
                return send_file(temp_file_path, mimetype='audio/wav')
        else:
            gen = get_wav_from_text_api(text, text_language, top_k=top_k, top_p=top_p, temperature=temperature, character_emotion=character_emotion, stream=stream)
            sampling_rate, audio_data = next(gen)
            wav = io.BytesIO()
            sf.write(wav, audio_data, sampling_rate, format="wav")
            wav.seek(0)
            return Response(wav, mimetype='audio/wav')
    else:
        gen = get_wav_from_text_api(text, text_language, top_k=top_k, top_p=top_p, temperature=temperature, character_emotion=character_emotion, stream=stream)
        return Response(stream_with_context(gen),  mimetype='audio/wav')


@app.route('/tts/unity', methods=['GET', 'POST'])
def tts_unity():
    global character_name
    global models_path

    # 尝试从JSON中获取数据，如果不是JSON，则从查询参数中获取
    if request.is_json:
        data = request.json
    else:
        data = request.args
    data = request.get_json(force=True)  # ✅ 强制用 UTF-8 解析 JSON
    text = data.get('text', '')
    cha_name = data.get('id', None)
    expected_path = os.path.join(models_path, cha_name) if cha_name else None
    print(f'cha_name: {cha_name}, text: {text}')
    # 检查cha_name和路径
    if cha_name and cha_name != character_name and expected_path and os.path.exists(expected_path):
        character_name = cha_name
        print(f"Loading character {character_name}")
        load_character(character_name)
    elif expected_path and not os.path.exists(expected_path):
        return jsonify({"error": f"Directory {expected_path} does not exist. Using the current character."}), 400

    text_language = data.get('text_language', '多语种混合')
    try:
        top_k = int(data.get('top_k', 6))
        top_p = float(data.get('top_p', 0.8))
        temperature = float(data.get('temperature', 0.8))
        stream = data.get('stream', 'False').lower() == 'true'
        save_temp = data.get('save_temp', 'False').lower() == 'true'
    except ValueError:
        return jsonify({"error": "Invalid parameters. They must be numbers."}), 400
    character_emotion = data.get('character_emotion', 'default')
    print(f'text: {text}, text_language: {text_language}, top_k: {top_k}, top_p: {top_p}, temperature: {temperature}, character_emotion: {character_emotion}, character_name: {character_name}')
    request_hash = generate_file_hash(text, text_language, top_k, top_p, temperature, character_emotion, character_name)
    print(f'Processing request with hash: {request_hash}')
    gen = get_wav_from_text_api(text, text_language, top_k=top_k, top_p=top_p, temperature=temperature, character_emotion=character_emotion, stream=stream)
    sampling_rate, audio_data = next(gen)
    # 保存为 wav
    wav = io.BytesIO()
    sf.write(wav, audio_data, sampling_rate, format="wav")
    wav.seek(0)

    # 转为 mp3
    mp3_bytes = convert_wav_bytes_to_mp3_bytes(wav.read())
    return Response(mp3_bytes, mimetype='audio/mpeg')

from pydub import AudioSegment

def convert_wav_bytes_to_mp3_bytes(wav_bytes: bytes) -> bytes:
    audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    mp3_io = io.BytesIO()
    audio.export(mp3_io, format="mp3", bitrate="128k")
    return mp3_io.getvalue()

import json
tts_port = 5000

# 取得模型文件夹路径
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        _config = json.load(f)
        tts_port = _config.get("tts_port", 5000)

import requests
import time

def call_tts_from_config():
    config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "zhonghang.json")
    if not os.path.exists(config_file):
        print("[ERROR] zhonghang.json 不存在，跳过自动调用")
        return

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        print(f"[ERROR] 加载 config.json 失败: {e}")
        return

    tts_calls = config.get("tts_calls", [])
    if not isinstance(tts_calls, list):
        print("[ERROR] config.json 中 tts_calls 应该是列表")
        return

    for idx, call in enumerate(tts_calls):
        try:
            print(f"[INFO] 正在调用第 {idx+1} 个 TTS 请求: {call}")
            resp = requests.post(f"http://localhost:{tts_port}/tts", json=call)
            if resp.status_code == 200:
                print(f"[SUCCESS] 第 {idx+1} 个调用成功")
            else:
                print(f"[FAIL] 第 {idx+1} 个调用失败，状态码：{resp.status_code}, 返回内容：{resp.text}")
        except Exception as e:
            print(f"[ERROR] 调用第 {idx+1} 个 TTS 失败: {e}")
        time.sleep(0.5)  # 可根据需要加延迟防止资源冲突

if __name__ == '__main__':
    # 加载配置到temp_files
    temp_files = load_temp_files()
    print(f'[INFO] Loaded temp_files from {CONFIG_FILE}: {temp_files}')
    # threading.Thread(target=call_tts_from_config, daemon=True).start()
    app.run(debug=False, host='0.0.0.0', port=tts_port)