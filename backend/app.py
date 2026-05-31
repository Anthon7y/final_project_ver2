from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_socketio import SocketIO, emit
from datetime import timedelta
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change-this-secret-key')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'change-this-secret-key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
    os.path.dirname(__file__), '..', 'furniture.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from backend.models import db as orm_db
orm_db.init_app(app)

jwt = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

from backend.database import Database
from backend.ai_analyzer import FurnitureAnalyzer
import bcrypt

db = Database()
analyzer = FurnitureAnalyzer()

# Создаём таблицы если их нет
with app.app_context():
    orm_db.create_all()


# ------------------------------------------------------------------ #
#  WebSocket — прогресс поиска                                        #
# ------------------------------------------------------------------ #

@socketio.on('connect')
def on_connect():
    emit('status', {'msg': 'connected'})


def emit_progress(sid, step, total, message):
    """Отправляет прогресс конкретному клиенту."""
    socketio.emit('search_progress', {
        'step': step, 'total': total, 'message': message
    }, room=sid)


# ------------------------------------------------------------------ #
#  Health                                                              #
# ------------------------------------------------------------------ #

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


# ------------------------------------------------------------------ #
#  Авторизация                                                         #
# ------------------------------------------------------------------ #

@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'error': 'Логин и пароль обязательны'}), 400
        if len(username) < 3:
            return jsonify({'error': 'Логин должен быть не менее 3 символов'}), 400
        if len(password) < 4:
            return jsonify({'error': 'Пароль должен быть не менее 4 символов'}), 400

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user_id = db.create_user(username, password_hash)

        if not user_id:
            return jsonify({'error': 'Пользователь с таким логином уже существует'}), 400

        token = create_access_token(identity=str(user_id))
        return jsonify({'access_token': token, 'user_id': user_id, 'username': username})
    except Exception as e:
        print(f"Register error: {e}")
        return jsonify({'error': 'server_error'}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'error': 'Логин и пароль обязательны'}), 400

        user = db.get_user_by_username(username)
        if not user or not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
            return jsonify({'error': 'Неверный логин или пароль'}), 401

        token = create_access_token(identity=str(user['id']))
        return jsonify({'access_token': token, 'user_id': user['id'], 'username': user['username']})
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({'error': 'server_error'}), 500


# ------------------------------------------------------------------ #
#  Поиск                                                               #
# ------------------------------------------------------------------ #

