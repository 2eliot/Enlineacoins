from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import hashlib
import os
import secrets
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash

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

def get_user_transactions(user_id, is_admin=False):
    """Obtiene las transacciones de un usuario con información del paquete"""
    conn = get_db_connection()
    
    if is_admin:
        # Admin ve todas las transacciones de todos los usuarios
        transactions = conn.execute('''
            SELECT t.*, u.nombre, u.apellido
            FROM transacciones t
            JOIN usuarios u ON t.usuario_id = u.id
            ORDER BY t.fecha DESC
        ''').fetchall()
    else:
        # Usuario normal ve solo sus transacciones
        transactions = conn.execute('''
            SELECT t.*, u.nombre, u.apellido
            FROM transacciones t
            JOIN usuarios u ON t.usuario_id = u.id
            WHERE t.usuario_id = ? 
            ORDER BY t.fecha DESC
        ''', (user_id,)).fetchall()
    
    # Agregar información del paquete basado en el monto
    transactions_with_package = []
    for transaction in transactions:
        transaction_dict = dict(transaction)
        monto = abs(transaction['monto'])  # Usar valor absoluto para comparar
        
        # Determinar el paquete basado en el monto
        if monto == 0.66:
            transaction_dict['paquete'] = "110 💎"
        elif monto == 2.25:
            transaction_dict['paquete'] = "341 💎"
        elif monto == 3.66:
            transaction_dict['paquete'] = "572 💎"
        elif monto == 7.10:
            # Puede ser 1.166 💎 o Tarjeta mensual
            if "FF-" in transaction['transaccion_id']:
                transaction_dict['paquete'] = "1.166 💎"
            else:
                transaction_dict['paquete'] = "Tarjeta mensual"
        elif monto == 14.44:
            transaction_dict['paquete'] = "2.376 💎"
        elif monto == 33.10:
            transaction_dict['paquete'] = "6.138 💎"
        elif monto == 0.50:
            transaction_dict['paquete'] = "Tarjeta básica"
        elif monto == 1.55:
            transaction_dict['paquete'] = "Tarjeta semanal"
        else:
            transaction_dict['paquete'] = "Paquete desconocido"
        
        transactions_with_package.append(transaction_dict)
    
    conn.close()
    return transactions_with_package

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
    
    user_id = session.get('id', '00000')
    transactions = []
    is_admin = session.get('is_admin', False)
    
    if is_admin:
        # Admin ve todas las transacciones de todos los usuarios
        transactions = get_user_transactions(None, is_admin=True)
    else:
        # Usuario normal ve solo sus transacciones
        if 'user_db_id' in session:
            conn = get_db_connection()
            user = conn.execute('SELECT saldo FROM usuarios WHERE id = ?', (session['user_db_id'],)).fetchone()
            if user:
                session['saldo'] = user['saldo']
            conn.close()
            transactions = get_user_transactions(session['user_db_id'], is_admin=False)
    
    balance = session.get('saldo', 0)
    
    return render_template('index.html', user_id=user_id, balance=balance, transactions=transactions)

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

# Rutas de administrador
@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acceso denegado. Solo administradores.', 'error')
        return redirect('/auth')
    
    users = get_all_users()
    pin_stock = get_pin_stock()
    prices = get_all_prices()
    return render_template('admin.html', users=users, pin_stock=pin_stock, prices=prices)

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
    
    if len(pins_list) > 10:
        flash('Máximo 10 pines por lote. Se procesarán solo los primeros 10.', 'warning')
        pins_list = pins_list[:10]
    
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

@app.route('/juego/freefire_latam')
def freefire_latam():
    if 'usuario' not in session:
        return redirect('/auth')
    
    # Solo usuarios normales pueden acceder a juegos
    if session.get('is_admin'):
        flash('Los administradores no pueden acceder a juegos', 'error')
        return redirect('/')
    
    # Actualizar saldo desde la base de datos
    user_id = session.get('user_db_id')
    if user_id:
        conn = get_db_connection()
        user = conn.execute('SELECT saldo FROM usuarios WHERE id = ?', (user_id,)).fetchone()
        if user:
            session['saldo'] = user['saldo']
        conn.close()
    
    # Obtener stock de pines
    stock = get_pin_stock()
    
    # Obtener precios dinámicos
    prices = get_package_info_with_prices()
    
    return render_template('freefire_latam.html', 
                         user_id=session.get('id', '00000'),
                         balance=session.get('saldo', 0),
                         stock=stock,
                         prices=prices)

