from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import hashlib
import os
import secrets
from datetime import timedelta, datetime
import pytz
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
import threading
from pin_manager import create_pin_manager
from inefable_api_client import get_inefable_client

app = Flask(__name__)

# Configuración de seguridad
# En producción, usar variables de entorno
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Configuración de cookies seguras (solo en producción con HTTPS)
is_production = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_SECURE'] = is_production  # Solo HTTPS en producción
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevenir XSS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Protección CSRF

# Configuración de duración de sesión (30 minutos)
app.permanent_session_lifetime = timedelta(minutes=30)

# Configuración de correo electrónico (solo 2 variables necesarias)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']

# Inicializar Flask-Mail
mail = Mail(app)

# Configuración de la base de datos
DATABASE = os.environ.get('DATABASE_PATH', 'usuarios.db')

# Crear directorio para la base de datos si no existe
db_dir = os.path.dirname(DATABASE)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

def init_db():
    """Inicializa la base de datos con las tablas necesarias"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            telefono TEXT NOT NULL,
            correo TEXT UNIQUE NOT NULL,
            contraseña TEXT NOT NULL,
            saldo REAL DEFAULT 0.0,
            fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de transacciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            numero_control TEXT NOT NULL,
            pin TEXT NOT NULL,
            transaccion_id TEXT NOT NULL,
            monto REAL DEFAULT 0.0,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Tabla de pines de Free Fire
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pines_freefire (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monto_id INTEGER NOT NULL,
            pin_codigo TEXT NOT NULL,
            usado BOOLEAN DEFAULT FALSE,
            fecha_agregado DATETIME DEFAULT CURRENT_TIMESTAMP,
            fecha_usado DATETIME NULL,
            usuario_id INTEGER NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Tabla de precios de paquetes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS precios_paquetes (
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            precio REAL NOT NULL,
            descripcion TEXT NOT NULL,
            activo BOOLEAN DEFAULT TRUE,
            fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de precios de Blood Striker
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS precios_bloodstriker (
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            precio REAL NOT NULL,
            descripcion TEXT NOT NULL,
            activo BOOLEAN DEFAULT TRUE,
            fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de transacciones de Blood Striker
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones_bloodstriker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            player_id TEXT NOT NULL,
            paquete_id INTEGER NOT NULL,
            numero_control TEXT NOT NULL,
            transaccion_id TEXT NOT NULL,
            monto REAL DEFAULT 0.0,
            estado TEXT DEFAULT 'pendiente',
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            fecha_procesado DATETIME NULL,
            admin_id INTEGER NULL,
            notas TEXT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (admin_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Insertar precios por defecto si no existen
    cursor.execute('SELECT COUNT(*) FROM precios_paquetes')
    if cursor.fetchone()[0] == 0:
        precios_default = [
            (1, '110 💎', 0.66, '110 Diamantes Free Fire', True),
            (2, '341 💎', 2.25, '341 Diamantes Free Fire', True),
            (3, '572 💎', 3.66, '572 Diamantes Free Fire', True),
            (4, '1.166 💎', 7.10, '1.166 Diamantes Free Fire', True),
            (5, '2.376 💎', 14.44, '2.376 Diamantes Free Fire', True),
            (6, '6.138 💎', 33.10, '6.138 Diamantes Free Fire', True),
            (7, 'Tarjeta básica', 0.50, 'Tarjeta básica Free Fire', True),
            (8, 'Tarjeta semanal', 1.55, 'Tarjeta semanal Free Fire', True),
            (9, 'Tarjeta mensual', 7.10, 'Tarjeta mensual Free Fire', True)
        ]
        cursor.executemany('''
            INSERT INTO precios_paquetes (id, nombre, precio, descripcion, activo)
            VALUES (?, ?, ?, ?, ?)
        ''', precios_default)
    
    # Insertar precios de Blood Striker por defecto si no existen
    cursor.execute('SELECT COUNT(*) FROM precios_bloodstriker')
    if cursor.fetchone()[0] == 0:
        precios_bloodstriker = [
            (1, '100+16 🪙', 0.82, '100+16 Monedas Blood Striker', True),
            (2, '300+52 🪙', 2.60, '300+52 Monedas Blood Striker', True),
            (3, '500+94 🪙', 4.30, '500+94 Monedas Blood Striker', True),
            (4, '1,000+210 🪙', 8.65, '1,000+210 Monedas Blood Striker', True),
            (5, '2,000+486 🪙', 17.30, '2,000+486 Monedas Blood Striker', True),
            (6, '5,000+1,380 🪙', 43.15, '5,000+1,380 Monedas Blood Striker', True),
            (7, 'Pase Elite 🎖️', 3.50, 'Pase Elite Blood Striker', True),
            (8, 'Pase Elite (Plus) 🎖️', 8.00, 'Pase Elite Plus Blood Striker', True),
            (9, 'Pase de Mejora 🔫', 1.85, 'Pase de Mejora Blood Striker', True),
            (10, 'Cofre Camuflaje Ultra 💼', 0.50, 'Cofre Camuflaje Ultra Blood Striker', True)
        ]
        cursor.executemany('''
            INSERT INTO precios_bloodstriker (id, nombre, precio, descripcion, activo)
            VALUES (?, ?, ?, ?, ?)
        ''', precios_bloodstriker)
    
    conn.commit()
    conn.close()

def hash_password(password):
    """Hashea la contraseña usando Werkzeug (más seguro que SHA256)"""
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

def verify_password(password, hashed):
    """Verifica la contraseña hasheada (compatible con métodos antiguos y nuevos)"""
    # Primero intentar con el nuevo método (PBKDF2)
    if hashed.startswith('pbkdf2:'):
        return check_password_hash(hashed, password)
    
    # Si no es PBKDF2, verificar con SHA256 (método anterior)
    sha256_hash = hashlib.sha256(password.encode()).hexdigest()
    return hashed == sha256_hash


def get_db_connection():
    """Obtiene una conexión a la base de datos"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def convert_to_venezuela_time(utc_datetime_str):
    """Convierte una fecha UTC a la zona horaria de Venezuela (UTC-4)"""
    try:
        # Parsear la fecha UTC desde la base de datos
        utc_dt = datetime.strptime(utc_datetime_str, '%Y-%m-%d %H:%M:%S')
        
        # Establecer como UTC
        utc_dt = pytz.utc.localize(utc_dt)
        
        # Convertir a zona horaria de Venezuela (UTC-4)
        venezuela_tz = pytz.timezone('America/Caracas')
        venezuela_dt = utc_dt.astimezone(venezuela_tz)
        
        # Retornar en formato legible
        return venezuela_dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        # Si hay error, retornar la fecha original
        return utc_datetime_str

def get_user_by_email(email):
    """Obtiene un usuario por su email"""
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM usuarios WHERE correo = ?', (email,)).fetchone()
    conn.close()
    return user

