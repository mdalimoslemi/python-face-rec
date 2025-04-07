from flask import Flask, render_template, request, redirect, url_for, send_file, session
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
import os
import cv2
import numpy as np
import logging
from logging.handlers import RotatingFileHandler
from PIL import Image  # Add this import for image resizing

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['PROCESSED_FOLDER'] = 'static/processed'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}

# Security Configurations
app.config['SECRET_KEY'] = os.urandom(32)  # Generate a secure random key
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize security extensions
csrf = CSRFProtect(app)
talisman = Talisman(
    app,
    content_security_policy={
        'default-src': "'self'",
        'img-src': "'self' data:",
        'script-src': "'self' 'unsafe-inline' unpkg.com",
        'style-src': "'self' 'unsafe-inline' unpkg.com fonts.googleapis.com",
        'font-src': "'self' fonts.gstatic.com",
    },
    force_https=True  # Remove in development if needed
)

# Create folders if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROCESSED_FOLDER'], exist_ok=True)

# Configure logging
if not app.debug:
    handler = RotatingFileHandler('error.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def detect_faces(image_path):
    # Load the image
    image = cv2.imread(image_path)
    
    # Convert to grayscale for face detection
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Load the face cascade classifier
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    
    # Detect faces with adjusted parameters
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,  # Increased from 1.1 for better accuracy
        minNeighbors=8,   # Increased from 5 to reduce false positives
        minSize=(40, 40), # Increased minimum face size
        flags=cv2.CASCADE_SCALE_IMAGE
    )
    
    # Sort faces by size (area) to prioritize more prominent faces
    faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
    
    # Draw rectangles only for faces that meet certain criteria
    valid_faces = 0
    for (x, y, w, h) in faces:
        # Calculate face aspect ratio (should be roughly square for real faces)
        aspect_ratio = float(w) / h
        if 0.8 <= aspect_ratio <= 1.2:  # Face should be roughly square
            cv2.rectangle(image, (x, y), (x+w, y+h), (0, 255, 0), 5)
            valid_faces += 1
    
    return image, valid_faces

def resize_image(image_path, max_width=1024, max_height=1024):
    """Resize the image to reduce memory usage."""
    with Image.open(image_path) as img:
        img.thumbnail((max_width, max_height))
        img.save(image_path)

class UploadForm(FlaskForm):
    pass

@app.route('/', methods=['GET'])
def index():
    form = UploadForm()
    return render_template('index.html', form=form)

@app.route('/favicon.ico')
def favicon():
    """Serve a placeholder favicon."""
    return send_file('static/favicon.ico')

@app.route('/upload', methods=['POST'])
def upload_file():
    form = UploadForm()
    if not form.validate_on_submit():
        return render_template('index.html', form=form, message='CSRF validation failed')
    
    if 'file' not in request.files:
        return render_template('index.html', form=form, message='No file part')
    
    file = request.files['file']
    
    if file.filename == '':
        return render_template('index.html', form=form, message='No selected file')
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(file_path)
            resize_image(file_path)  # Resize the image before processing
        except Exception as e:
            return render_template('index.html', form=form, message=f'Error saving file: {str(e)}')
        
        # Process the image to detect faces
        try:
            processed_image, face_count = detect_faces(file_path)
            
            # Save the processed image
            processed_filename = f"processed_{filename}"
            processed_path = os.path.join(app.config['PROCESSED_FOLDER'], processed_filename)
            cv2.imwrite(processed_path, processed_image)
            
            return render_template('result.html', 
                                  original_image=f"uploads/{filename}",
                                  processed_image=f"processed/{processed_filename}",
                                  face_count=face_count,
                                  message='File uploaded and processed successfully!')
        except Exception as e:
            return render_template('index.html', form=form, message=f'Error processing image: {str(e)}')
    
    return render_template('index.html', form=form, message='Allowed file types are png, jpg, jpeg')

# Error handlers
@app.errorhandler(413)
def too_large(e):
    return "File is too large", 413

@app.errorhandler(429)
def ratelimit_handler(e):
    return "Too many requests. Please try again later.", 429

@app.errorhandler(500)
def internal_error(e):
    app.logger.error(f"Server Error: {e}, Path: {request.path}")
    return "Internal Server Error", 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    app.logger.error(f"Unhandled Exception: {e}, Path: {request.path}")
    return "Something went wrong", 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
