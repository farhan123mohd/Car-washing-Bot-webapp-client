from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit, join_room
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from config import SECRET_KEY, UPLOAD_FOLDER
from database import get_connection
from flask import Response
from camera import start_camera, stop_camera, generate_frames

user_sessions = {}

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

socketio = SocketIO(app, cors_allowed_origins="*")

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['full_name']
        mobile = request.form['mobile']
        email = request.form['email']
        password = request.form['password']
        con = get_connection()
        cur = con.cursor()
        cur.execute("INSERT INTO users (full_name, mobile, email, password) VALUES (%s, %s, %s, %s)",
                    (name, mobile, email, password))
        con.commit()
        con.close()
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/start_stream')
def start_stream():
    if 'admin' not in session:
        return "Unauthorized", 403
    start_camera()
    return "Streaming started."

@app.route('/stop_stream')
def stop_stream():
    if 'admin' not in session:
        return "Unauthorized", 403
    stop_camera()
    return "Streaming stopped."

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        con = get_connection()
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s AND password=%s", (email, password))
        user = cur.fetchone()
        con.close()
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials.')
    return render_template('login.html')

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials.')
    return render_template('admin_login.html')

@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    con = get_connection()
    cur = con.cursor()

    # Delete related bookings first
    cur.execute("DELETE FROM bookings WHERE user_id = %s", (user_id,))
# Then delete the user
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


    
    con.commit()
    cur.close()
    con.close()

    session.clear()
    flash("Your account has been deleted.", "info")
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT date_time, service_center, status, slot FROM bookings WHERE user_id = %s ORDER BY id DESC", (session['user_id'],))

    bookings = [{'date_time': row[0], 'service_center': row[1], 'status': row[2], 'slot': row[3]} for row in cur.fetchall()]


    cur.execute("SELECT COUNT(*) FROM bookings WHERE user_id = %s", (session['user_id'],))
    booking_count = cur.fetchone()[0]
    is_premium = booking_count >= 3


    con.close()
    return render_template('dashboard.html', user_name=session['user_name'], bookings=bookings)

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    
    con = get_connection()
    cur = con.cursor()
    # Get all bookings with user info
    cur.execute("""SELECT b.id, u.id, u.full_name, u.email, b.date_time, b.service_center, b.status, b.image_filename 
               FROM bookings b JOIN users u ON b.user_id = u.id 
               ORDER BY b.id DESC""")

    raw_bookings = cur.fetchall()
    
    # Collect bookings and determine premium status for each user
    bookings = []
    for row in raw_bookings:
        user_id = row[1]
        cur.execute("SELECT COUNT(*) FROM bookings WHERE user_id = %s", (user_id,))
        booking_count = cur.fetchone()[0]
        is_premium = booking_count >= 3
        bookings.append({
            'id': row[0],
            'user_id': user_id,
            'full_name': row[2],
            'email': row[3],
            'date_time': row[4],
            'service_center': row[5],
            'status': row[6],
            'image': row[7],
            'is_premium': is_premium
        })

    con.close()
    return render_template('admin_dashboard.html', bookings=bookings)