def create_user(nombre, apellido, telefono, correo, contraseña):
    """Crea un nuevo usuario en la base de datos"""
    conn = get_db_connection()
    hashed_password = hash_password(contraseña)
    try:
        cursor = conn.execute('''
            INSERT INTO usuarios (nombre, apellido, telefono, correo, contraseña, saldo)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nombre, apellido, telefono, correo, hashed_password, 0.0))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def get_user_transactions(user_id, is_admin=False, page=1, per_page=10):
    """Obtiene las transacciones de un usuario con información del paquete y paginación"""
    conn = get_db_connection()
    
    # Calcular offset para paginación
    offset = (page - 1) * per_page
    
    if is_admin:
        # Admin ve todas las transacciones de todos los usuarios
        transactions = conn.execute('''
            SELECT t.*, u.nombre, u.apellido
            FROM transacciones t
            JOIN usuarios u ON t.usuario_id = u.id
            ORDER BY t.fecha DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset)).fetchall()
        
        # Obtener total de transacciones para paginación
        total_count = conn.execute('''
            SELECT COUNT(*) FROM transacciones t
            JOIN usuarios u ON t.usuario_id = u.id
        ''').fetchone()[0]
    else:
        # Usuario normal ve solo sus transacciones
        transactions = conn.execute('''
            SELECT t.*, u.nombre, u.apellido
            FROM transacciones t
            JOIN usuarios u ON t.usuario_id = u.id
            WHERE t.usuario_id = ? 
            ORDER BY t.fecha DESC
            LIMIT ? OFFSET ?
        ''', (user_id, per_page, offset)).fetchall()
        
        # Obtener total de transacciones del usuario para paginación
        total_count = conn.execute('''
            SELECT COUNT(*) FROM transacciones t
            JOIN usuarios u ON t.usuario_id = u.id
            WHERE t.usuario_id = ?
        ''', (user_id,)).fetchone()[0]
    
    # Obtener precios dinámicos de la base de datos (Free Fire y Blood Striker)
    packages_info = get_package_info_with_prices()
    bloodstriker_packages_info = get_bloodstriker_prices()
    
    # Agregar información del paquete basado en el monto dinámico
    transactions_with_package = []
    for transaction in transactions:
        transaction_dict = dict(transaction)
        monto = abs(transaction['monto'])  # Usar valor absoluto para comparar
        
        # Buscar el paquete que coincida con el monto (con tolerancia para decimales)
        paquete_encontrado = False
        
        # Primero buscar en paquetes de Free Fire
        for package_id, package_info in packages_info.items():
            if abs(monto - package_info['precio']) < 0.01:  # Tolerancia de 1 centavo
                transaction_dict['paquete'] = package_info['nombre']
                paquete_encontrado = True
                break
        
        # Si no se encuentra en Free Fire, buscar en Blood Striker
        if not paquete_encontrado:
            for package_id, package_info in bloodstriker_packages_info.items():
                if abs(monto - package_info['precio']) < 0.01:  # Tolerancia de 1 centavo
                    transaction_dict['paquete'] = package_info['nombre']
                    paquete_encontrado = True
                    break
        
        # Si no se encuentra coincidencia exacta, usar el nombre por defecto
        if not paquete_encontrado:
            transaction_dict['paquete'] = f"Paquete ${monto:.2f}"
        
        # Convertir fecha a zona horaria de Venezuela
        transaction_dict['fecha'] = convert_to_venezuela_time(transaction_dict['fecha'])
        
        transactions_with_package.append(transaction_dict)
    
    conn.close()
    
    # Calcular información de paginación
    total_pages = (total_count + per_page - 1) // per_page  # Redondear hacia arriba
    has_prev = page > 1
    has_next = page < total_pages
    
    return {
        'transactions': transactions_with_package,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_prev': has_prev,
            'has_next': has_next,
            'prev_num': page - 1 if has_prev else None,
            'next_num': page + 1 if has_next else None
        }
    }