@app.route('/validar/freefire_latam', methods=['POST'])
def validar_freefire_latam():
    if 'usuario' not in session:
        return redirect('/auth')
    
    # Solo usuarios normales pueden hacer compras
    if session.get('is_admin'):
        flash('Los administradores no pueden realizar compras', 'error')
        return redirect('/')
    
    monto_id = request.form.get('monto')
    
    if not monto_id:
        flash('Por favor selecciona un paquete', 'error')
        return redirect('/juego/freefire_latam')
    
    monto_id = int(monto_id)
    user_id = session.get('user_db_id')
    
    # Verificar si hay stock disponible
    available_pin = get_available_pin(monto_id)
    if not available_pin:
        flash('No hay stock disponible para este paquete', 'error')
        return redirect('/juego/freefire_latam')
    
    # Obtener precio dinámico de la base de datos
    precio = get_price_by_id(monto_id)
    
    # Obtener información del paquete
    packages_info = get_package_info_with_prices()
    package_info = packages_info.get(monto_id, {})
    
    paquete_nombre = f"{package_info.get('nombre', 'Paquete')} / ${precio:.2f}"
    
    if precio == 0:
        flash('Paquete no encontrado o inactivo', 'error')
        return redirect('/juego/freefire_latam')
    saldo_actual = session.get('saldo', 0)
    
    # Verificar si tiene saldo suficiente
    if saldo_actual < precio:
        flash(f'Saldo insuficiente. Necesitas ${precio:.2f} pero tienes ${saldo_actual:.2f}', 'error')
        return redirect('/juego/freefire_latam')
    
    # Procesar la compra
    import random
    import string
    
    # Generar datos de la transacción
    numero_control = ''.join(random.choices(string.digits, k=10))
    transaccion_id = 'FF-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    # Obtener el PIN directamente (ya está en texto plano)
    pin_codigo = available_pin['pin_codigo']
    
    # Usar una sola conexión para todas las operaciones
    conn = get_db_connection()
    try:
        # Actualizar saldo del usuario
        conn.execute('UPDATE usuarios SET saldo = saldo - ? WHERE id = ?', (precio, user_id))
        
        # Eliminar el pin de la base de datos (ya no marcarlo como usado)
        conn.execute('DELETE FROM pines_freefire WHERE id = ?', (available_pin['id'],))
        
        # Registrar la transacción (guardar PIN desencriptado para el usuario)
        conn.execute('''
            INSERT INTO transacciones (usuario_id, numero_control, pin, transaccion_id, monto)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, numero_control, pin_codigo, transaccion_id, -precio))
        
        # Limitar transacciones a 20 por usuario - eliminar las más antiguas si hay más de 20
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
        flash('Error al procesar la compra. Intente nuevamente.', 'error')
        return redirect('/juego/freefire_latam')
    finally:
        conn.close()
    
    # Actualizar saldo en sesión
    session['saldo'] = saldo_actual - precio
    
    # Obtener stock actualizado
    stock = get_pin_stock()
    
    # Obtener precios dinámicos para el template
    prices = get_package_info_with_prices()
    
    # Mostrar los datos de la compra en la misma página
    return render_template('freefire_latam.html', 
                         user_id=session.get('id', '00000'),
                         balance=session.get('saldo', 0),
                         stock=stock,
                         prices=prices,
                         compra_exitosa=True,
                         paquete_nombre=paquete_nombre,
                         monto_compra=precio,
                         numero_control=numero_control,
                         pin=pin_codigo,
                         transaccion_id=transaccion_id)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/auth')

if __name__ == '__main__':
    app.run(debug=True)
