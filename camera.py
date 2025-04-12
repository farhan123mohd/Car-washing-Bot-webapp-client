import cv2

camera = None

def start_camera():
    global camera
    if camera is None:
        camera = cv2.VideoCapture(0)

def stop_camera():
    global camera
    if camera is not None:
        camera.release()
        camera = None

def generate_frames():
    global camera
    while camera and camera.isOpened():
        success, frame = camera.read()
        if not success:
            break
        else:
            _, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
