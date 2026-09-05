import os
import uuid
import random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, make_response, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
# === استدعاء مكتبة حماية أسماء الملفات ===
from werkzeug.utils import secure_filename

app = Flask(__name__)
# سحب رابط قاعدة البيانات من السيرفر، ولو مش موجود هيشغل SQLite محلياً
db_url = os.environ.get('DATABASE_URL', 'sqlite:///academy.db')
# معالجة بسيطة لمشكلة بتظهر في بعض السيرفرات مع رابط PostgreSQL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SECRET_KEY'] = 'super_secret_key_for_security'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['PDF_FOLDER'] = 'static/pdfs'
# === تحديد الحجم الأقصى للرفع بـ 2 ميجابايت لحماية السيرفر ===
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
ADMIN_PASSWORD = "admin123"

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    grade = db.Column(db.String(50), nullable=True) 
    is_paid = db.Column(db.Boolean, default=False)
    receipt = db.Column(db.String(200), nullable=True)
    activation_date = db.Column(db.DateTime, nullable=True) 
    device_id = db.Column(db.String(100), nullable=True)
    points = db.Column(db.Integer, default=0)
    session_token = db.Column(db.String(100), nullable=True)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    video_url = db.Column(db.String(500), nullable=False)
    grade = db.Column(db.String(50), nullable=False)
    pdf_file = db.Column(db.String(200), nullable=True)
    quiz_q = db.Column(db.String(300), nullable=True)
    quiz_op1 = db.Column(db.String(100), nullable=True)
    quiz_op2 = db.Column(db.String(100), nullable=True)
    quiz_op3 = db.Column(db.String(100), nullable=True)
    quiz_ans = db.Column(db.String(1), nullable=True)