def get_user_wallet_credits(user_id):
    """Obtiene los créditos de billetera de un usuario"""
    conn = get_db_connection()
    # Crear tabla si no existe
    conn.execute('''
        CREATE TABLE IF NOT EXISTS creditos_billetera (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            monto REAL DEFAULT 0.0,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    credits = conn.execute('''
        SELECT * FROM creditos_billetera 
        WHERE usuario_id = ? 
        ORDER BY fecha DESC
    ''', (user_id,)).fetchall()
    conn.close()
    return credits


# Inicializar la base de datos al iniciar la aplicación
init_db()

@app.route('/')
def index():
    if 'usuario' not in session:
        return redirect('/auth')
    
    # Obtener parámetros de paginación
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Transacciones por página
    
    user_id = session.get('id', '00000')
    transactions_data = {}
    is_admin = session.get('is_admin', False)
    
    if is_admin:
        # Admin ve todas las transacciones de todos los usuarios con paginación
        transactions_data = get_user_transactions(None, is_admin=True, page=page, per_page=per_page)
        
        # Para admin, también agregar transacciones pendientes de Blood Striker solo en la primera página
        if page == 1:
            bloodstriker_transactions = get_pending_bloodstriker_transactions()
            # Combinar transacciones normales con las de Blood Striker
            all_transactions = list(transactions_data['transactions']) + list(bloodstriker_transactions)
            # Ordenar por fecha
            all_transactions.sort(key=lambda x: x.get('fecha', ''), reverse=True)
            # Tomar solo las primeras per_page transacciones
            transactions_data['transactions'] = all_transactions[:per_page]
        
        balance = 0  # Admin no tiene saldo
    else:
        # Usuario normal ve solo sus transacciones
        if 'user_db_id' in session:
            # Actualizar saldo desde la base de datos SIEMPRE
            conn = get_db_connection()
            user = conn.execute('SELECT saldo FROM usuarios WHERE id = ?', (session['user_db_id'],)).fetchone()
            if user:
                session['saldo'] = user['saldo']
                balance = user['saldo']
            else:
                balance = 0
            conn.close()
            
            # Obtener transacciones normales del usuario con paginación
            transactions_data = get_user_transactions(session['user_db_id'], is_admin=False, page=page, per_page=per_page)
            
            # Para usuario normal, también agregar transacciones pendientes de Blood Striker solo en la primera página
            if page == 1:
                user_bloodstriker_transactions = get_user_pending_bloodstriker_transactions(session['user_db_id'])
                # Combinar transacciones normales con las de Blood Striker del usuario
                all_user_transactions = list(transactions_data['transactions']) + list(user_bloodstriker_transactions)
                # Ordenar por fecha
                all_user_transactions.sort(key=lambda x: x.get('fecha', ''), reverse=True)
                # Tomar solo las primeras per_page transacciones
                transactions_data['transactions'] = all_user_transactions[:per_page]
        else:
            balance = 0
            transactions_data = {'transactions': [], 'pagination': {'page': 1, 'total_pages': 0, 'has_prev': False, 'has_next': False}}
    
    return render_template('index.html', 
                         user_id=user_id, 
                         balance=balance, 
                         transactions=transactions_data['transactions'],
                         pagination=transactions_data['pagination'],
                         is_admin=is_admin)

@app.route('/auth')
def auth():
    return render_template('auth.html')

@app.route('/login', methods=['POST'])
def login():
    correo = request.form['correo']
    contraseña = request.form['contraseña']
    
    if not correo or not contraseña:
        flash('Por favor, complete todos los campos', 'error')
        return redirect('/auth')
    
    # Verificar credenciales de administrador (desde variables de entorno)
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@inefable.com')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'InefableAdmin2024!')
    
    if correo == admin_email and contraseña == admin_password:
        session.permanent = True  # Activar duración de sesión de 30 minutos
        session['usuario'] = admin_email
        session['nombre'] = 'Administrador'
        session['apellido'] = 'Sistema'
        session['id'] = 'ADMIN'
        session['user_db_id'] = 0
        session['saldo'] = 0
        session['is_admin'] = True
        return redirect('/')
    
    # Buscar usuario en la base de datos
    user = get_user_by_email(correo)
    
    if user and verify_password(contraseña, user['contraseña']):
        # Migrar contraseña antigua a nuevo formato si es necesario
        if not user['contraseña'].startswith('pbkdf2:'):
            # Actualizar contraseña al nuevo formato seguro
            new_hashed_password = hash_password(contraseña)
            conn = get_db_connection()
            conn.execute('UPDATE usuarios SET contraseña = ? WHERE id = ?', 
                        (new_hashed_password, user['id']))
            conn.commit()
            conn.close()
            print(f"Contraseña migrada para usuario: {user['correo']}")
        
        # Login exitoso
        session.permanent = True  # Activar duración de sesión de 30 minutos
        session['usuario'] = user['correo']
        session['nombre'] = user['nombre']
        session['apellido'] = user['apellido']
        session['id'] = str(user['id']).zfill(5)
        session['user_db_id'] = user['id']
        session['saldo'] = user['saldo']
        session['is_admin'] = False
        return redirect('/')
    else:
        flash('Credenciales incorrectas', 'error')
        return redirect('/auth')

@app.route('/register', methods=['POST'])
def register():
    nombre = request.form.get('nombre')
    apellido = request.form.get('apellido')
    telefono = request.form.get('telefono')
    correo = request.form.get('correo')
    contraseña = request.form.get('contraseña')
    
    # Validar que todos los campos estén completos
    if not all([nombre, apellido, telefono, correo, contraseña]):
        flash('Por favor, complete todos los campos', 'error')
        return redirect('/auth')
    
    # Verificar si el usuario ya existe
    if get_user_by_email(correo):
        flash('El correo electrónico ya está registrado', 'error')
        return redirect('/auth')
    
    # Crear nuevo usuario
    user_id = create_user(nombre, apellido, telefono, correo, contraseña)
    
    if user_id:
        # Registro exitoso, iniciar sesión automáticamente
        session.permanent = True  # Activar duración de sesión de 30 minutos
        session['usuario'] = correo
        session['nombre'] = nombre
        session['apellido'] = apellido
        session['id'] = str(user_id).zfill(5)
        session['user_db_id'] = user_id
        session['saldo'] = 0.0  # Saldo inicial
        flash('Registro exitoso. ¡Bienvenido!', 'success')
        return redirect('/')
    else:
        flash('Error al crear la cuenta. Intente nuevamente.', 'error')
        return redirect('/auth')


# Funciones de administrador
def get_all_users():
    """Obtiene todos los usuarios registrados"""
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM usuarios ORDER BY fecha_registro DESC').fetchall()
    conn.close()
    return users

def update_user_balance(user_id, new_balance):
    """Actualiza el saldo de un usuario"""
    conn = get_db_connection()
    conn.execute('UPDATE usuarios SET saldo = ? WHERE id = ?', (new_balance, user_id))
    conn.commit()
    conn.close()

def delete_user(user_id):
    """Elimina un usuario y todos sus datos relacionados"""
    conn = get_db_connection()
    # Eliminar transacciones del usuario
    conn.execute('DELETE FROM transacciones WHERE usuario_id = ?', (user_id,))
    # Eliminar créditos de billetera del usuario
    conn.execute('DELETE FROM creditos_billetera WHERE usuario_id = ?', (user_id,))
    # Eliminar usuario
    conn.execute('DELETE FROM usuarios WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

def add_credit_to_user(user_id, amount):
    """Añade crédito al saldo de un usuario y registra en billetera"""
    conn = get_db_connection()
    
    # Crear tabla de créditos de billetera si no existe
    conn.execute('''
        CREATE TABLE IF NOT EXISTS creditos_billetera (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            monto REAL DEFAULT 0.0,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Actualizar saldo del usuario
    conn.execute('UPDATE usuarios SET saldo = saldo + ? WHERE id = ?', (amount, user_id))
    
    # Registrar en créditos de billetera (solo monto y fecha)
    conn.execute('''
        INSERT INTO creditos_billetera (usuario_id, monto)
        VALUES (?, ?)
    ''', (user_id, amount))
    
    # Limitar créditos de billetera a 10 por usuario - eliminar los más antiguos si hay más de 10
    conn.execute('''
        DELETE FROM creditos_billetera 
        WHERE usuario_id = ? AND id NOT IN (
            SELECT id FROM creditos_billetera 
            WHERE usuario_id = ? 
            ORDER BY fecha DESC 
            LIMIT 10
        )
    ''', (user_id, user_id))
    
    conn.commit()
    conn.close()

# Funciones para pines de Free Fire
def add_pin_freefire(monto_id, pin_codigo):
    """Añade un pin de Free Fire al stock"""
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO pines_freefire (monto_id, pin_codigo)
        VALUES (?, ?)
    ''', (monto_id, pin_codigo))
    conn.commit()
    conn.close()

def add_pins_batch(monto_id, pins_list):
    """Añade múltiples pines de Free Fire al stock en lote"""
    conn = get_db_connection()
    try:
        for pin_codigo in pins_list:
            pin_codigo = pin_codigo.strip()
            if pin_codigo:  # Solo agregar si el pin no está vacío
                conn.execute('''
                    INSERT INTO pines_freefire (monto_id, pin_codigo)
                    VALUES (?, ?)
                ''', (monto_id, pin_codigo))
        conn.commit()
        return len([p for p in pins_list if p.strip()])  # Retornar cantidad agregada
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_pin_stock():
    """Obtiene el stock de pines por monto_id"""
    conn = get_db_connection()
    stock = {}
    for i in range(1, 10):  # monto_id del 1 al 9
        count = conn.execute('''
            SELECT COUNT(*) FROM pines_freefire 
            WHERE monto_id = ? AND usado = FALSE
        ''', (i,)).fetchone()[0]
        stock[i] = count
    conn.close()
    return stock

def get_available_pin(monto_id):
    """Obtiene un pin disponible para el monto especificado"""
    conn = get_db_connection()
    pin = conn.execute('''
        SELECT * FROM pines_freefire 
        WHERE monto_id = ? AND usado = FALSE 
        LIMIT 1
    ''', (monto_id,)).fetchone()
    conn.close()
    return pin


def get_all_pins():
    """Obtiene todos los pines para el admin"""
    conn = get_db_connection()
    pins = conn.execute('''
        SELECT p.*, u.nombre, u.apellido 
        FROM pines_freefire p
        LEFT JOIN usuarios u ON p.usuario_id = u.id
        ORDER BY p.fecha_agregado DESC
    ''').fetchall()
    conn.close()
    return pins

def remove_duplicate_pins():
    """Elimina pines duplicados de la base de datos, manteniendo el más reciente de cada código"""
    conn = get_db_connection()
    try:
        # Encontrar pines duplicados y eliminar los más antiguos
        duplicates_removed = conn.execute('''
            DELETE FROM pines_freefire 
            WHERE id NOT IN (
                SELECT MIN(id) 
                FROM pines_freefire 
                GROUP BY pin_codigo, monto_id
            )
        ''').rowcount
        
        conn.commit()
        return duplicates_removed
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_duplicate_pins_count():
    """Obtiene el número de pines duplicados en la base de datos"""
    conn = get_db_connection()
    try:
        # Contar pines duplicados
        result = conn.execute('''
            SELECT COUNT(*) - COUNT(DISTINCT pin_codigo || '-' || monto_id) as duplicates
            FROM pines_freefire
            WHERE usado = FALSE
        ''').fetchone()
        
        return result[0] if result else 0
    finally:
        conn.close()

# Funciones para gestión de precios
def get_all_prices():
    """Obtiene todos los precios de paquetes"""
    conn = get_db_connection()
    prices = conn.execute('''
        SELECT * FROM precios_paquetes 
        ORDER BY id
    ''').fetchall()
    conn.close()
    return prices

def get_price_by_id(monto_id):
    """Obtiene el precio de un paquete específico"""
    conn = get_db_connection()
    price = conn.execute('''
        SELECT precio FROM precios_paquetes 
        WHERE id = ? AND activo = TRUE
    ''', (monto_id,)).fetchone()
    conn.close()
    return price['precio'] if price else 0

def update_package_price(package_id, new_price):
    """Actualiza el precio de un paquete"""
    conn = get_db_connection()
    conn.execute('''
        UPDATE precios_paquetes 
        SET precio = ?, fecha_actualizacion = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (new_price, package_id))
    conn.commit()
    conn.close()

def get_package_info_with_prices():
    """Obtiene información de paquetes con precios dinámicos"""
    conn = get_db_connection()
    packages = conn.execute('''
        SELECT id, nombre, precio, descripcion 
        FROM precios_paquetes 
        WHERE activo = TRUE 
        ORDER BY id
    ''').fetchall()
    conn.close()
    
    # Convertir a diccionario para fácil acceso
    package_dict = {}
    for package in packages:
        package_dict[package['id']] = {
            'nombre': package['nombre'],
            'precio': package['precio'],
            'descripcion': package['descripcion']
        }
    
    return package_dict

# Funciones para Blood Striker
def get_bloodstriker_prices():
    """Obtiene información de paquetes de Blood Striker con precios dinámicos"""
    conn = get_db_connection()
    packages = conn.execute('''
        SELECT id, nombre, precio, descripcion 
        FROM precios_bloodstriker 
        WHERE activo = TRUE 
        ORDER BY id
    ''').fetchall()
    conn.close()
    
    # Convertir a diccionario para fácil acceso
    package_dict = {}
    for package in packages:
        package_dict[package['id']] = {
            'nombre': package['nombre'],
            'precio': package['precio'],
            'descripcion': package['descripcion']
        }
    
    return package_dict

def get_bloodstriker_price_by_id(package_id):
    """Obtiene el precio de un paquete específico de Blood Striker"""
    conn = get_db_connection()
    price = conn.execute('''
        SELECT precio FROM precios_bloodstriker 
        WHERE id = ? AND activo = TRUE
    ''', (package_id,)).fetchone()
    conn.close()
    return price['precio'] if price else 0

def create_bloodstriker_transaction(user_id, player_id, package_id, precio):
    """Crea una transacción pendiente de Blood Striker"""
    import random
    import string
    
    # Generar datos de la transacción
    numero_control = ''.join(random.choices(string.digits, k=10))
    transaccion_id = 'BS-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    conn = get_db_connection()
    try:
        # Insertar transacción pendiente
        cursor = conn.execute('''
            INSERT INTO transacciones_bloodstriker 
            (usuario_id, player_id, paquete_id, numero_control, transaccion_id, monto, estado)
            VALUES (?, ?, ?, ?, ?, ?, 'pendiente')
        ''', (user_id, player_id, package_id, numero_control, transaccion_id, -precio))
        
        transaction_id = cursor.lastrowid
        conn.commit()
        return {
            'id': transaction_id,
            'numero_control': numero_control,
            'transaccion_id': transaccion_id
        }
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_pending_bloodstriker_transactions():
    """Obtiene todas las transacciones pendientes de Blood Striker para el admin"""
    conn = get_db_connection()
    transactions = conn.execute('''
        SELECT bs.*, u.nombre, u.apellido, u.correo, p.nombre as paquete_nombre
        FROM transacciones_bloodstriker bs
        JOIN usuarios u ON bs.usuario_id = u.id
        JOIN precios_bloodstriker p ON bs.paquete_id = p.id
        WHERE bs.estado = 'pendiente'
        ORDER BY bs.fecha DESC
    ''').fetchall()
    
    # Formatear las transacciones de Blood Striker para que sean compatibles con el template
    formatted_transactions = []
    for transaction in transactions:
        formatted_transaction = {
            'id': transaction['id'],
            'usuario_id': transaction['usuario_id'],
            'numero_control': transaction['numero_control'],
            'transaccion_id': transaction['transaccion_id'],
            'monto': transaction['monto'],
            'fecha': transaction['fecha'],
            'nombre': transaction['nombre'],
            'apellido': transaction['apellido'],
            'paquete': transaction['paquete_nombre'],
            'pin': f"ID: {transaction['player_id']}",  # Mostrar Player ID en lugar de PIN
            'estado': transaction['estado'],
            'is_bloodstriker': True  # Marcar como transacción de Blood Striker
        }
        formatted_transactions.append(formatted_transaction)
    
    conn.close()
    return formatted_transactions

def get_user_pending_bloodstriker_transactions(user_id):
    """Obtiene las transacciones pendientes de Blood Striker de un usuario específico"""
    conn = get_db_connection()
    transactions = conn.execute('''
        SELECT bs.*, u.nombre, u.apellido, p.nombre as paquete_nombre
        FROM transacciones_bloodstriker bs
        JOIN usuarios u ON bs.usuario_id = u.id
        JOIN precios_bloodstriker p ON bs.paquete_id = p.id
        WHERE bs.usuario_id = ? AND bs.estado = 'pendiente'
        ORDER BY bs.fecha DESC
    ''', (user_id,)).fetchall()
    
    # Formatear las transacciones de Blood Striker para que sean compatibles con el template
    formatted_transactions = []
    for transaction in transactions:
        formatted_transaction = {
            'id': transaction['id'],
            'usuario_id': transaction['usuario_id'],
            'numero_control': transaction['numero_control'],
            'transaccion_id': transaction['transaccion_id'],
            'monto': transaction['monto'],
            'fecha': convert_to_venezuela_time(transaction['fecha']),  # Convertir a zona horaria de Venezuela
            'nombre': transaction['nombre'],
            'apellido': transaction['apellido'],
            'paquete': transaction['paquete_nombre'],
            'pin': f"ID: {transaction['player_id']}",  # Mostrar Player ID del usuario
            'estado': transaction['estado'],
            'is_bloodstriker': True  # Marcar como transacción de Blood Striker
        }
        formatted_transactions.append(formatted_transaction)
    
    conn.close()
    return formatted_transactions

def update_bloodstriker_transaction_status(transaction_id, new_status, admin_id, notas=None):
    """Actualiza el estado de una transacción de Blood Striker"""
    conn = get_db_connection()
    conn.execute('''
        UPDATE transacciones_bloodstriker 
        SET estado = ?, admin_id = ?, notas = ?, fecha_procesado = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (new_status, admin_id, notas, transaction_id))
    conn.commit()
    conn.close()

def update_bloodstriker_price(package_id, new_price):
    """Actualiza el precio de un paquete de Blood Striker"""
    conn = get_db_connection()
    conn.execute('''
        UPDATE precios_bloodstriker 
        SET precio = ?, fecha_actualizacion = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (new_price, package_id))
    conn.commit()
    conn.close()

def get_all_bloodstriker_prices():
    """Obtiene todos los precios de paquetes de Blood Striker"""
    conn = get_db_connection()
    prices = conn.execute('''
        SELECT * FROM precios_bloodstriker 
        ORDER BY id
    ''').fetchall()
    conn.close()
    return prices

# Funciones de notificación por correo
def send_email_async(app, msg):
    """Envía correo de forma asíncrona"""
    with app.app_context():
        try:
            mail.send(msg)
            print("Correo de notificación enviado exitosamente")
        except Exception as e:
            print(f"Error al enviar correo: {str(e)}")

def send_bloodstriker_notification(transaction_data):
    """Envía notificación por correo cuando hay una nueva transacción de Blood Striker"""
    # Verificar si las credenciales de correo están configuradas
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        print("Credenciales de correo no configuradas. Notificación omitida.")
        return
    
    try:
        # Obtener correo del administrador
        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@inefable.com')
        
        # Crear mensaje
        msg = Message(
            subject='🎯 Nueva Transacción Blood Striker Pendiente',
            recipients=[admin_email],
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        
        # Contenido del correo
        msg.html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #667eea; text-align: center;">🎯 Nueva Transacción Blood Striker</h2>
                
                <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #333; margin-top: 0;">Detalles de la Transacción:</h3>
                    
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Usuario:</td>
                            <td style="padding: 8px 0;">{transaction_data['nombre']} {transaction_data['apellido']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Correo:</td>
                            <td style="padding: 8px 0;">{transaction_data['correo']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Player ID:</td>
                            <td style="padding: 8px 0; font-family: monospace; background: #e9ecef; padding: 4px 8px; border-radius: 4px;">{transaction_data['player_id']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Paquete:</td>
                            <td style="padding: 8px 0;">{transaction_data['paquete_nombre']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Monto:</td>
                            <td style="padding: 8px 0; color: #dc3545; font-weight: bold;">${transaction_data['precio']:.2f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Número de Control:</td>
                            <td style="padding: 8px 0; font-family: monospace;">{transaction_data['numero_control']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">ID de Transacción:</td>
                            <td style="padding: 8px 0; font-family: monospace;">{transaction_data['transaccion_id']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: bold;">Fecha:</td>
                            <td style="padding: 8px 0;">{transaction_data['fecha']}</td>
                        </tr>
                    </table>
                </div>
                
                <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 6px; margin: 20px 0;">
                    <p style="margin: 0; color: #856404;">
                        <strong>⏳ Acción Requerida:</strong> Esta transacción está pendiente de aprobación. 
                        Ingresa al panel de administración para aprobar o rechazar la solicitud.
                    </p>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <p style="color: #6c757d; font-size: 14px;">
                        Este es un correo automático del sistema de notificaciones.<br>
                        No responder a este correo.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Enviar correo de forma asíncrona
        thread = threading.Thread(target=send_email_async, args=(app, msg))
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        print(f"Error al preparar notificación por correo: {str(e)}")

# Rutas de administrador
@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    users = get_all_users()
    pin_stock = get_pin_stock()
    prices = get_all_prices()
    bloodstriker_prices = get_all_bloodstriker_prices()
    
    # Obtener estado de la API externa
    pin_manager = create_pin_manager(DATABASE)
    api_status = pin_manager.get_stock_status()
    
    return render_template('admin.html', 
                         users=users, 
                         pin_stock=pin_stock, 
                         prices=prices, 
                         bloodstriker_prices=bloodstriker_prices,
                         api_status=api_status)

@app.route('/admin/add_credit', methods=['POST'])
def admin_add_credit():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    user_id = request.form.get('user_id')
    amount = float(request.form.get('amount', 0))
    
    if user_id and amount > 0:
        add_credit_to_user(user_id, amount)
        flash(f'Se agregaron ${amount:.2f} al usuario ID {user_id}', 'success')
    else:
        flash('Datos inválidos para agregar crédito', 'error')
    
    return redirect('/admin')

@app.route('/admin/update_balance', methods=['POST'])
def admin_update_balance():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    user_id = request.form.get('user_id')
    new_balance = float(request.form.get('new_balance', 0))
    
    if user_id and new_balance >= 0:
        update_user_balance(user_id, new_balance)
        flash(f'Saldo actualizado a ${new_balance:.2f} para usuario ID {user_id}', 'success')
    else:
        flash('Datos inválidos para actualizar saldo', 'error')
    
    return redirect('/admin')

@app.route('/admin/delete_user', methods=['POST'])
def admin_delete_user():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    user_id = request.form.get('user_id')
    
    if user_id:
        delete_user(user_id)
        flash(f'Usuario ID {user_id} eliminado exitosamente', 'success')
    else:
        flash('ID de usuario inválido', 'error')
    
    return redirect('/admin')

@app.route('/admin/add_pin', methods=['POST'])
def admin_add_pin():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    monto_id = request.form.get('monto_id')
    pin_codigo = request.form.get('pin_codigo')
    
    if monto_id and pin_codigo:
        add_pin_freefire(int(monto_id), pin_codigo)
        
        # Obtener información del paquete dinámicamente
        packages_info = get_package_info_with_prices()
        package_info = packages_info.get(int(monto_id), {})
        
        if package_info:
            paquete_nombre = f"{package_info['nombre']} / ${package_info['precio']:.2f}"
        else:
            paquete_nombre = "Paquete desconocido"
        
        flash(f'Pin agregado exitosamente para {paquete_nombre}', 'success')
    else:
        flash('Datos inválidos para agregar pin', 'error')
    
    return redirect('/admin')

@app.route('/admin/add_pins_batch', methods=['POST'])
def admin_add_pins_batch():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    monto_id = request.form.get('batch_monto_id')
    pins_text = request.form.get('pins_batch')
    
    if not monto_id or not pins_text:
        flash('Por favor complete todos los campos para el lote de pines', 'error')
        return redirect('/admin')
    
    # Procesar los pines (separados por líneas o comas)
    pins_list = []
    for line in pins_text.replace(',', '\n').split('\n'):
        pin = line.strip()
        if pin:
            pins_list.append(pin)
    
    if not pins_list:
        flash('No se encontraron pines válidos en el texto', 'error')
        return redirect('/admin')
    
    # Sin límite de pines por lote
    
    try:
        added_count = add_pins_batch(int(monto_id), pins_list)
        
        # Obtener información del paquete dinámicamente
        packages_info = get_package_info_with_prices()
        package_info = packages_info.get(int(monto_id), {})
        
        if package_info:
            paquete_nombre = f"{package_info['nombre']} / ${package_info['precio']:.2f}"
        else:
            paquete_nombre = "Paquete desconocido"
        
        flash(f'Se agregaron {added_count} pines exitosamente para {paquete_nombre}', 'success')
        
    except Exception as e:
        flash(f'Error al agregar pines en lote: {str(e)}', 'error')
    
    return redirect('/admin')

@app.route('/admin/remove_duplicates', methods=['POST'])
def admin_remove_duplicates():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    try:
        duplicates_removed = remove_duplicate_pins()
        if duplicates_removed > 0:
            flash(f'Se eliminaron {duplicates_removed} pines duplicados exitosamente', 'success')
        else:
            flash('No se encontraron pines duplicados para eliminar', 'success')
    except Exception as e:
        flash(f'Error al eliminar pines duplicados: {str(e)}', 'error')
    
    return redirect('/admin')

@app.route('/admin/update_price', methods=['POST'])
def admin_update_price():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    package_id = request.form.get('package_id')
    new_price = request.form.get('new_price')
    
    if not package_id or not new_price:
        flash('Datos inválidos para actualizar precio', 'error')
        return redirect('/admin')
    
    try:
        new_price = float(new_price)
        if new_price < 0:
            flash('El precio no puede ser negativo', 'error')
            return redirect('/admin')
        
        # Obtener información del paquete antes de actualizar
        conn = get_db_connection()
        package = conn.execute('SELECT nombre FROM precios_paquetes WHERE id = ?', (package_id,)).fetchone()
        conn.close()
        
        if not package:
            flash('Paquete no encontrado', 'error')
            return redirect('/admin')
        
        # Actualizar precio
        update_package_price(int(package_id), new_price)
        flash(f'Precio actualizado exitosamente para {package["nombre"]}: ${new_price:.2f}', 'success')
        
    except ValueError:
        flash('Precio inválido. Debe ser un número válido.', 'error')
    except Exception as e:
        flash(f'Error al actualizar precio: {str(e)}', 'error')
    
    return redirect('/admin')

@app.route('/billetera')
def billetera():
    if 'usuario' not in session:
        return redirect('/auth')
    
    # Solo usuarios normales pueden ver su billetera
    if session.get('is_admin'):
        flash('Los administradores no tienen billetera', 'error')
        return redirect('/')
    
    user_id = session.get('user_db_id')
    if not user_id:
        flash('Error al acceder a la billetera', 'error')
        return redirect('/')
    
    # Obtener créditos de billetera
    wallet_credits = get_user_wallet_credits(user_id)
    
    # Actualizar saldo
    conn = get_db_connection()
    user = conn.execute('SELECT saldo FROM usuarios WHERE id = ?', (user_id,)).fetchone()
    if user:
        session['saldo'] = user['saldo']
    conn.close()
    
    return render_template('billetera.html', 
                         wallet_credits=wallet_credits, 
                         user_id=session.get('id', '00000'),
                         balance=session.get('saldo', 0))


@app.route('/validar/freefire_latam', methods=['POST'])
def validar_freefire_latam():
    if 'usuario' not in session:
        return redirect('/auth')
    
    monto_id = request.form.get('monto')
    cantidad = request.form.get('cantidad')
    
    if not monto_id or not cantidad:
        flash('Por favor selecciona un paquete y cantidad', 'error')
        return redirect('/juego/freefire_latam')
    
    monto_id = int(monto_id)
    cantidad = int(cantidad)
    user_id = session.get('user_db_id')
    is_admin = session.get('is_admin', False)
    
    # Validar cantidad (entre 1 y 10)
    if cantidad < 1 or cantidad > 10:
        flash('La cantidad debe estar entre 1 y 10 pines', 'error')
        return redirect('/juego/freefire_latam')
    
    # Obtener precio dinámico de la base de datos
    precio_unitario = get_price_by_id(monto_id)
    precio_total = precio_unitario * cantidad
    
    # Obtener información del paquete
    packages_info = get_package_info_with_prices()
    package_info = packages_info.get(monto_id, {})
    
    paquete_nombre = f"{package_info.get('nombre', 'Paquete')} x{cantidad}"
    
    if precio_unitario == 0:
        flash('Paquete no encontrado o inactivo', 'error')
        return redirect('/juego/freefire_latam')
    
    saldo_actual = session.get('saldo', 0)
    
    # Solo verificar saldo para usuarios normales, admin puede comprar sin saldo
    if not is_admin and saldo_actual < precio_total:
        flash(f'Saldo insuficiente. Necesitas ${precio_total:.2f} pero tienes ${saldo_actual:.2f}', 'error')
        return redirect('/juego/freefire_latam')
    
    # Usar el nuevo sistema de gestión de pines con respaldo de API externa
    pin_manager = create_pin_manager(DATABASE)
    
    try:
        # Solicitar pines usando el gestor con respaldo de API externa
        if cantidad == 1:
            # Para un solo pin
            result = pin_manager.request_pin_with_fallback(monto_id, use_external_api=True)
            
            if result.get('status') == 'success':
                pines_codigos = [result.get('pin_code')]
                sources_used = [result.get('source')]
            else:
                # Verificar si es específicamente un error de falta de stock
                error_type = result.get('error_type', 'unknown')
                if error_type in ['no_stock_anywhere', 'no_stock', 'no_pin_found']:
                    flash('Sin stock disponible para este paquete. Intente más tarde.', 'error')
                else:
                    flash(f'Error al obtener pin: {result.get("message", "Error desconocido")}', 'error')
                return redirect('/juego/freefire_latam')
        else:
            # Para múltiples pines
            result = pin_manager.request_multiple_pins(monto_id, cantidad, use_external_api=True)
            
            if result.get('status') in ['success', 'partial_success']:
                pines_data = result.get('pins', [])
                pines_codigos = [pin['pin_code'] for pin in pines_data]
                sources_used = list(set([pin['source'] for pin in pines_data]))
                
                if result.get('status') == 'partial_success':
                    cantidad_obtenida = len(pines_codigos)
                    flash(f'Solo se pudieron obtener {cantidad_obtenida} de {cantidad} pines solicitados', 'warning')
                    # Ajustar precio total según pines obtenidos
                    precio_total = precio_unitario * cantidad_obtenida
                    cantidad = cantidad_obtenida
                    paquete_nombre = f"{package_info.get('nombre', 'Paquete')} x{cantidad}"
            else:
                flash(f'Error al obtener pines: {result.get("message", "Error desconocido")}', 'error')
                return redirect('/juego/freefire_latam')
        
        # Verificar que se obtuvieron pines
        if not pines_codigos:
            flash('No se pudieron obtener pines. Intente nuevamente.', 'error')
            return redirect('/juego/freefire_latam')
        
        # Generar datos de la transacción
        import random
        import string
        numero_control = ''.join(random.choices(string.digits, k=10))
        transaccion_id = 'FF-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Procesar la transacción
        conn = get_db_connection()
        try:
            # Solo actualizar saldo si no es admin
            if not is_admin:
                conn.execute('UPDATE usuarios SET saldo = saldo - ? WHERE id = ?', (precio_total, user_id))
            
            # Registrar la transacción
            pines_texto = '\n'.join(pines_codigos)
            
            # Para admin, registrar con monto 0 para indicar que fue una prueba/gestión
            monto_transaccion = 0 if is_admin else -precio_total
            
            # Agregar información de fuente en el pin si viene de API externa
            if 'inefable_api' in sources_used:
                pines_texto += f"\n[Fuente: {', '.join(sources_used)}]"
            
            conn.execute('''
                INSERT INTO transacciones (usuario_id, numero_control, pin, transaccion_id, monto)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, numero_control, pines_texto, transaccion_id, monto_transaccion))
            
            # Limitar transacciones a 20 por usuario
            conn.execute('''
                DELETE FROM transacciones 
                WHERE usuario_id = ? AND id NOT IN (
                    SELECT id FROM transacciones 
                    WHERE usuario_id = ? 
                    ORDER BY fecha DESC 
                    LIMIT 20
                )
            ''', (user_id, user_id))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            flash('Error al procesar la transacción. Intente nuevamente.', 'error')
            return redirect('/juego/freefire_latam')
        finally:
            conn.close()
        
        # Actualizar saldo en sesión solo si no es admin
        if not is_admin:
            session['saldo'] = saldo_actual - precio_total
        
        # Guardar datos de la compra en la sesión para mostrar después del redirect
        if cantidad == 1:
            # Para un solo pin
            session['compra_exitosa'] = {
                'paquete_nombre': paquete_nombre,
                'monto_compra': precio_total,
                'numero_control': numero_control,
                'pin': pines_codigos[0],
                'transaccion_id': transaccion_id,
                'cantidad_comprada': cantidad,
                'source': sources_used[0] if sources_used else 'local_stock'
            }
        else:
            # Para múltiples pines
            session['compra_exitosa'] = {
                'paquete_nombre': paquete_nombre,
                'monto_compra': precio_total,
                'numero_control': numero_control,
                'pines_list': pines_codigos,
                'transaccion_id': transaccion_id,
                'cantidad_comprada': cantidad,
                'sources_used': sources_used
            }
        
        # Redirect para evitar reenvío del formulario (patrón POST-Redirect-GET)
        return redirect('/juego/freefire_latam?compra=exitosa')
        
    except Exception as e:
        flash(f'Error inesperado al procesar la compra: {str(e)}', 'error')
        return redirect('/juego/freefire_latam')

@app.route('/juego/freefire_latam')
def freefire_latam():
    if 'usuario' not in session:
        return redirect('/auth')
    
    # Actualizar saldo desde la base de datos
    user_id = session.get('user_db_id')
    if user_id:
        conn = get_db_connection()
        user = conn.execute('SELECT saldo FROM usuarios WHERE id = ?', (user_id,)).fetchone()
        if user:
            session['saldo'] = user['saldo']
        conn.close()
    
    # Obtener stock combinado (local + API externa)
    pin_manager = create_pin_manager(DATABASE)
    stock = {}
    
    # Verificar stock combinado para cada paquete
    for monto_id in range(1, 10):
        stock_check = pin_manager.check_combined_stock(monto_id)
        stock[monto_id] = {
            'local': stock_check.get('local_stock', 0),
            'external_available': stock_check.get('external_available', False),
            'total_available': stock_check.get('total_available', False),
            'message': stock_check.get('message', 'Sin información')
        }
    
    # Obtener precios dinámicos
    prices = get_package_info_with_prices()
    
    # Verificar si hay una compra exitosa para mostrar (solo una vez)
    compra_exitosa = False
    compra_data = {}
    
    # Solo mostrar compra exitosa si viene del redirect POST y hay datos en sesión
    if request.args.get('compra') == 'exitosa' and 'compra_exitosa' in session:
        compra_exitosa = True
        compra_data = session.pop('compra_exitosa')  # Remover después de usar para evitar mostrar de nuevo
    
    return render_template('freefire_latam.html', 
                         user_id=session.get('id', '00000'),
                         balance=session.get('saldo', 0),
                         stock=stock,
                         prices=prices,
                         compra_exitosa=compra_exitosa,
                         **compra_data)  # Desempaquetar los datos de la compra

# Rutas para Blood Striker
@app.route('/juego/bloodstriker')
def bloodstriker():
    if 'usuario' not in session:
        return redirect('/auth')
    
    # Actualizar saldo desde la base de datos
    user_id = session.get('user_db_id')
    if user_id:
        conn = get_db_connection()
        user = conn.execute('SELECT saldo FROM usuarios WHERE id = ?', (user_id,)).fetchone()
        if user:
            session['saldo'] = user['saldo']
        conn.close()
    
    # Obtener precios dinámicos de Blood Striker
    prices = get_bloodstriker_prices()
    
    # Verificar si hay una compra exitosa para mostrar (solo una vez)
    compra_exitosa = False
    compra_data = {}
    
    # Solo mostrar compra exitosa si viene del redirect POST y hay datos en sesión
    if request.args.get('compra') == 'exitosa' and 'compra_bloodstriker_exitosa' in session:
        compra_exitosa = True
        compra_data = session.pop('compra_bloodstriker_exitosa')  # Remover después de usar
    
    return render_template('bloodstriker.html', 
                         user_id=session.get('id', '00000'),
                         balance=session.get('saldo', 0),
                         prices=prices,
                         compra_exitosa=compra_exitosa,
                         **compra_data)

@app.route('/validar/bloodstriker', methods=['POST'])
def validar_bloodstriker():
    if 'usuario' not in session:
        return redirect('/auth')
    
    package_id = request.form.get('monto')
    player_id = request.form.get('player_id')
    
    if not package_id or not player_id:
        flash('Por favor complete todos los campos', 'error')
        return redirect('/juego/bloodstriker')
    
    package_id = int(package_id)
    user_id = session.get('user_db_id')
    is_admin = session.get('is_admin', False)
    
    # Obtener precio dinámico de la base de datos
    precio = get_bloodstriker_price_by_id(package_id)
    
    # Obtener información del paquete
    packages_info = get_bloodstriker_prices()
    package_info = packages_info.get(package_id, {})
    
    paquete_nombre = f"{package_info.get('nombre', 'Paquete')} / ${precio:.2f}"
    
    if precio == 0:
        flash('Paquete no encontrado o inactivo', 'error')
        return redirect('/juego/bloodstriker')
    
    saldo_actual = session.get('saldo', 0)
    
    # Solo verificar saldo para usuarios normales, admin puede comprar sin saldo
    if not is_admin and saldo_actual < precio:
        flash(f'Saldo insuficiente. Necesitas ${precio:.2f} pero tienes ${saldo_actual:.2f}', 'error')
        return redirect('/juego/bloodstriker')
    
    # Procesar la compra (crear transacción pendiente)
    try:
        # Solo descontar saldo si no es admin
        if not is_admin:
            conn = get_db_connection()
            conn.execute('UPDATE usuarios SET saldo = saldo - ? WHERE id = ?', (precio, user_id))
            conn.commit()
            conn.close()
            session['saldo'] = saldo_actual - precio
        
        # Crear transacción pendiente
        transaction_data = create_bloodstriker_transaction(user_id, player_id, package_id, precio)
        
        # Obtener datos del usuario para la notificación
        conn = get_db_connection()
        user_data = conn.execute('''
            SELECT nombre, apellido, correo FROM usuarios WHERE id = ?
        ''', (user_id,)).fetchone()
        conn.close()
        
        # Enviar notificación por correo al admin (solo si no es admin quien hace la compra)
        if not is_admin and user_data:
            notification_data = {
                'nombre': user_data['nombre'],
                'apellido': user_data['apellido'],
                'correo': user_data['correo'],
                'player_id': player_id,
                'paquete_nombre': package_info.get('nombre', 'Paquete desconocido'),
                'precio': precio,
                'numero_control': transaction_data['numero_control'],
                'transaccion_id': transaction_data['transaccion_id'],
                'fecha': convert_to_venezuela_time(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            }
            send_bloodstriker_notification(notification_data)
        
        # Guardar datos de la compra en la sesión para mostrar después del redirect
        session['compra_bloodstriker_exitosa'] = {
            'paquete_nombre': paquete_nombre,
            'monto_compra': precio,
            'numero_control': transaction_data['numero_control'],
            'transaccion_id': transaction_data['transaccion_id'],
            'player_id': player_id,
            'estado': 'pendiente'
        }
        
        # Redirect para evitar reenvío del formulario
        return redirect('/juego/bloodstriker?compra=exitosa')
        
    except Exception as e:
        flash('Error al procesar la compra. Intente nuevamente.', 'error')
        return redirect('/juego/bloodstriker')

# Rutas de administrador para Blood Striker
@app.route('/admin/bloodstriker_transactions')
def admin_bloodstriker_transactions():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    pending_transactions = get_pending_bloodstriker_transactions()
    return render_template('admin_bloodstriker.html', transactions=pending_transactions)

@app.route('/admin/bloodstriker_approve', methods=['POST'])
def admin_bloodstriker_approve():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    transaction_id = request.form.get('transaction_id')
    notas = request.form.get('notas', '')
    
    if transaction_id:
        update_bloodstriker_transaction_status(int(transaction_id), 'aprobado', session.get('user_db_id'), notas)
        flash('Transacción aprobada exitosamente', 'success')
    else:
        flash('ID de transacción inválido', 'error')
    
    return redirect('/admin/bloodstriker_transactions')

@app.route('/admin/bloodstriker_reject', methods=['POST'])
def admin_bloodstriker_reject():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    transaction_id = request.form.get('transaction_id')
    notas = request.form.get('notas', '')
    
    if transaction_id:
        # Obtener información de la transacción para devolver el saldo
        conn = get_db_connection()
        transaction = conn.execute('''
            SELECT usuario_id, monto FROM transacciones_bloodstriker 
            WHERE id = ?
        ''', (transaction_id,)).fetchone()
        
        if transaction:
            # Devolver saldo al usuario (monto es negativo, así que sumamos el valor absoluto)
            conn.execute('UPDATE usuarios SET saldo = saldo + ? WHERE id = ?', 
                        (abs(transaction['monto']), transaction['usuario_id']))
            conn.commit()
        conn.close()
        
        # Actualizar estado de la transacción
        update_bloodstriker_transaction_status(int(transaction_id), 'rechazado', session.get('user_db_id'), notas)
        flash('Transacción rechazada y saldo devuelto al usuario', 'success')
    else:
        flash('ID de transacción inválido', 'error')
    
    return redirect('/admin/bloodstriker_transactions')

@app.route('/admin/update_bloodstriker_price', methods=['POST'])
def admin_update_bloodstriker_price():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    package_id = request.form.get('package_id')
    new_price = request.form.get('new_price')
    
    if not package_id or not new_price:
        flash('Datos inválidos para actualizar precio', 'error')
        return redirect('/admin')
    
    try:
        new_price = float(new_price)
        if new_price < 0:
            flash('El precio no puede ser negativo', 'error')
            return redirect('/admin')
        
        # Obtener información del paquete antes de actualizar
        conn = get_db_connection()
        package = conn.execute('SELECT nombre FROM precios_bloodstriker WHERE id = ?', (package_id,)).fetchone()
        conn.close()
        
        if not package:
            flash('Paquete no encontrado', 'error')
            return redirect('/admin')
        
        # Actualizar precio
        update_bloodstriker_price(int(package_id), new_price)
        flash(f'Precio de Blood Striker actualizado exitosamente para {package["nombre"]}: ${new_price:.2f}', 'success')
        
    except ValueError:
        flash('Precio inválido. Debe ser un número válido.', 'error')
    except Exception as e:
        flash(f'Error al actualizar precio: {str(e)}', 'error')
    
    return redirect('/admin')

@app.route('/admin/approve_bloodstriker/<int:transaction_id>', methods=['POST'])
def approve_bloodstriker_transaction(transaction_id):
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    try:
        # Obtener información de la transacción de Blood Striker
        conn = get_db_connection()
        bs_transaction = conn.execute('''
            SELECT bs.*, u.nombre, u.apellido, p.nombre as paquete_nombre
            FROM transacciones_bloodstriker bs
            JOIN usuarios u ON bs.usuario_id = u.id
            JOIN precios_bloodstriker p ON bs.paquete_id = p.id
            WHERE bs.id = ?
        ''', (transaction_id,)).fetchone()
        
        if bs_transaction:
            # Crear transacción normal en el historial
            conn.execute('''
                INSERT INTO transacciones (usuario_id, numero_control, pin, transaccion_id, monto)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                bs_transaction['usuario_id'],
                bs_transaction['numero_control'],
                f"ID: {bs_transaction['player_id']}",
                bs_transaction['transaccion_id'],
                bs_transaction['monto']
            ))
            
            # Limitar transacciones a 20 por usuario
            conn.execute('''
                DELETE FROM transacciones 
                WHERE usuario_id = ? AND id NOT IN (
                    SELECT id FROM transacciones 
                    WHERE usuario_id = ? 
                    ORDER BY fecha DESC 
                    LIMIT 20
                )
            ''', (bs_transaction['usuario_id'], bs_transaction['usuario_id']))
            
            conn.commit()
        
        conn.close()
        
        # Actualizar estado de la transacción de Blood Striker
        update_bloodstriker_transaction_status(transaction_id, 'aprobado', session.get('user_db_id'))
        flash('Transacción aprobada exitosamente', 'success')
    except Exception as e:
        flash(f'Error al aprobar transacción: {str(e)}', 'error')
    
    return redirect('/')

@app.route('/admin/reject_bloodstriker/<int:transaction_id>', methods=['POST'])
def reject_bloodstriker_transaction(transaction_id):
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    try:
        # Obtener información de la transacción para devolver el saldo
        conn = get_db_connection()
        transaction = conn.execute('''
            SELECT usuario_id, monto FROM transacciones_bloodstriker 
            WHERE id = ?
        ''', (transaction_id,)).fetchone()
        
        if transaction:
            # Devolver saldo al usuario (monto es negativo, así que sumamos el valor absoluto)
            conn.execute('UPDATE usuarios SET saldo = saldo + ? WHERE id = ?', 
                        (abs(transaction['monto']), transaction['usuario_id']))
            conn.commit()
        conn.close()
        
        # Actualizar estado de la transacción
        update_bloodstriker_transaction_status(transaction_id, 'rechazado', session.get('user_db_id'))
        flash('Transacción rechazada y saldo devuelto al usuario', 'success')
    except Exception as e:
        flash(f'Error al rechazar transacción: {str(e)}', 'error')
    
    return redirect('/')

# Rutas de administración para API externa
@app.route('/admin/test_external_api', methods=['POST'])
def admin_test_external_api():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    try:
        pin_manager = create_pin_manager(DATABASE)
        result = pin_manager.test_external_api()
        
        if result.get('status') == 'success':
            flash(f'✅ API Externa: {result.get("message")}', 'success')
        else:
            flash(f'❌ API Externa: {result.get("message")}', 'error')
    except Exception as e:
        flash(f'Error al probar API externa: {str(e)}', 'error')
    
    return redirect('/admin')

@app.route('/admin/request_external_pin', methods=['POST'])
def admin_request_external_pin():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    monto_id = request.form.get('monto_id')
    
    if not monto_id:
        flash('Por favor selecciona un monto válido', 'error')
        return redirect('/admin')
    
    try:
        monto_id = int(monto_id)
        if monto_id < 1 or monto_id > 9:
            flash('Monto ID debe estar entre 1 y 9', 'error')
            return redirect('/admin')
        
        inefable_client = get_inefable_client()
        result = inefable_client.request_pin(monto_id)
        
        if result.get('status') == 'success':
            pin_code = result.get('pin_code')
            
            # Agregar el pin obtenido al stock local
            pin_manager = create_pin_manager(DATABASE)
            success, message = pin_manager.add_local_pin(monto_id, pin_code, source='inefable_api_manual')
            
            if success:
                # Obtener información del paquete
                packages_info = get_package_info_with_prices()
                package_info = packages_info.get(monto_id, {})
                paquete_nombre = package_info.get('nombre', f'Paquete {monto_id}')
                
                flash(f'✅ Pin obtenido de API externa y agregado al stock: {paquete_nombre}', 'success')
            else:
                flash(f'Pin obtenido pero error al agregar al stock: {message}', 'warning')
        else:
            flash(f'❌ Error al obtener pin de API externa: {result.get("message", "Error desconocido")}', 'error')
            
    except ValueError:
        flash('Monto ID debe ser un número válido', 'error')
    except Exception as e:
        flash(f'Error inesperado: {str(e)}', 'error')
    
    return redirect('/admin')

@app.route('/admin/get_api_status', methods=['GET'])
def admin_get_api_status():
    if not session.get('is_admin'):
        return {'status': 'error', 'message': 'Acceso denegado'}
    
    try:
        pin_manager = create_pin_manager(DATABASE)
        status = pin_manager.get_stock_status()
        return status
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/auth')

if __name__ == '__main__':
    app.run(debug=True)
