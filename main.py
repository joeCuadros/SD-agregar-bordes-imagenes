import imghdr, base64, re
from io import BytesIO
from flask import Flask, render_template, request, send_from_directory, url_for, session, redirect, flash
from flask_socketio import SocketIO, disconnect, emit
from werkzeug.security import check_password_hash #,generate_password_hash, 
from PIL import Image, ImageOps
# Configuracion del servidor
app = Flask(__name__)
app.config['UPLOAD_EXTENSIONS'] = ['.jpg', '.png',]
app.secret_key = 'qpTI!vMBI1FpkvEkQ4*X^afdcSu0zhviasfas'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True #no se puede leer por javascript
)
socketio = SocketIO(app)
MAX_FILE_SIZE = 2 * 1024 * 1024 # max 2 MB
socketio = SocketIO(app, max_http_buffer_size=MAX_FILE_SIZE) 

# usuario con contraseñas encriptadas
users = {
    'joe': {'id': 1,'password': 'scrypt:32768:8:1$YuLFzGcwJVbaou7G$2c9c2f21d858a2121d10644537c872c5efbe9d39825e6139fc3e6ebccd668a770242fd42a872cce9fc5148657d532991ecedf497ca79339ddbf5403c4df2f28d'},
    'misael': {'id': 2,'password': 'scrypt:32768:8:1$LPOUjOJrmGFshjyD$724a223d766c805912eee91f02b24214c6fd427d9645fae3bbb857f2e67aa3badd1e6b23f5c8073ee5839f17dd0307a40e062864449edbd0e6ef379aadb94dba'},
    'sebastian': {'id': 3,'password': 'scrypt:32768:8:1$x81vogaNFuwwWboO$ec5c0a2a8c1a6f3362ec0faf2347f1885b99584d0265eeadfce52df5c401cc699f5e5a9536ec18c3da6281238e79a29e5b261675c9d52d99e765ff6d9064040a'},
    'rodrigo': {'id': 4,'password': 'scrypt:32768:8:1$sXzsAW3BMK2QRA5F$23be256b413782396d45f28ca790eadf54474f21a31a8fcf4467c7b738e09a4bffc75b2ce333f51ad8b7800e307a85e5a371efe5a4d636b96021b5eed5b8e02f'},
}

# Decorador para proteger las rutas privadas
def login_required(f):
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__ 
    return wrap

# retorna None si no es imagen
def validate_image(stream):
    header = stream.read(512)
    stream.seek(0) 
    format = imghdr.what(None, header) 
    if not format:
        return None
    return '.' + (format if format != 'jpeg' else 'jpg')
# convertir color hexadecimal a rgb
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        raise ValueError("Formato de color inválido")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
#### VISTAS
# login 
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users:
            # Verificar la contraseña
            if check_password_hash(users[username]['password'],password):
                user_id = users[username]['id']
                session['user_id'] = {"id": user_id, "username": username}
                return redirect(url_for('index'))
        
        flash('Credenciales incorrectas','danger') # mandar error
        return render_template('login.html',username = request.form['username'])

    return render_template('login.html')

# cerrar sesion
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logout successful.','success') # mandar notificacion
    return redirect(url_for('login')) 

# vista principal
@app.route('/')
@login_required
def index():
    return render_template('index.html',MAX_FILE_SIZE=MAX_FILE_SIZE)


#subida de imagenes
@socketio.on('upload_image')
def upload_image(data):
    # evitar el ingreso de usuario no ingresado
    if 'user_id' not in session:
        emit('error', 'No autorizado. Inicia sesion.')
        disconnect()
        return
    # obtener la imagen
    image_base64 = data.get('image')
    color_hex = data.get('border_color') or '#000000'
    border_width_str = data.get('border_width') or 10

     # Validar y convertir color
    try:
        border_color = hex_to_rgb(color_hex)
    except ValueError:
        emit('image_error', {'message': 'El color de borde es invalido. Debe ser un valor hexadecimal como #ff0000.'})
        emit('alert_server', {'type':'danger','message': 'El color de borde es invalido. Debe ser un valor hexadecimal como #ff0000.'})
        return
    # Validar ancho de borde
    try:
        border_width = int(border_width_str)
        if border_width < 0:
            raise ValueError
    except ValueError:
        emit('image_error', {'message': 'Ancho de borde invalido. Debe ser un número entero positivo.'})
        emit('alert_server', {'type':'danger','message': 'ncho de borde invalido. Debe ser un número entero positivo.'})
        return
    
    if image_base64:
        try:
            header, encoded = re.split(",", image_base64) #separar encabezado
            image_data = base64.b64decode(encoded) #decodficar a binario

            stream = BytesIO(image_data)
            #validar si es imagen
            file_ext = validate_image(stream)
            if file_ext not in app.config['UPLOAD_EXTENSIONS']:
                emit('image_error', {'message': 'La imagen no es válida o el formato no está permitido.'})
                return

            img = Image.open(stream) #leer la imagen
            img_with_border = ImageOps.expand(img, border=border_width, fill=border_color) 

            # Guardar la imagen procesada en un BytesIO para convertirla de nuevo a base64
            output_stream = BytesIO()
            img_with_border.save(output_stream, format=img.format if img.format else 'JPEG')
            processed_image_data = output_stream.getvalue()

            processed_encoded = base64.b64encode(processed_image_data).decode('utf-8') # Convertir de nuevo a base64
            format_ext = file_ext[1:].lower() 

            original_image_url = f"data:image/{format_ext};base64,{encoded}"
            processed_image_url = f"data:image/{format_ext};base64,{processed_encoded}"

            emit('image_processed', {
                'before': original_image_url,
                'after': processed_image_url
            })

        except Exception as e:
            emit('image_error', {'message': 'Error al procesar la imagen.'})
            return

    else:
        emit('image_error', {'message': 'No se recibió la imagen.'})


if __name__ == '__main__':
    socketio.run(app,host="0.0.0.0",port=4000, debug=True)