@app.route('/upload_status/<int:booking_id>', methods=['GET', 'POST'])
def upload_status(booking_id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        status = request.form.get('status')
        if 'image' not in request.files:
            return "No image uploaded", 400
        image = request.files['image']
        if image.filename == '':
            return "No selected file", 400

        filename = secure_filename(image.filename)
        upload_folder = os.path.join(app.root_path, 'static', 'uploads')  # static/uploads
        os.makedirs(upload_folder, exist_ok=True)  # create folder if doesn't exist

        filepath = os.path.join(upload_folder, filename)
        image.save(filepath)

        # Save filename to DB
        con = get_connection()
        cur = con.cursor()
        cur.execute(
            "UPDATE bookings SET status = %s, image_filename = %s WHERE id = %s",
            (status, filename, booking_id)
        )
        con.commit()
        con.close()

        return redirect(url_for('admin_dashboard'))

    return render_template('upload_status.html', booking_id=booking_id)


@app.route('/chatbot')
def chatbot_page():
    user_id = session.get('user_id')
    user_name = session.get('user_name')
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM bookings WHERE user_id = %s", (session['user_id'],))
    booking_count = cur.fetchone()[0]
    is_premium = booking_count >= 3

    return render_template('chatbot.html', user_id=user_id, user_name=user_name)


@app.route('/pay', methods=['GET', 'POST'])
def pay():
    if request.method == 'POST':
        flash("Payment successful! Booking complete.")
        return redirect(url_for('dashboard'))
    return render_template('payment.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# -------- Chatbot Logic -------- #

def get_available_slots():
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT slot_time FROM slots WHERE status='available'")
    slots = [row[0] for row in cur.fetchall()]
    con.close()
    return slots

@socketio.on("init")
def handle_init(data):
    key = str(data.get("user_id") or request.sid)
    user_sessions[key] = {"step": 1, "user_id": session.get("user_id")}
    join_room(key)
    emit("response", "     Hello! I’m your Car Wash Assistant. Type 'hello' to begin..", to=key)

@socketio.on("message")
def handle_message(msg):
    key = str(session.get("user_id") or request.sid)
    msg = msg.lower().strip()
    user = user_sessions.get(key, {})
    logged_user_id = session.get("user_id")

    # Greet & check membership only at the beginning
    if msg in ["hello", "hi", "hey"]:
        if logged_user_id:
            con = get_connection()
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM bookings WHERE user_id = %s", (logged_user_id,))
            booking_count = cur.fetchone()[0]
            con.close()

            if booking_count >= 3:
                user['is_premium'] = True
                emit("response", "You're a Premium Member! 🎉 Your washes get faster service priority.")
            else:
                user['is_premium'] = False
                emit("response", "Regular member. Keep booking to unlock Premium status!")

        emit("response", "Hello! What type of car do you have? (Hybrid, Electrical, Engine)")
        user_sessions[key] = user
        return

    # Handle car type
    if msg in ["hybrid", "electrical", "engine"]:
        user['car_type'] = msg
        slots = get_available_slots()
        if slots:
            if user.get('is_premium'):
                emit("response", f"🚗 Premium Access: Available slots: {', '.join(slots)}.")
            else:
                emit("response", f"Available slots: {', '.join(slots)}.")
        else:
            emit("response", "Sorry, no slots available.")
        user_sessions[key] = user
        return

    # Handle slot input
    elif ":" in msg:
        user['slot'] = msg
        if user.get('is_premium'):
            emit("response", "Great! As a Premium member, your preferred time will be prioritized. 💎")
        emit("response", "Please enter your preferred service center location. (Ernakulam, Thalassery, Vadakara, Mattancherry)")
        user_sessions[key] = user
        return

    # Handle location input
    elif 'slot' in user and 'location' not in user:
        entered_location = msg.title()

        con = get_connection()
        cur = con.cursor()
        cur.execute("SELECT DISTINCT service_center FROM bookings")
        valid_centers = [row[0].lower() for row in cur.fetchall() if row[0] is not None]
        con.close()

        if entered_location.lower() in valid_centers:
            user['location'] = entered_location
            emit("response", f"Confirming booking at {user['location']} on slot {user['slot']} for your {user['car_type']} car.")
            if user.get('is_premium'):
                emit("response", "🚀 Fast-track booking enabled for Premium Member.")
            emit("response", "Proceed to payment?")
            user_sessions[key] = user
        else:
            emit("response", "⚠️ Service center not found. Please enter a valid location with an available service center.")



    # Proceed to payment
    elif msg in ["yes", "y", "yaah"] and 'location' in user:
        emit("response", "Redirecting to payment demo page...")
        emit("redirect", "/pay")
        return

    # Cancel booking
    elif msg in ["no", "n", "cancel"]:
        emit("response", "Booking cancelled. Start again with 'Hi'.")
        user_sessions.pop(key, None)
        return

    # Payment confirmation
    elif msg == "paid":
        if not logged_user_id:
            emit("response", "Please log in to complete booking.")
            return

        con = get_connection()
        cur = con.cursor()
        cur.execute("""INSERT INTO bookings (user_id, car_type, slot, location, date_time, service_center, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (logged_user_id,
             user.get('car_type'),
             user.get('slot'),
             user.get('location'),
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             user.get('location'),
             'Booked'))

        con.commit()
        con.close()

        emit("response", "✅ Booking completed successfully!")
        user_sessions.pop(key, None)
        return

    else:
        emit("response", "Sorry, I didn’t understand. Please start again with 'Hi'.")

# -------- Run -------- #

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