@app.route('/api/search/image', methods=['POST'])
def search_by_image():
    if 'image' not in request.files:
        return jsonify({'error': 'Нет изображения'}), 400

    file = request.files['image']
    sid  = request.form.get('sid')          # socket id для прогресса

    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    try:
        if sid: emit_progress(sid, 1, 3, 'Анализируем изображение...')

        analysis = analyzer.analyze_image(file)
        if not analysis:
            return jsonify({'error': 'no_furniture', 'message': 'no_furniture'}), 400

        if sid: emit_progress(sid, 2, 3, 'Ищем похожие товары...')

        search_params = {}
        if analysis.get('type'):   search_params['furniture_type'] = analysis['type']
        if analysis.get('colors'): search_params['colors'] = analysis['colors']

        results = db.search_furniture(**search_params, limit=20)
        if len(results) < 5 and analysis.get('type'):
            results = db.search_furniture(furniture_type=analysis['type'], limit=20)
        if len(results) < 5:
            results = db.search_furniture(limit=20)

        if sid: emit_progress(sid, 3, 3, 'Готово!')

        if not results:
            return jsonify({'results': [], 'analysis': analysis, 'message': 'no_results'})
        return jsonify({'analysis': analysis, 'results': results})

    except Exception as e:
        print(f"Image search error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': 'server_error'}), 500


@app.route('/api/search/room', methods=['POST'])
def search_by_room():
    if 'image' not in request.files:
        return jsonify({'error': 'Нет изображения'}), 400

    file = request.files['image']
    sid  = request.form.get('sid')

    furniture_type = request.form.get('type', '').strip()
    if not furniture_type:
        return jsonify({'error': 'Укажите тип мебели'}), 400

    min_price  = request.form.get('min_price')  or None
    max_price  = request.form.get('max_price')  or None
    min_width  = request.form.get('min_width')  or None
    max_width  = request.form.get('max_width')  or None
    min_length = request.form.get('min_length') or None
    max_length = request.form.get('max_length') or None
    min_height = request.form.get('min_height') or None
    max_height = request.form.get('max_height') or None

    try:
        import io
        if sid: emit_progress(sid, 1, 3, 'Анализируем интерьер...')

        room = analyzer.analyze_room(io.BytesIO(file.read()))
        room_style  = room.get('style')
        room_colors = room.get('colors', [])

        if sid: emit_progress(sid, 2, 3, 'Подбираем мебель...')

        candidates = db.search_furniture(
            furniture_type=furniture_type,
            min_price=min_price, max_price=max_price, limit=200
        )

        def in_range(val, lo, hi):
            if val is None: return True
            try:
                v = float(val)
                if lo and v < float(lo): return False
                if hi and v > float(hi): return False
                return True
            except Exception: return True

        if any([min_width, max_width, min_length, max_length, min_height, max_height]):
            candidates = [c for c in candidates
                if in_range(c.get('width'),  min_width,  max_width)
                and in_range(c.get('length'), min_length, max_length)
                and in_range(c.get('height'), min_height, max_height)]

        def score(item):
            s = 0
            if room_style and room_style.lower() in (item.get('style') or '').lower():
                s += 3
            for c in room_colors:
                if c.lower() in (item.get('colors') or '').lower():
                    s += 2
            return s

        top = sorted(candidates, key=score, reverse=True)[:7]
        if len(top) < 3:
            extra = [c for c in candidates if c not in top]
            top = (top + extra)[:max(3, len(top))]

        if sid: emit_progress(sid, 3, 3, 'Готово!')

        return jsonify({'room_analysis': room, 'results': top,
                        'message': 'no_results' if not top else ''})

    except Exception as e:
        print(f"Room search error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': 'server_error'}), 500


@app.route('/api/search/params', methods=['POST'])
def search_by_params():
    try:
        params = request.json or {}
        results = db.search_furniture(
            furniture_type=params.get('type'),
            min_price=params.get('min_price'), max_price=params.get('max_price'),
            width=params.get('width'), length=params.get('length'), height=params.get('height'),
            materials=params.get('materials'), colors=params.get('colors'),
            brand=params.get('brand'), style=params.get('style')
        )
        if not results:
            return jsonify({'results': [], 'message': 'no_results'})
        return jsonify({'results': results})
    except Exception as e:
        print(f"Params search error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': 'server_error'}), 500


# ------------------------------------------------------------------ #
#  Избранное                                                           #
# ------------------------------------------------------------------ #

@app.route('/api/favorites', methods=['GET'])
@jwt_required()
def get_favorites():
    try:
        user_id = int(get_jwt_identity())
        return jsonify({'favorites': db.get_favorites(user_id)})
    except Exception as e:
        print(f"Get favorites error: {e}")
        return jsonify({'error': 'server_error'}), 500


@app.route('/api/favorites/<int:furniture_id>', methods=['POST'])
@jwt_required()
def add_favorite(furniture_id):
    try:
        user_id = int(get_jwt_identity())
        success = db.add_to_favorites(user_id, furniture_id)
        return jsonify({'message': 'Добавлено в избранное' if success else 'Уже в избранном'})
    except Exception as e:
        print(f"Add favorite error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': f'Ошибка: {str(e)}'}), 500


@app.route('/api/favorites/<int:furniture_id>', methods=['DELETE'])
@jwt_required()
def remove_favorite(furniture_id):
    try:
        user_id = int(get_jwt_identity())
        db.remove_from_favorites(user_id, furniture_id)
        return jsonify({'message': 'Удалено из избранного'})
    except Exception as e:
        print(f"Remove favorite error: {e}")
        return jsonify({'error': 'server_error'}), 500


# ------------------------------------------------------------------ #
#  Справочники                                                         #
# ------------------------------------------------------------------ #

@app.route('/api/furniture/types', methods=['GET'])
def get_furniture_types():
    return jsonify({'types': sorted(db.get_distinct_values('type'))})

@app.route('/api/furniture/styles', methods=['GET'])
def get_styles():
    return jsonify({'styles': sorted(db.get_distinct_values('style'))})

@app.route('/api/furniture/colors', methods=['GET'])
def get_colors():
    return jsonify({'colors': sorted(db.get_distinct_values('colors'))})

@app.route('/api/furniture/materials', methods=['GET'])
def get_materials():
    return jsonify({'materials': sorted(db.get_distinct_values('materials'))})
    
#----------------попытка помочь себе---------------------------------------------------------------------------------------#
from flask import send_from_directory
import os

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react_app(path):
    # Не трогаем API и WebSocket
    if path.startswith('api/') or path.startswith('socket.io/'):
        return {"error": "Not found"}, 404

    build_dir = os.path.join(os.path.dirname(__file__), 'static')
    
    # Запрос корня — генерируем HTML с правильными ссылками
    if not path or path == 'index.html':
        html = """
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <meta name="description" content="Помощник по подбору мебели - найдите мебель по фото" />
            <title>Помощник по подбору мебели</title>
            <link href="/static/static/css/main.8cd491c6.css" rel="stylesheet">
        </head>
        <body>
            <noscript>Для работы сайта необходим JavaScript.</noscript>
            <div id="root"></div>
            <script defer="defer" src="/static/static/js/main.68e81bb2.js"></script>
        </body>
        </html>
        """
        return html, 200, {'Content-Type': 'text/html'}

    # Обработка запросов к статическим файлам (JS, CSS, картинки)
    # Если путь начинается с 'static/', ищем в подпапке static
    if path.startswith('static/'):
        # Убираем 'static/' и ищем внутри build_dir/static
        sub_path = path[7:]
        alt_path = os.path.join(build_dir, 'static', sub_path)
        if os.path.exists(alt_path) and os.path.isfile(alt_path):
            return send_from_directory(os.path.join(build_dir, 'static'), sub_path)
    
    # Если файл лежит прямо в build_dir (например, favicon.ico)
    direct_path = os.path.join(build_dir, path)
    if os.path.exists(direct_path) and os.path.isfile(direct_path):
        return send_from_directory(build_dir, path)
    
    # Всё остальное — отдаём index.html для клиентского роутинга
    return send_from_directory(build_dir, 'index.html')

@app.route('/debug/index')
def debug_index():
    build_dir = os.path.join(os.path.dirname(__file__), 'static')
    index_path = os.path.join(build_dir, 'index.html')
    if not os.path.exists(index_path):
        return "index.html not found"
    with open(index_path, 'r') as f:
        return f.read(), 200, {'Content-Type': 'text/html'}
# ------------------------------------------------------------------ #
#  Запуск                                                              #
# ------------------------------------------------------------------ #

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