class Progress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    course_id = db.Column(db.Integer, nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    question = db.Column(db.Text, nullable=False)
    reply = db.Column(db.Text, nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# === صفحة خطأ مخصصة لو الطالب رفع صورة أكبر من 2 ميجا ===
@app.errorhandler(413)
def request_entity_too_large(error):
    return "<h2 style='text-align:center; margin-top:50px; font-family:sans-serif;'>الملف كبير جداً! الحد الأقصى هو 2 ميجابايت.<br><a href='/checkout'>العودة</a></h2>", 413

@app.before_request
def enforce_single_session():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.session_token != session.get('session_token'):
            session.pop('user_id', None)
            session.pop('session_token', None)

@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

def get_rank(points):
    if points >= 200: return "بشمهندس المستقبل 🎓"
    elif points >= 50: return "عبقري الرياضيات 💡"
    elif points > 0: return "مبتدئ 🚀"
    return "جديد 🌟"

@app.context_processor
def inject_globals():
    current_user = None
    rank = ""
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        if current_user: rank = get_rank(current_user.points)
    return dict(current_user=current_user, rank=rank)

def get_price(grade):
    prices = {'رابعة ابتدائي': 350, 'خامسة ابتدائي': 350, 'سادسة ابتدائي': 400, 'أولى إعدادي': 450, 'ثانية إعدادي': 450, 'ثالثة إعدادي': 500}
    return prices.get(grade, 0)

@app.route('/')
def home():
    top_students = User.query.filter(User.points > 0).order_by(User.points.desc()).limit(5).all()
    return render_template('index.html', top_students=top_students)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error_msg = None
    if request.method == 'POST':
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        password = request.form['password']
        captcha_answer = request.form.get('captcha')
        
        if str(captcha_answer) != str(session.get('captcha_answer')):
            error_msg = "إجابة التحقق (الروبوت) غير صحيحة!"
        elif len(name.split()) < 4:
            error_msg = "يرجى إدخال الاسم رباعي كما هو مطلوب."
        elif not (len(phone) == 11 and phone.isdigit() and phone.startswith(('010', '011', '012', '015'))):
            error_msg = "يرجى إدخال رقم هاتف مصري صحيح (11 رقم)."
        elif User.query.filter_by(phone=phone).first():
            error_msg = "رقم الهاتف مسجل بالفعل! يرجى تسجيل الدخول."
        else:
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            new_user = User(name=name, phone=phone, password=hashed_password, grade="")
            
            db.session.add(new_user)
            db.session.commit()
            session.pop('captcha_answer', None)
            return redirect(url_for('login'))

    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    session['captcha_answer'] = num1 + num2

    return render_template('register.html', error=error_msg, num1=num1, num2=num2)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_msg = None
    if request.method == 'POST':
        user = User.query.filter_by(phone=request.form['phone']).first()
        if user and check_password_hash(user.password, request.form['password']):
            user_device = request.cookies.get('device_token') or str(uuid.uuid4())
            
            if user.device_id and user.device_id != user_device:
                error_msg = "مسجل بالفعل على جهاز آخر! تواصل مع الدعم الفني."
            else:
                if not user.device_id:
                    user.device_id = user_device
                
                new_session_token = str(uuid.uuid4())
                user.session_token = new_session_token
                db.session.commit()
                
                session['user_id'] = user.id
                session['session_token'] = new_session_token 
                
                resp = make_response(redirect(url_for('courses')))
                resp.set_cookie('device_token', user_device, max_age=60*60*24*365)
                return resp
        else:
            error_msg = "البيانات غير صحيحة"
            
    return render_template('login.html', error=error_msg)
    # === مسار طلب استعادة كلمة المرور ===
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    error_msg = None
    success_msg = None
    if request.method == 'POST':
        phone = request.form['phone'].strip()
        name = request.form['name'].strip()
        
        # البحث عن الطالب برقم الهاتف والاسم للتأكد من هويته
        user = User.query.filter_by(phone=phone, name=name).first()
        
        if user:
            # هنا الطالب موجود فعلاً
            success_msg = f"مرحباً يا {user.name.split()[0]}، تم تأكيد هويتك. يرجى التقاط صورة لهذه الشاشة والتواصل مع رقم الدعم الفني (01061149713) على واتساب للحصول على كلمة مرورك الجديدة."
        else:
            error_msg = "رقم الهاتف أو الاسم غير مسجل لدينا. تأكد من البيانات."
            
    return render_template('forgot.html', error=error_msg, success=success_msg)

# === مسار تغيير الباسورد للأدمن ===
@app.route('/admin/force_reset_password/<int:user_id>', methods=['POST'])
def force_reset_password(user_id):
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    
    user = User.query.get_or_404(user_id)
    new_password = request.form['new_password']
    
    # تشفير الباسورد الجديد وحفظه
    hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
    user.password = hashed_password
    db.session.commit()
    
    flash(f"✅ تم تغيير كلمة المرور للطالب {user.name} بنجاح.", "success")
    return redirect(url_for('admin'))

@app.route('/plans')
def plans():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('plans.html')

@app.route('/select_plan', methods=['POST'])
def select_plan():
    if 'user_id' not in session: return redirect(url_for('login'))
    current_user = User.query.get(session['user_id'])
    current_user.grade = request.form['grade']
    db.session.commit()
    return redirect(url_for('checkout'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session: return redirect(url_for('login'))
    current_user = User.query.get(session['user_id'])
    if not current_user.grade: return redirect(url_for('plans'))
    if current_user.receipt and not current_user.is_paid: return redirect(url_for('courses'))
    
    if request.method == 'POST':
        file = request.files['receipt']
        if file:
            # === تأمين اسم الملف ===
            safe_filename = secure_filename(file.filename)
            filename = f"user_{current_user.id}_{uuid.uuid4().hex[:4]}_{safe_filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            current_user.receipt = filename
            db.session.commit()
            return redirect(url_for('courses')) 
            
    plan_price = get_price(current_user.grade)
    return render_template('checkout.html', user=current_user, price=plan_price)

@app.route('/courses')
def courses():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    if not user.grade: return redirect(url_for('plans'))
    
    days_left = -1
    if user.is_paid and user.activation_date:
        expiry_date = user.activation_date + timedelta(days=30)
        # === حساب الأيام المتبقية ===
        if datetime.utcnow() > expiry_date:
            user.is_paid = False 
            user.activation_date = user.receipt = None 
            db.session.commit()
            return redirect(url_for('checkout')) 
        else:
            days_left = (expiry_date - datetime.utcnow()).days

    if not user.is_paid:
        if user.receipt: return render_template('pending.html', user=user)
        return redirect(url_for('checkout'))
        
    student_courses = Course.query.filter_by(grade=user.grade).all()
    completed_ids = [p.course_id for p in Progress.query.filter_by(user_id=user.id).all()]
    all_comments = Comment.query.all()
    
    total_c = len(student_courses)
    comp_c = len(completed_ids)
    progress_percent = int((comp_c / total_c) * 100) if total_c > 0 else 0
    
    # === تمرير المتغير الجديد أيام الاشتراك ===
    return render_template('courses.html', courses=student_courses, user=user, completed_ids=completed_ids, comments=all_comments, progress=progress_percent, days_left=days_left)

@app.route('/submit_quiz/<int:course_id>', methods=['POST'])
def submit_quiz(course_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    course = Course.query.get(course_id)
    selected_ans = request.form.get('answer')
    
    existing = Progress.query.filter_by(user_id=user.id, course_id=course_id).first()
    if not existing:
        new_progress = Progress(user_id=user.id, course_id=course_id)
        if selected_ans == course.quiz_ans: user.points += 10
        else: user.points += 2 
        db.session.add(new_progress)
        db.session.commit()
    return redirect(url_for('courses'))

@app.route('/ask_question/<int:course_id>', methods=['POST'])
def ask_question(course_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    new_comment = Comment(course_id=course_id, user_id=user.id, user_name=user.name, question=request.form['question'])
    db.session.add(new_comment)
    db.session.commit()
    return redirect(url_for('courses'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('session_token', None)
    return redirect(url_for('home'))

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    error_msg = None
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['is_admin'] = True 
            return redirect(url_for('admin'))
        error_msg = "كلمة المرور خاطئة!"
    return render_template('admin_login.html', error=error_msg)

@app.route('/admin')
def admin():
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    all_users = User.query.all()
    all_comments = Comment.query.order_by(Comment.date.desc()).all()
    
    total_revenue = sum([get_price(u.grade) for u in all_users if u.is_paid])
    active_students = len([u for u in all_users if u.is_paid])
    pending_students = len([u for u in all_users if not u.is_paid and u.receipt])
    
    return render_template('admin.html', users=all_users, comments=all_comments, total_revenue=total_revenue, active_students=active_students, pending_students=pending_students)

@app.route('/reply_comment/<int:comment_id>', methods=['POST'])
def reply_comment(comment_id):
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    comment = Comment.query.get_or_404(comment_id)
    comment.reply = request.form['reply']
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/activate/<int:user_id>')
def activate(user_id):
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    user.is_paid = not user.is_paid
    if user.is_paid: user.activation_date = datetime.utcnow()
    else: user.activation_date = user.receipt = None
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/reset_device/<int:user_id>')
def reset_device(user_id):
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    user.device_id = None 
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/add_course', methods=['POST'])
def add_course():
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    
    pdf_file = request.files.get('pdf')
    pdf_filename = None
    if pdf_file and pdf_file.filename != '':
        safe_pdf = secure_filename(pdf_file.filename)
        pdf_filename = f"course_{uuid.uuid4().hex[:6]}_{safe_pdf}"
        pdf_file.save(os.path.join(app.config['PDF_FOLDER'], pdf_filename))
        
    new_course = Course(
        title=request.form['title'], 
        description=request.form['description'], 
        video_url=request.form['video_url'], 
        grade=request.form['grade'],
        pdf_file=pdf_filename,
        quiz_q=request.form.get('quiz_q'),
        quiz_op1=request.form.get('quiz_op1'),
        quiz_op2=request.form.get('quiz_op2'),
        quiz_op3=request.form.get('quiz_op3'),
        quiz_ans=request.form.get('quiz_ans')
    )
    db.session.add(new_course)
    db.session.commit()
    return redirect(url_for('admin'))

# === مسار النسخ الاحتياطي لقاعدة البيانات ===
@app.route('/admin/backup')
def backup_db():
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    
    # حسب الهيكل في صورتك، قاعدة البيانات موجودة في مجلد instance
    db_path = os.path.join(app.root_path, 'instance', 'academy.db')
    
    if os.path.exists(db_path):
        date_str = datetime.utcnow().strftime('%Y-%m-%d')
        return send_file(db_path, as_attachment=True, download_name=f"Backup_Albashmohandes_{date_str}.db")
    
    # مسار بديل لو متسجلة بره الـ instance
    fallback_path = os.path.join(app.root_path, 'academy.db')
    if os.path.exists(fallback_path):
        return send_file(fallback_path, as_attachment=True, download_name=f"Backup_Albashmohandes_{datetime.utcnow().strftime('%Y-%m-%d')}.db")
        
    return "ملف قاعدة البيانات غير موجود!", 404

@app.route('/admin_logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)