import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, make_response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///academy.db'
app.config['SECRET_KEY'] = 'super_secret_key_for_security'

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)
ADMIN_PASSWORD = "admin123"

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(50), nullable=False) # الصف الدراسي للطالب
    is_paid = db.Column(db.Boolean, default=False)
    receipt = db.Column(db.String(200), nullable=True)
    activation_date = db.Column(db.DateTime, nullable=True) 
    device_id = db.Column(db.String(100), nullable=True) # بصمة الجهاز المرتبط بالحساب

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    video_url = db.Column(db.String(500), nullable=False)
    grade = db.Column(db.String(50), nullable=False) # الصف الدراسي الخاص بالدرس

with app.app_context():
    db.create_all()

@app.context_processor
def inject_user():
    current_user = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
    return dict(current_user=current_user)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        new_name = request.form['name']
        new_phone = request.form['phone']
        new_password = request.form['password']
        new_grade = request.form['grade']
        
        new_user = User(name=new_name, phone=new_phone, password=new_password, grade=new_grade)
        db.session.add(new_user)
        db.session.commit()
        
        session['user_id'] = new_user.id
        return redirect(url_for('checkout'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_msg = None
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        user = User.query.filter_by(phone=phone, password=password).first()
        
        if user:
            # نظام قفل الجهاز (Device Binding)
            user_device = request.cookies.get('device_token')
            if not user_device:
                user_device = str(uuid.uuid4())
            
            if user.device_id and user.device_id != user_device:
                error_msg = "هذا الحساب مسجل بالفعل على جهاز آخر! لا يمكن فتح الحساب من جهازين. يرجى التواصل مع الإدارة لإعادة تعيين الجهاز."
            else:
                if not user.device_id:
                    user.device_id = user_device
                    db.session.commit()
                
                session['user_id'] = user.id
                resp = make_response(redirect(url_for('courses')))
                resp.set_cookie('device_token', user_device, max_age=60*60*24*365)
                return resp
        else:
            error_msg = "رقم الموبايل أو كلمة المرور غير صحيحة!"
            
    return render_template('login.html', error=error_msg)

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    current_user = User.query.get(session['user_id'])
    if current_user is None:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        file = request.files['receipt']
        if file:
            filename = f"user_{current_user.id}_{file.filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            current_user.receipt = filename
            db.session.commit()
            return render_template('success.html') 
            
    return render_template('checkout.html', user=current_user)

@app.route('/courses')
def courses():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    current_user = User.query.get(session['user_id'])
    if current_user is None:
        session.pop('user_id', None)
        return redirect(url_for('login'))
    
    if current_user.is_paid and current_user.activation_date:
        expiration_date = current_user.activation_date + timedelta(days=30)
        if datetime.utcnow() > expiration_date:
            current_user.is_paid = False 
            current_user.activation_date = None 
            current_user.receipt = None 
            db.session.commit()
            return redirect(url_for('checkout')) 

    if not current_user.is_paid:
        return redirect(url_for('checkout'))
        
    # فلترة الكورسات لتظهر فقط الخاصة بصف الطالب الدراسي
    student_courses = Course.query.filter_by(grade=current_user.grade).all()
    return render_template('courses.html', courses=student_courses, user=current_user)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

# ================= لوحة التحكم =================
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    error_msg = None
    if request.method == 'POST':
        password = request.form['password']
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True 
            return redirect(url_for('admin'))
        else:
            error_msg = "كلمة المرور خاطئة!"
    return render_template('admin_login.html', error=error_msg)

@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    all_users = User.query.all()
    return render_template('admin.html', users=all_users)

@app.route('/activate/<int:user_id>')
def activate(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    user.is_paid = not user.is_paid
    if user.is_paid:
        user.activation_date = datetime.utcnow()
    else:
        user.activation_date = None
        user.receipt = None
    db.session.commit()
    return redirect(url_for('admin'))

# زرار لإعادة تعيين جهاز الطالب من الإدارة لو حب يفتح من جهاز جديد بإذنك
@app.route('/reset_device/<int:user_id>')
def reset_device(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    user.device_id = None # تفريغ بصمة الجهاز ليتمكن من تسجيل الدخول من جهاز جديد
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/add_course', methods=['POST'])
def add_course():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    title = request.form['title']
    description = request.form['description']
    video_url = request.form['video_url']
    grade = request.form['grade'] # استقبال الصف المخصص للدرس
    
    new_course = Course(title=title, description=description, video_url=video_url, grade=grade)
    db.session.add(new_course)
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin_logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)