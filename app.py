from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import mysql.connector
import math
import random
import os
import base64
import uuid
import re
from werkzeug.utils import secure_filename
from itertools import zip_longest
from datetime import date

# പഴയ എക്സാം ഡാറ്റ ക്ലിയർ ചെയ്യാനുള്ള ഫംഗ്ഷൻ
# പഴയ എക്സാം ഡാറ്റ ക്ലിയർ ചെയ്യാനുള്ള ഫംഗ്ഷൻ (Modified)
def clear_past_exam_data():
    try:
        conn = get_db()
        cursor = conn.cursor()
        today = date.today().strftime('%Y-%m-%d')
        
        # സീറ്റിംഗും ഡ്യൂട്ടിയും മാത്രം ക്ലിയർ ചെയ്യുന്നു. പരീക്ഷയുടെ വിവരങ്ങൾ ഹിസ്റ്ററിക്ക് വേണ്ടി നിലനിർത്തുന്നു!
        cursor.execute("DELETE FROM seating_publish WHERE exam_date < %s", (today,))
        cursor.execute("DELETE FROM invigilation WHERE exam_id IN (SELECT id FROM exams WHERE exam_date < %s)", (today,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print("Error clearing past data:", e)

app = Flask(__name__)
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
app.secret_key = 'supersecretkey'

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- DATABASE CONNECTION ---
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # XAMPP Password
    'database': 'exam_seating'
}

def get_db():
    return mysql.connector.connect(**db_config)

# ==========================================
# 1. PUBLIC ROUTES & HOME PAGE
# ==========================================

@app.route('/')
def home():
    # പഴയ ഡാറ്റ ക്ലിയർ ചെയ്യാനുള്ള ഫംഗ്ഷൻ ഇവിടെ വിളിക്കുന്നു
    clear_past_exam_data() 

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # FETCH STATS FOR HOME PAGE DASHBOARD
    cursor.execute("SELECT COUNT(*) as c FROM students")
    s_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) as c FROM users WHERE role='faculty'")
    f_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) as c FROM classrooms")
    r_count = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) as c FROM exams")
    e_count = cursor.fetchone()['c']
    
    conn.close()
    return render_template('home.html', s_count=s_count, f_count=f_count, r_count=r_count, e_count=e_count)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # --- A. STUDENT LOGIN ---
        if role == 'student':
            cursor.execute("SELECT * FROM students WHERE reg_no=%s AND password=%s", (username, password))
            user = cursor.fetchone()
            if user:
                if user['is_approved'] == 0:
                    msg = "Pending Approval! Please wait for Admin confirmation."
                    conn.close()
                    return render_template('login.html', msg=msg)
                
                # 🛑 സെഷനിലേക്ക് ഫോട്ടോയും പേരും കൊടുക്കുന്നു
                session['user_id'] = user['id']
                session['user_name'] = user['name'] 
                session['user_photo'] = user['photo'] 
                session['role'] = 'student'
                
                conn.close()
                return redirect('/')
            else:
                msg = "Invalid Register Number or Password!"

        # --- B. FACULTY & ADMIN LOGIN ---
        else:
            cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s AND role=%s", (username, password, role))
            user = cursor.fetchone()
            if user:
                if role == 'admin':
                    # 🛑 അഡ്മിൻ സെഷൻ 
                    session['user_id'] = user['id']
                    session['user_name'] = user['name']
                    session['user_photo'] = user['photo']
                    session['role'] = 'admin'
                    conn.close()
                    return redirect('/')
                
                elif user['is_approved'] == 0:
                    msg = "Your account is pending admin approval!"
                    conn.close()
                    return render_template('login.html', msg=msg)
                
                else:
                    # 🛑 ഫാക്കൽറ്റി സെഷൻ
                    session['user_id'] = user['id']
                    session['user_name'] = user['name']
                    session['user_photo'] = user['photo']
                    session['role'] = 'faculty'
                    conn.close()
                    return redirect('/')
            else:
                msg = "Invalid Credentials!"
        
        conn.close()
    return render_template('login.html', msg=msg)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ==========================================
# 2. ADMIN ROUTES
# ==========================================

@app.route('/admin')
def admin_home():
    return redirect('/')

@app.route('/api/get_date_details', methods=['POST'])
def get_date_details():
    if session.get('role') != 'admin': return jsonify({'error': 'Unauthorized'})
    date_val = request.json.get('date')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT e.id, sub.subject_name, c.course_name 
        FROM exams e JOIN subjects sub ON e.subject_id = sub.id JOIN courses c ON sub.course_id = c.id
        WHERE e.exam_date = %s
    """, (date_val,))
    exams = cursor.fetchall()
    
    total_students = 0
    departments = set()
    for exam in exams:
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM students s JOIN subjects sub ON s.course_id = sub.course_id AND s.semester = sub.semester
            WHERE sub.id = (SELECT subject_id FROM exams WHERE id=%s) AND s.is_approved=1
        """, (exam['id'],))
        total_students += cursor.fetchone()['cnt']
        departments.add(exam['course_name'])
        
    conn.close()
    return jsonify({'total_students': total_students, 'departments': list(departments), 'is_common': len(departments) > 1})

# ------------------------------------------
# PAGE 1: EXAM TIME TABLE ONLY
# ------------------------------------------
# ------------------------------------------
# PAGE 1: EXAM TIME TABLE ONLY
# ------------------------------------------
@app.route('/get_active_semesters/<int:course_id>')
def get_active_semesters(course_id):
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        # Approved aaya kuttikal ulla semesters mathram edukkunnu
        cursor.execute("SELECT DISTINCT semester FROM student WHERE course_id = %s AND status = 'Approved' ORDER BY semester", (course_id,))
        sems = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({'status': 'success', 'semesters': [s['semester'] for s in sems]})
    except Exception as e:
        print("Backend Error:", e)
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/admin/timetable', methods=['GET', 'POST'])
def admin_timetable():
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST' and 'save_timetable' in request.form:
        exam_name = request.form.get('exam_name')
        subjects = request.form.getlist('subject[]')
        dates = request.form.getlist('date[]')
        times = request.form.getlist('time[]')
        row_courses = request.form.getlist('row_course_id[]')
        row_semesters = request.form.getlist('row_semester[]')

        for i in range(len(subjects)):
            if subjects[i] and subjects[i] != "":
                cursor.execute("""
                    INSERT INTO exams (exam_name, course_id, semester, subject_id, exam_date, exam_time) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (exam_name, row_courses[i], row_semesters[i], subjects[i], dates[i], times[i]))
        conn.commit()
        return redirect('/admin/timetable')

    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()

    cursor.execute("""
        SELECT e.*, s.subject_name, c.course_name 
        FROM exams e 
        JOIN subjects s ON e.subject_id = s.id 
        JOIN courses c ON e.course_id = c.id
        ORDER BY e.exam_name, c.course_name, e.semester, e.exam_date ASC
    """)
    all_exams = cursor.fetchall()

    from datetime import date
    today = date.today()
    
    grouped_exams = {}
    upcoming_exams = {}

    for e in all_exams:
        e['is_completed'] = e['exam_date'] < today
        
        exam_nm = e['exam_name']
        course_nm = e['course_name']
        sem = e['semester']
        
        # 🛑 കോഴ്സും സെമസ്റ്ററും ഒരുമിച്ച് ഗ്രൂപ്പ് ആക്കുന്നു (ഡബിൾ ആവാതിരിക്കാൻ)
        dept_sem_key = f"{course_nm}_{sem}"
        
        if exam_nm not in grouped_exams:
            grouped_exams[exam_nm] = {}
            
        if dept_sem_key not in grouped_exams[exam_nm]:
            grouped_exams[exam_nm][dept_sem_key] = {
                'course_name': course_nm,
                'semester': sem,
                'exams': []
            }
            
        grouped_exams[exam_nm][dept_sem_key]['exams'].append(e)

        if not e['is_completed']:
            modal_group = f"{course_nm} (Semester {sem}) - {exam_nm}"
            if modal_group not in upcoming_exams:
                upcoming_exams[modal_group] = []
            upcoming_exams[modal_group].append(e)

    conn.close()
    return render_template('timetable.html', courses=courses, grouped_exams=grouped_exams, upcoming_exams=upcoming_exams)
# ഡിലീറ്റ് ചെയ്യാനുള്ള റൂട്ട്
# --- മെയിൻ പേജ് കാണിക്കാൻ ---
@app.route('/admin/seatplan', methods=['GET', 'POST'])
def admin_seatplan():
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Exam date matthu aa date nalli iruva sessions (FN/AN) eradanu fetch maduttide
    cursor.execute("""
        SELECT exam_date, GROUP_CONCAT(DISTINCT exam_time) as sessions 
        FROM exams 
        WHERE exam_date >= CURDATE() 
        GROUP BY exam_date
        ORDER BY exam_date ASC
    """)
    exam_dates = cursor.fetchall()
    conn.close()
    
    return render_template('seatplan.html', exam_dates=exam_dates)

# --- Step 1: കുട്ടികളുടെ എണ്ണം എടുക്കാൻ ---
@app.route('/api/get_exam_students', methods=['POST'])
def get_exam_students():
    data = request.get_json()
    date_val = data.get('date')
    sessions = data.get('sessions') 
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    total_students = 0
    if sessions:
        format_strings = ','.join(['%s'] * len(sessions))
        # 🛑 students ടേബിളും is_approved ഉം ശരിയാക്കി 🛑
        query = f"""
            SELECT COUNT(DISTINCT s.id) as total_count
            FROM students s
            JOIN subjects sub ON s.course_id = sub.course_id AND s.semester = sub.semester
            JOIN exams e ON e.subject_id = sub.id
            WHERE e.exam_date = %s AND e.exam_time IN ({format_strings}) AND s.is_approved = 1
        """
        params = [date_val] + sessions
        cursor.execute(query, tuple(params))
        result = cursor.fetchone()
        total_students = result['total_count'] if result['total_count'] else 0

    conn.close()
    return jsonify({"total_students": total_students})

# --- Step 2 & 4: റൂമുകളും ടീച്ചർമാരെയും എടുക്കാൻ ---
@app.route('/api/get_resources', methods=['GET'])
def get_resources():
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # 1. റൂമുകൾ എടുക്കുന്നു (UI-ക്ക് വേണ്ട എല്ലാ ഫീൽഡുകളും കൊടുക്കുന്നു)
        cursor.execute("SELECT id, room_no as name, capacity FROM classrooms ORDER BY room_no ASC")
        rooms = cursor.fetchall()
        
        # 2. ടീച്ചർമാരെ എടുക്കുന്നു
        cursor.execute("SELECT id, name FROM users WHERE role = 'faculty' ORDER BY name")
        faculty = cursor.fetchall()
        
        conn.close()
        return jsonify({"rooms": rooms, "faculty": faculty})
        
    except Exception as e:
        print("API ERROR:", str(e)) 
        return jsonify({"error": str(e)}), 500


@app.route('/admin_approve', methods=['GET', 'POST']) # 🛑 ഇവിടെ GET കൂടെ വേണം
def admin_approve():
    conn = get_db()
    cursor = conn.cursor(dictionary=True) 

    # 1. ബട്ടൺ അമർത്തുമ്പോൾ (POST Request)
    if request.method == 'POST':
        user_type = request.form.get('type') 
        user_id = request.form.get('id')
        action = request.form.get('action')

        if action == 'approve':
            table = "students" if user_type == "student" else "users"
            cursor.execute(f"UPDATE {table} SET is_approved = 1 WHERE id = %s", (user_id,))
            
        elif action == 'reject':
            # റിജക്ട് ചെയ്താൽ ഡാറ്റാബേസിൽ നിന്ന് നീക്കം ചെയ്യുന്നു
            table = "students" if user_type == "student" else "users"
            cursor.execute(f"DELETE FROM {table} WHERE id = %s", (user_id,))
            
        conn.commit()

    # 2. വെറുതെ പേജ് തുറക്കുമ്പോൾ (GET Request) - പെൻഡിങ് ലിസ്റ്റ് എടുക്കുന്നു
    cursor.execute("SELECT * FROM users WHERE role='faculty' AND is_approved = 1")
    faculty_list = cursor.fetchall()
    
    # JOIN ഉപയോഗിച്ച് കോഴ്സ് പേര് എടുക്കുന്നു
    cursor.execute("""
        SELECT s.*, c.course_name 
        FROM students s 
        JOIN courses c ON s.course_id = c.id 
        WHERE s.is_approved = 0
    """)
    student_list = cursor.fetchall()
    
    conn.close()
    return render_template('approve.html', faculty=faculty_list, students=student_list)

@app.route('/manage/rooms')
def manage_rooms():
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM classrooms ORDER BY room_no")
    rooms = cursor.fetchall()
    conn.close()
    return render_template('manage_rooms.html', rooms=rooms)

@app.route('/add_room', methods=['GET', 'POST'])
def add_room():
    if session.get('role') != 'admin': return redirect('/login')
    if request.method == 'POST':
        try:
            room_no = request.form['room_no'].strip()
            benches = int(request.form['benches'])
            capacity = benches * 2 # 1 Bench = 2 Students
            
            conn = get_db()
            cursor = conn.cursor()
            # ഡ്യൂപ്ലിക്കേറ്റ് റൂം വരാതിരിക്കാൻ
            cursor.execute("SELECT id FROM classrooms WHERE room_no = %s", (room_no,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO classrooms (room_no, benches, capacity) VALUES (%s, %s, %s)", 
                               (room_no, benches, capacity))
                conn.commit()
            conn.close()
        except Exception as e: print(e)
        return redirect('/manage/rooms')
    return render_template('add_room.html')

@app.route('/edit/room/<int:id>', methods=['GET', 'POST'])
def edit_room(id):
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            room_no = request.form['room_no'].strip()
            benches = int(request.form['benches'])
            capacity = benches * 2
            
            cursor.execute("UPDATE classrooms SET room_no=%s, benches=%s, capacity=%s WHERE id=%s", 
                           (room_no, benches, capacity, id))
            conn.commit()
        except Exception as e: print(e)
        conn.close()
        return redirect('/manage/rooms')
        
    cursor.execute("SELECT * FROM classrooms WHERE id=%s", (id,))
    room = cursor.fetchone()
    conn.close()
    return render_template('edit_room.html', room=room)

@app.route('/delete/room/<int:id>')
def delete_room(id):
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM allotment WHERE room_id=%s", (id,))
    cursor.execute("DELETE FROM invigilation WHERE room_id=%s", (id,))
    cursor.execute("DELETE FROM permanent_seating WHERE room_id=%s", (id,))
    cursor.execute("DELETE FROM classrooms WHERE id=%s", (id,))
    conn.commit(); conn.close()
    return redirect('/manage/rooms')

@app.route('/manage/subjects', methods=['GET', 'POST'])
def manage_subjects():
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    
    # 1. ADD NEW DEPARTMENT (COURSE)
    if 'add_course' in request.form:
        course_name = request.form['new_course_name'].strip()
        # ഡ്യൂപ്ലിക്കേറ്റ് ഉണ്ടോ എന്ന് ചെക്ക് ചെയ്യുന്നു
        cursor.execute("SELECT id FROM courses WHERE course_name = %s", (course_name,))
        if not cursor.fetchone(): # ഇല്ലെങ്കിൽ മാത്രം ഇൻസേർട്ട് ചെയ്യും
            try: 
                cursor.execute("INSERT INTO courses (course_name) VALUES (%s)", (course_name,))
                conn.commit()
            except Exception as e: print(e)
        return redirect('/manage/subjects')
        
    # 2. ADD NEW SUBJECT
    if 'add_subject' in request.form:
        sub_code = request.form['subject_code'].strip()
        # ഒരേ സബ്ജക്ട് കോഡ് വീണ്ടും വരാതിരിക്കാൻ ചെക്ക് ചെയ്യുന്നു
        cursor.execute("SELECT id FROM subjects WHERE subject_code = %s", (sub_code,))
        if not cursor.fetchone():
            try: 
                cursor.execute("INSERT INTO subjects (subject_name, subject_code, course_id, semester) VALUES (%s, %s, %s, %s)", 
                               (request.form['subject_name'], sub_code, request.form['course_id'], request.form['semester']))
                conn.commit()
            except Exception as e: print(e)
        return redirect('/manage/subjects')
        
    # FETCH DATA TO DISPLAY
    cursor.execute("SELECT s.*, c.course_name FROM subjects s JOIN courses c ON s.course_id = c.id ORDER BY s.course_id, s.semester")
    subjects = cursor.fetchall()
    
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()
    
    conn.close()
    return render_template('manage_subjects.html', subjects=subjects, courses=courses)

@app.route('/delete/subject/<int:id>')
def delete_subject(id):
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM exams WHERE subject_id=%s", (id,))
    cursor.execute("DELETE FROM subjects WHERE id=%s", (id,))
    conn.commit(); conn.close(); return redirect('/manage/subjects')

@app.route('/manage/faculty', methods=['GET', 'POST'])
def manage_faculty():
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        mobile = request.form['mobile']
        password = request.form['password'] # പാസ്‌വേഡ് എടുക്കുന്നു
        
        # 🛑 1. Password Validation Check (പുതിയതായി ചേർത്തത്)
        if not re.match(r'^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]).{6,}$', password):
            return "<script>alert('Error: Password must have at least 6 characters, 1 Uppercase, 1 Number, and 1 Symbol!'); window.history.back();</script>"

        # 🛑 2. Duplicate Check
        cursor.execute("""
            SELECT username FROM users 
            WHERE role = 'faculty' AND (username = %s OR email = %s OR mobile = %s)
        """, (username, email, mobile))
        
        if cursor.fetchone():
            return "<script>alert('Error: Staff ID, Email, or Mobile already exists!'); window.history.back();</script>"

        try: 
            cursor.execute("""
                INSERT INTO users (username, password, name, email, mobile, role, position, is_approved, availability, photo, profession) 
                VALUES (%s, %s, %s, %s, %s, 'faculty', %s, 1, 'Yes', 'default.png', 'Faculty')
            """, (username, password, request.form['name'], email, mobile, request.form['position']))
            conn.commit()
        except Exception as e: 
            print(f"Error adding faculty: {e}")
            
        return redirect('/manage/faculty')
        
    cursor.execute("SELECT * FROM users WHERE role='faculty' AND is_approved = 1")
    faculty = cursor.fetchall()
    
    conn.close()
    return render_template('manage_faculty.html', faculty=faculty)

@app.route('/delete/faculty/<int:id>')
def delete_faculty(id):
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM invigilation WHERE faculty_id=%s", (id,))
    cursor.execute("DELETE FROM users WHERE id=%s", (id,))
    conn.commit(); conn.close(); return redirect('/manage/faculty')

@app.route('/manage/students', methods=['GET', 'POST'])
def manage_students():
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    
    # 1. ADD NEW STUDENT BY ADMIN
    if request.method == 'POST':
        reg_no = request.form['reg_no']
        email = request.form['email']
        mobile = request.form['mobile']
        
        # 🛑 ഡ്യൂപ്ലിക്കേറ്റ് ചെക്ക്
        cursor.execute("""
            SELECT reg_no FROM students 
            WHERE reg_no = %s OR email = %s OR mobile = %s
        """, (reg_no, email, mobile))
        
        if cursor.fetchone():
            return "<script>alert('Error: Register Number, Email, or Mobile already exists!'); window.history.back();</script>"

        try: 
            cursor.execute("""
                INSERT INTO students (reg_no, name, email, mobile, course_id, semester, password, is_approved, photo) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 'default.png')
            """, (reg_no, request.form['name'], email, mobile, 
                  request.form['course'], request.form['semester'], request.form['password']))
            conn.commit()
        except Exception as e: 
            print(e)
        return redirect(f"/manage/students?course_id={request.form['course']}&semester={request.form['semester']}")

    # 2. FETCH DATA FOR DROPDOWNS
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()

    # 3. GET FILTER VALUES FROM URL
    selected_course = request.args.get('course_id')
    selected_sem = request.args.get('semester')
    view_all = request.args.get('view_all') 
    
    students = []
    
    # 4. FETCH STUDENTS (അപ്രൂവ് ആയവരെ മാത്രം കാണിക്കുന്നു)
    if view_all == 'true':
        cursor.execute("""
            SELECT s.*, c.course_name 
            FROM students s 
            JOIN courses c ON s.course_id = c.id 
            WHERE s.is_approved = 1
            ORDER BY c.course_name, s.semester, s.reg_no
        """)
        students = cursor.fetchall()
    elif selected_course and selected_sem:
        cursor.execute("""
            SELECT s.*, c.course_name 
            FROM students s 
            JOIN courses c ON s.course_id = c.id 
            WHERE s.course_id = %s AND s.semester = %s AND s.is_approved = 1
            ORDER BY s.reg_no
        """, (selected_course, selected_sem))
        students = cursor.fetchall()
        
    # 5. FETCH ALL STUDENTS FOR THE EDIT/DELETE MODAL FILTERING
    cursor.execute("SELECT id, reg_no, name, course_id, semester FROM students WHERE is_approved = 1 ORDER BY reg_no")
    all_students_modal = cursor.fetchall()
        
    conn.close()
    return render_template('manage_students.html', 
                           students=students, courses=courses, 
                           selected_course=selected_course, selected_sem=selected_sem,
                           view_all=view_all, all_students_modal=all_students_modal)

@app.route('/register_student', methods=['GET', 'POST'])
def register_student():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'GET':
        # കോഴ്സുകൾ ലിസ്റ്റ് ചെയ്യാൻ
        cursor.execute("SELECT * FROM courses")
        courses_list = cursor.fetchall()
        cursor.close()
        db.close()
        return render_template('register_student.html', courses=courses_list)

    if request.method == 'POST':
        try:
            name = request.form.get('name')
            reg_no = request.form.get('reg_no')
            course_id = request.form.get('course_id') # HTML-ൽ നിന്ന് വരുന്നത്
            semester = request.form.get('semester')
            email = request.form.get('email')
            mobile = request.form.get('mobile')
            password = request.form.get('password')

            # 🛑 1. ഡ്യൂപ്ലിക്കേറ്റ് ഉണ്ടോ എന്ന് ചെക്ക് ചെയ്യുന്നു (Duplicate Check) 🛑
            cursor.execute("""
                SELECT reg_no, email, mobile FROM students 
                WHERE reg_no = %s OR email = %s OR mobile = %s
            """, (reg_no, email, mobile))
            existing_student = cursor.fetchone()

            if existing_student:
                if existing_student['reg_no'] == reg_no:
                    return jsonify({"status": "error", "message": "This Register Number is already registered!"})
                elif existing_student['email'] == email:
                    return jsonify({"status": "error", "message": "This Email Address is already registered!"})
                elif existing_student['mobile'] == mobile:
                    return jsonify({"status": "error", "message": "This Mobile Number is already registered!"})
            
            # 🛑 2. പ്രശ്നമൊന്നും ഇല്ലെങ്കിൽ ഡാറ്റാബേസിലേക്ക് സേവ് ചെയ്യുന്നു 🛑
            sql = """
                INSERT INTO students 
                (reg_no, name, email, mobile, course_id, semester, password, is_approved, photo) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'default.png')
            """
            cursor.execute(sql, (reg_no, name, email, mobile, course_id, semester, password))
            
            db.commit()
            cursor.close()
            db.close()

            return jsonify({"status": "success", "message": "Registration successful! Please wait for Admin Approval."})

        except Exception as e:
            print(f"Error: {e}")
            return jsonify({"status": "error", "message": str(e)})

@app.route('/delete/student/<int:id>')
def delete_student(id):
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM allotment WHERE student_id=%s", (id,))
    cursor.execute("DELETE FROM students WHERE id=%s", (id,))
    conn.commit(); conn.close(); return redirect('/manage/students')

# ==========================================
# 4. STUDENT & FACULTY ROUTES
# ==========================================

@app.route('/student')
def student_dashboard():
    if session.get('role') != 'student': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    today = date.today()

    # വിദ്യാർത്ഥിയുടെ വിവരങ്ങൾ എടുക്കുന്നു
    cursor.execute("SELECT name, reg_no FROM students WHERE id=%s", (session['user_id'],))
    student = cursor.fetchone()

    # ഈ വിദ്യാർത്ഥിക്ക് പബ്ലിഷ് ചെയ്ത സീറ്റിംഗ് മാത്രം എടുക്കുന്നു
    cursor.execute("""
        SELECT e.exam_name, e.exam_date, e.exam_time, s.subject_name, 
               a.seat_no, a.bench_no, a.side, c.room_no
        FROM exams e JOIN subjects s ON e.subject_id = s.id 
        JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time
        JOIN allotment a ON a.exam_id = e.id AND a.student_id = %s
        JOIN classrooms c ON a.room_id = c.id
        WHERE sp.status = 'Published'
        ORDER BY e.exam_date ASC
    """, (session['user_id'],))
    all_seating = cursor.fetchall()
    conn.close()

    # ഇന്നത്തെയും വരാനിരിക്കുന്നതുമായ സീറ്റിംഗ് (Active)
    active_seating = [s for s in all_seating if s['exam_date'] >= today]
    
    # കഴിഞ്ഞുപോയ എക്സാമുകൾ (അതിൽ ഏറ്റവും അവസാനത്തേത് മാത്രം എടുക്കുന്നു)
    past_seating = [s for s in all_seating if s['exam_date'] < today]
    last_seating = past_seating[-1] if past_seating else None

    return render_template('student_dashboard.html', student=student, active_seating=active_seating, last_seating=last_seating)

@app.route('/student/seat/<int:exam_id>')
def student_seat(exam_id):
    if session.get('role') != 'student': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT status FROM seating_publish JOIN exams e ON seating_publish.exam_date = e.exam_date AND seating_publish.exam_time = e.exam_time WHERE e.id=%s", (exam_id,))
    status = cursor.fetchone()
    if status and status['status'] == 'Published':
        cursor.execute("""
            SELECT a.seat_no, a.bench_no, a.side, c.room_no, e.exam_name, e.exam_date, e.exam_time, sub.subject_name
            FROM allotment a JOIN classrooms c ON a.room_id = c.id JOIN exams e ON a.exam_id = e.id JOIN subjects sub ON e.subject_id = sub.id
            WHERE a.exam_id = %s AND a.student_id = %s
        """, (exam_id, session['user_id']))
        allotment = cursor.fetchone()
    else: allotment = None
    conn.close()
    return render_template('student_seat.html', data=allotment)

@app.route('/student/profile', methods=['GET', 'POST'])
def student_profile():
    if session.get('role') != 'student': return redirect('/login')
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    msg = ""
    
    if request.method == 'POST':
        name = request.form['name']
        mobile = request.form['mobile']
        email = request.form.get('email', '') 
        password = request.form['password']
        
        # 1. നിലവിലുള്ള കുട്ടിയുടെ ഡാറ്റ (പഴയ ഫോട്ടോ ഉൾപ്പെടെ) എടുക്കുന്നു
        cursor.execute("SELECT email, mobile, photo FROM students WHERE id=%s", (session['user_id'],))
        current_data = cursor.fetchone()
        
        duplicate_found = False
        
        # 2. ഈമെയിലോ നമ്പറോ മാറ്റിയിട്ടുണ്ടെങ്കിൽ മാത്രം ഡ്യൂപ്ലിക്കേറ്റ് ചെക്ക് ചെയ്യുന്നു
        if current_data['email'] != email or current_data['mobile'] != mobile:
            cursor.execute("""
                SELECT id FROM students 
                WHERE (email = %s OR mobile = %s) AND id != %s
            """, (email, mobile, session['user_id']))
            if cursor.fetchone():
                duplicate_found = True
        
        if duplicate_found:
            msg = "Error: Email or Mobile is already in use by another student!"
        else:
            photo_filename = request.form.get('current_photo', 'default.png')
            cropped_image = request.form.get('cropped_image') 
            
            # 3. പുതിയ ഫോട്ടോ ഉണ്ടെങ്കിൽ പഴയത് ഡിലീറ്റ് ചെയ്ത് പുതിയത് സേവ് ചെയ്യുന്നു
            if cropped_image and ',' in cropped_image:
                # പഴയ ഫോട്ടോ default.png അല്ലെങ്കിൽ അത് ഡിലീറ്റ് ചെയ്യുക
                if current_data['photo'] and current_data['photo'] != 'default.png':
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_data['photo'])
                    if os.path.exists(old_path):
                        os.remove(old_path)

                # പുതിയ ഫോട്ടോ സേവ് ചെയ്യുന്നു
                header, encoded = cropped_image.split(",", 1)
                file_ext = header.split(';')[0].split('/')[1]
                photo_filename = f"student_{session['user_id']}_{uuid.uuid4().hex[:6]}.{file_ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(encoded))

            # 4. ഡാറ്റാബേസിൽ അപ്ഡേറ്റ് ചെയ്യുന്നു
            cursor.execute("UPDATE students SET name=%s, mobile=%s, email=%s, password=%s, photo=%s WHERE id=%s", 
                           (name, mobile, email, password, photo_filename, session['user_id']))
            conn.commit()
            
            session['user_photo'] = photo_filename
            msg = "Profile Updated Successfully!"
        
    cursor.execute("SELECT s.*, c.course_name FROM students s JOIN courses c ON s.course_id = c.id WHERE s.id=%s", (session['user_id'],))
    student = cursor.fetchone()
    conn.close()
    
    return render_template('student_profile.html', student=student, msg=msg)

@app.route('/student/timetable')
def student_timetable():
    if session.get('role') != 'student': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    today = date.today()

    # Student na course mattu semester hudukuttade
    cursor.execute("SELECT course_id, semester FROM students WHERE id = %s", (session['user_id'],))
    student = cursor.fetchone()

    # Student ge avara course data matra fetch maduttade
    cursor.execute("""
        SELECT e.*, s.subject_name, c.course_name 
        FROM exams e 
        JOIN subjects s ON e.subject_id = s.id 
        JOIN courses c ON e.course_id = c.id 
        WHERE s.course_id = %s AND s.semester = %s 
        ORDER BY e.exam_date ASC
    """, (student['course_id'], student['semester']))
    all_exams = cursor.fetchall()
    
    grouped_exams = {}
    for e in all_exams:
        e['is_completed'] = e['exam_date'] < today
        exam_nm = e['exam_name']
        course_nm = e['course_name']
        sem = e['semester']
        dept_sem_key = f"{course_nm}_{sem}"
        
        if exam_nm not in grouped_exams:
            grouped_exams[exam_nm] = {}
        if dept_sem_key not in grouped_exams[exam_nm]:
            grouped_exams[exam_nm][dept_sem_key] = {'course_name': course_nm, 'semester': sem, 'exams': []}
        grouped_exams[exam_nm][dept_sem_key]['exams'].append(e)

    conn.close()
    return render_template('view_timetable.html', grouped_exams=grouped_exams)

@app.route('/student/all_seating')
def student_all_seating():
    if session.get('role') != 'student': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT a.seat_no, a.bench_no, a.side, r.room_no, s.name, s.reg_no, sub.subject_name, e.exam_date, e.exam_time
        FROM allotment a JOIN students s ON a.student_id = s.id JOIN classrooms r ON a.room_id = r.id JOIN exams e ON a.exam_id = e.id JOIN subjects sub ON e.subject_id = sub.id JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time WHERE sp.status = 'Published' ORDER BY e.exam_date, e.exam_time, r.room_no, a.seat_no
    """)
    seating = cursor.fetchall(); conn.close()
    return render_template('public_seating.html', seating=seating)

@app.route('/faculty')
def faculty_dashboard():
    if session.get('role') != 'faculty': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT e.exam_date, e.exam_time, s.subject_name, c.room_no FROM invigilation i JOIN exams e ON i.exam_id = e.id JOIN subjects s ON e.subject_id = s.id JOIN classrooms c ON i.room_id = c.id WHERE i.faculty_id = %s", (session['user_id'],))
    duties = cursor.fetchall(); conn.close()
    return render_template('faculty.html', duties=duties)



@app.route('/faculty/profile', methods=['GET', 'POST'])
def faculty_profile():
    if session.get('role') != 'faculty': return redirect('/login')
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    msg = ""
    
    if request.method == 'POST':
        name = request.form['name']
        mobile = request.form['mobile']
        email = request.form.get('email', '') 
        password = request.form['password']
        # 🛑 പൊസിഷൻ ഫോമിൽ നിന്ന് എടുക്കുന്നു
        position = request.form.get('position')
        
        cursor.execute("SELECT email, mobile, photo, password FROM users WHERE id=%s", (session['user_id'],))
        current_data = cursor.fetchone()

        password_pattern = r"^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{6,}$"
        
        duplicate_found = False
        if current_data['email'] != email or current_data['mobile'] != mobile:
            cursor.execute("SELECT id FROM users WHERE role = 'faculty' AND (email = %s OR mobile = %s) AND id != %s", (email, mobile, session['user_id']))
            if cursor.fetchone():
                duplicate_found = True

        if duplicate_found:
            msg = "Error: Email or Mobile is already in use by another faculty!"
        elif current_data['password'] != password and not re.match(password_pattern, password):
            msg = "Error: Password must have at least 6 characters, 1 Uppercase, 1 Number, and 1 Symbol!"
        else:
            photo_filename = request.form.get('current_photo', 'default.png')
            cropped_image = request.form.get('cropped_image') 
            
            if cropped_image and ',' in cropped_image:
                if current_data['photo'] and current_data['photo'] != 'default.png':
                    old_path = os.path.join(app.root_path, 'static', 'uploads', current_data['photo'])
                    if os.path.exists(old_path):
                        os.remove(old_path)

                header, encoded = cropped_image.split(",", 1)
                file_ext = header.split(';')[0].split('/')[1]
                photo_filename = f"faculty_{session['user_id']}_{uuid.uuid4().hex[:6]}.{file_ext}"
                filepath = os.path.join(app.root_path, 'static', 'uploads', photo_filename)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(encoded))

            # 🛑 UPDATE ക്വറിയിൽ position കൂടി ചേർത്തു
            cursor.execute("""
                UPDATE users 
                SET name=%s, mobile=%s, email=%s, password=%s, photo=%s, position=%s 
                WHERE id=%s
            """, (name, mobile, email, password, photo_filename, position, session['user_id']))
            conn.commit()
            
            session['user_photo'] = photo_filename
            msg = "Profile Updated Successfully!"
        
    cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    faculty = cursor.fetchone()
    conn.close()
    
    return render_template('faculty_profile.html', faculty=faculty, msg=msg)

@app.route('/edit/<string:type>/<int:id>', methods=['GET', 'POST'])
def edit_generic(type, id):
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    tables = {'student': 'students', 'faculty': 'users', 'subject': 'subjects', 'room': 'classrooms'}
    table = tables.get(type)
    if request.method == 'POST':
        if type == 'student': cursor.execute("UPDATE students SET name=%s, reg_no=%s, mobile=%s WHERE id=%s", (request.form['name'], request.form['reg_no'], request.form['mobile'], id))
        elif type == 'faculty': cursor.execute("UPDATE users SET name=%s, mobile=%s, position=%s WHERE id=%s", (request.form['name'], request.form['mobile'], request.form['position'], id))
        elif type == 'subject': cursor.execute("UPDATE subjects SET subject_name=%s, subject_code=%s, semester=%s WHERE id=%s", (request.form['subject_name'], request.form['subject_code'], request.form['semester'], id))
        elif type == 'room': b = int(request.form['benches']); c = b * 2; cursor.execute("UPDATE classrooms SET room_no=%s, benches=%s, capacity=%s WHERE id=%s", (request.form['room_no'], b, c, id))
        conn.commit(); conn.close()
        return redirect(f'/manage/{type}s')
    cursor.execute(f"SELECT * FROM {table} WHERE id=%s", (id,))
    data = cursor.fetchone(); conn.close()
    return render_template('edit_form.html', type=type.title(), data=data, action=f'/edit/{type}/{id}')

@app.route('/edit/student/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        # ഫോമിൽ നിന്നും പുതിയ ഡാറ്റ എടുക്കുന്നു
        name = request.form['name']
        reg_no = request.form['reg_no']
        course_id = request.form['course']
        semester = request.form['semester']
        email = request.form['email']
        mobile = request.form['mobile']
        
        # ഡാറ്റാബേസിൽ അപ്ഡേറ്റ് ചെയ്യുന്നു
        cursor.execute("""
            UPDATE students 
            SET name=%s, reg_no=%s, course_id=%s, semester=%s, email=%s, mobile=%s 
            WHERE id=%s
        """, (name, reg_no, course_id, semester, email, mobile, id))
        
        conn.commit()
        conn.close()
        
        # എഡിറ്റ് ചെയ്ത ശേഷം തിരികെ ആ കുട്ടിയുടെ ക്ലാസ്സിലേക്ക് തന്നെ പോകാൻ
        return redirect(f'/manage/students?course_id={course_id}&semester={semester}')
        
    # എഡിറ്റ് പേജ് ലോഡ് ചെയ്യുമ്പോൾ പഴയ ഡാറ്റ കാണിക്കാൻ
    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()
    
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()
    
    conn.close()
    return render_template('edit_student.html', student=student, courses=courses)

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        reg_no = request.form['reg_no']
        email = request.form['email']
        mobile = request.form['mobile']
        
        # 🛑 ഡ്യൂപ്ലിക്കേറ്റ് ചെക്ക്
        cursor.execute("""
            SELECT reg_no FROM students 
            WHERE reg_no = %s OR email = %s OR mobile = %s
        """, (reg_no, email, mobile))
        
        if cursor.fetchone():
            conn.close()
            return "<script>alert('Error: Register Number, Email, or Mobile already exists!'); window.history.back();</script>"

        try: 
            cursor.execute("""
                INSERT INTO students (reg_no, name, email, mobile, course_id, semester, password, is_approved, photo) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 'default.png')
            """, (reg_no, request.form['name'], email, mobile, 
                  request.form['course'], request.form['semester'], request.form['password']))
            conn.commit()
        except Exception as e: 
            print(e)
            
        conn.close()
        return redirect(f"/manage/students?course_id={request.form['course']}&semester={request.form['semester']}")
        
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()
    conn.close()
    
    return render_template('add_student.html', courses=courses)

@app.route('/add_faculty', methods=['GET', 'POST'])
def add_faculty():
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    if request.method == 'POST':
        conn = get_db()
        cursor = conn.cursor()
        try: 
            cursor.execute("""
                INSERT INTO users (username, password, name, email, mobile, role, position, is_approved) 
                VALUES (%s, %s, %s, %s, %s, 'faculty', %s, 1)
            """, (request.form['username'], request.form['password'], request.form['name'], 
                  request.form['email'], request.form['mobile'], request.form['position']))
            conn.commit()
        except Exception as e: 
            print(e)
        conn.close()
        return redirect('/manage/faculty')
        
    return render_template('add_faculty.html')

@app.route('/edit/faculty/<int:id>', methods=['GET', 'POST'])
def edit_faculty(id):
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        name = request.form['name']
        position = request.form['position']
        username = request.form['username']
        email = request.form['email']
        mobile = request.form['mobile']
        
        cursor.execute("""
            UPDATE users 
            SET name=%s, position=%s, username=%s, email=%s, mobile=%s 
            WHERE id=%s AND role='faculty'
        """, (name, position, username, email, mobile, id))
        
        conn.commit()
        conn.close()
        return redirect('/manage/faculty')
        
    cursor.execute("SELECT * FROM users WHERE id=%s AND role='faculty'", (id,))
    faculty = cursor.fetchone()
    conn.close()
    
    return render_template('edit_faculty.html', faculty=faculty)

@app.route('/edit/subject/<int:id>', methods=['GET', 'POST'])
def edit_subject(id):
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        # ഫോമിൽ നിന്നുള്ള പുതിയ ഡാറ്റ
        name = request.form['subject_name']
        code = request.form['subject_code']
        course_id = request.form['course_id']
        semester = request.form['semester']
        
        # ഡാറ്റാബേസിൽ അപ്ഡേറ്റ് ചെയ്യുന്നു
        cursor.execute("""
            UPDATE subjects 
            SET subject_name=%s, subject_code=%s, course_id=%s, semester=%s 
            WHERE id=%s
        """, (name, code, course_id, semester, id))
        
        conn.commit()
        conn.close()
        return redirect('/manage/subjects')
        
    # പഴയ ഡാറ്റ കാണിക്കാൻ
    cursor.execute("SELECT * FROM subjects WHERE id=%s", (id,))
    subject = cursor.fetchone()
    
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()
    
    conn.close()
    return render_template('edit_subject.html', subject=subject, courses=courses)

@app.route('/add_subject', methods=['GET', 'POST'])
def add_subject():
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        sub_code = request.form['subject_code'].strip()
        next_url = request.form.get('next_url') or request.referrer or '/manage/subjects'
        
        cursor.execute("SELECT id FROM subjects WHERE subject_code = %s", (sub_code,))
        if not cursor.fetchone():
            try: 
                cursor.execute("INSERT INTO subjects (subject_name, subject_code, course_id, semester) VALUES (%s, %s, %s, %s)", 
                               (request.form['subject_name'], sub_code, request.form['course_id'], request.form['semester']))
                conn.commit()
            except Exception as e: print(e)
        
        conn.close()
        return redirect(next_url)
        
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()
    conn.close()
    
    return render_template('add_subject.html', courses=courses, next_url=request.referrer)

@app.route('/add_department', methods=['GET', 'POST'])
def add_department():
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    if request.method == 'POST':
        course_name = request.form['new_course_name'].strip()
        conn = get_db()
        cursor = conn.cursor()
        # ഡ്യൂപ്ലിക്കേറ്റ് ഡിപ്പാർട്ട്മെന്റ് ഒഴിവാക്കാൻ
        cursor.execute("SELECT id FROM courses WHERE course_name = %s", (course_name,))
        if not cursor.fetchone():
            try: 
                cursor.execute("INSERT INTO courses (course_name) VALUES (%s)", (course_name,))
                conn.commit()
            except Exception as e: print(e)
        conn.close()
        # ഡിപ്പാർട്ട്മെന്റ് ആഡ് ചെയ്ത ശേഷം തിരികെ സബ്ജക്റ്റ് ആഡ് ചെയ്യുന്ന പേജിലേക്ക് തന്നെ പോകും
        return redirect('/add_subject')
        
    return render_template('add_department.html')

@app.route('/edit/exam/<int:id>', methods=['GET', 'POST'])
def edit_exam(id):
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            exam_name = request.form['exam_name']
            subject_id = request.form['subject_id']
            exam_date = request.form['exam_date']
            exam_time = request.form['exam_time']
            
            cursor.execute("""
                UPDATE exams 
                SET exam_name=%s, subject_id=%s, exam_date=%s, exam_time=%s 
                WHERE id=%s
            """, (exam_name, subject_id, exam_date, exam_time, id))
            conn.commit()
        except Exception as e:
            print(e)
            
        conn.close()
        return redirect('/admin/timetable')
        
    # പഴയ ഡാറ്റ ഫോമിൽ കാണിക്കാൻ
    cursor.execute("SELECT * FROM exams WHERE id=%s", (id,))
    exam = cursor.fetchone()
    
    cursor.execute("SELECT s.*, c.course_name FROM subjects s JOIN courses c ON s.course_id = c.id ORDER BY c.course_name, s.semester")
    subjects = cursor.fetchall()
    
    conn.close()
    return render_template('edit_exam.html', exam=exam, subjects=subjects)


@app.route('/delete/exam/<int:id>')
def delete_exam(id):
    if session.get('role') != 'admin': 
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor()
    # എക്സാം ഡിലീറ്റ് ചെയ്യുമ്പോൾ അതുമായി ബന്ധപ്പെട്ട സീറ്റിംഗ് അറേഞ്ച്മെന്റുകളും കളയാൻ
    cursor.execute("DELETE FROM allotment WHERE exam_id=%s", (id,))
    cursor.execute("DELETE FROM invigilation WHERE exam_id=%s", (id,))
    cursor.execute("DELETE FROM exams WHERE id=%s", (id,))
    
    conn.commit()
    conn.close()
    return redirect('/admin/timetable')

@app.route('/faculty/timetable')
def faculty_timetable():
    if session.get('role') != 'faculty': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)
    today = date.today()

    # Faculty ge ella exam galannu fetch maduttade (Admin reeti)
    cursor.execute("""
        SELECT e.*, s.subject_name, c.course_name 
        FROM exams e 
        JOIN subjects s ON e.subject_id = s.id 
        JOIN courses c ON e.course_id = c.id 
        ORDER BY e.exam_name, c.course_name, e.semester, e.exam_date ASC
    """)
    all_exams = cursor.fetchall()

    grouped_exams = {}
    for e in all_exams:
        e['is_completed'] = e['exam_date'] < today
        exam_nm = e['exam_name']
        course_nm = e['course_name']
        sem = e['semester']
        dept_sem_key = f"{course_nm}_{sem}"
        
        if exam_nm not in grouped_exams:
            grouped_exams[exam_nm] = {}
        if dept_sem_key not in grouped_exams[exam_nm]:
            grouped_exams[exam_nm][dept_sem_key] = {'course_name': course_nm, 'semester': sem, 'exams': []}
        grouped_exams[exam_nm][dept_sem_key]['exams'].append(e)

    conn.close()
    return render_template('view_timetable.html', grouped_exams=grouped_exams)


    
    # POST മെത്തേഡ് (രജിസ്റ്റർ ചെയ്യുമ്പോൾ ഉള്ളത്) താഴെ വരും...
@app.route('/register_faculty', methods=['GET', 'POST'])
def register_faculty():
    if request.method == 'POST':
        name = request.form.get('name')
        staff_id = request.form.get('staff_id') # ഇതാണ് username
        position = request.form.get('position')
        email = request.form.get('email')
        mobile = request.form.get('mobile')
        password = request.form.get('password')

        try:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)

            # 🛑 1. ഡ്യൂപ്ലിക്കേറ്റ് ഉണ്ടോ എന്ന് ചെക്ക് ചെയ്യുന്നു (Duplicate Check) 🛑
            cursor.execute("""
                SELECT username, email, mobile FROM users 
                WHERE role = 'faculty' AND (username = %s OR email = %s OR mobile = %s)
            """, (staff_id, email, mobile))
            existing_faculty = cursor.fetchone()

            if existing_faculty:
                if existing_faculty['username'] == staff_id:
                    return jsonify({"status": "error", "message": "This Staff ID / Username is already registered!"})
                elif existing_faculty['email'] == email:
                    return jsonify({"status": "error", "message": "This Email Address is already registered!"})
                elif existing_faculty['mobile'] == mobile:
                    return jsonify({"status": "error", "message": "This Mobile Number is already registered!"})

            # 🛑 2. പ്രശ്നമൊന്നും ഇല്ലെങ്കിൽ ഡാറ്റാബേസിലേക്ക് സേവ് ചെയ്യുന്നു 🛑
            query = """
                INSERT INTO users (username, password, name, email, mobile, role, position, availability, is_approved, photo, profession) 
                VALUES (%s, %s, %s, %s, %s, 'faculty', %s, 'Yes', 0, 'default.png', 'Faculty')
            """
            cursor.execute(query, (staff_id, password, name, email, mobile, position))
            
            conn.commit()
            conn.close()
            return jsonify({"status": "success"})

        except Exception as e:
            print(f"Error: {e}")
            return jsonify({"status": "error", "message": str(e)})

    return render_template('register_faculty.html')

@app.route('/assign_teacher', methods=['POST'])
def assign_teacher():
    room_id = request.form.get('room_id')
    teacher_id = request.form.get('teacher_id')
    exam_id = request.form.get('exam_id') # ഏത് എക്സാമിനാണെന്ന് അറിയാൻ

    conn = get_db()
    cursor = conn.cursor()
    
    # invigilation ടേബിളിലേക്ക് സേവ് ചെയ്യുന്നു
    query = "INSERT INTO invigilation (exam_id, room_id, teacher_id) VALUES (%s, %s, %s)"
    cursor.execute(query, (exam_id, room_id, teacher_id))
    
    # ടീച്ചറുടെ അവൈലബിലിറ്റി 'No' ആക്കുന്നു (ആ ദിവസത്തേക്ക്)
    cursor.execute("UPDATE users SET availability = 'No' WHERE id = %s", (teacher_id,))
    
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


# --- 1. പുതിയ ടൈംടേബിൾ പേജ് കാണിക്കാനുള്ള റൂട്ട് ---
@app.route('/admin/add_timetable')
def add_timetable_page():
    if session.get('role') != 'admin':
        return redirect('/login')
        
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM courses")
    courses = cursor.fetchall()
    conn.close()
    return render_template('add_timetable.html', courses=courses)

# --- 2. സബ്ജക്റ്റുകൾ AJAX വഴി ലോഡ് ചെയ്യാനുള്ള റൂട്ട് ---
# (ഇത് നിന്റെ ഫയലിൽ എവിടെയെങ്കിലും ഉണ്ടെങ്കിൽ വീണ്ടും എഴുതണ്ട)
@app.route('/get_subjects/<int:course_id>')
def get_subjects(course_id):
    try:
        conn = get_db() # allengil ninte db connection code
        cursor = conn.cursor(dictionary=True)
        # 🛑 Ividuthe query-il 'semester' koodi edukkunnu 🛑
        cursor.execute("SELECT id, subject_name, semester FROM subjects WHERE course_id = %s", (course_id,))
        subjects = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(subjects)
    except Exception as e:
        print("Error fetching subjects:", e)
        return jsonify([])

@app.route('/admin/delete_multiple_exams', methods=['POST'])
def delete_multiple_exams():
    if session.get('role') != 'admin':
        return jsonify({"status": "unauthorized"}), 403
        
    data = request.get_json()
    ids = data.get('ids', [])
    
    if ids:
        conn = get_db()
        cursor = conn.cursor()
        # ലിസ്റ്റിലുള്ള എല്ലാ ഐഡികളും ഡിലീറ്റ് ചെയ്യുന്നു
        format_strings = ','.join(['%s'] * len(ids))
        cursor.execute(f"DELETE FROM exams WHERE id IN ({format_strings})", tuple(ids))
        conn.commit()
        conn.close()
    
    return jsonify({"status": "success"})

@app.route('/api/add_room', methods=['POST'])
def add_room_api():
    try:
        data = request.get_json()
        room_no = data['room_no'].strip() # സ്പേസ് ഉണ്ടെങ്കിൽ കളയാൻ
        capacity = data['capacity']

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # 1. റൂം ഓൾറെഡി ഉണ്ടോ എന്ന് ചെക്ക് ചെയ്യുന്നു
        cursor.execute("SELECT id FROM classrooms WHERE room_no = %s", (room_no,))
        existing_room = cursor.fetchone()
        
        if existing_room:
            conn.close()
            # റൂം ഉണ്ടെങ്കിൽ എറർ മെസ്സേജ് അയക്കുന്നു
            return jsonify({"status": "exists", "message": f"'{room_no}' എന്ന പേരിൽ ഒരു റൂം ഓൾറെഡി ഉണ്ട്!"})

        # 2. പുതിയ റൂം ആണെങ്കിൽ സേവ് ചെയ്യുന്നു
        benches = int(capacity) // 2 
        cursor.execute("INSERT INTO classrooms (room_no, capacity, benches) VALUES (%s, %s, %s)", 
                       (room_no, capacity, benches))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
        
    except Exception as e:
        print("Error Adding Room:", e)
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/api/edit_room', methods=['POST'])
def edit_room_api():
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()
        
        benches = int(data['capacity']) // 2
        
        cursor.execute("UPDATE classrooms SET capacity = %s, benches = %s WHERE id = %s", 
                       (data['capacity'], benches, data['id']))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        print("Error Editing Room:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/admin/generate_seating', methods=['POST'])
def generate_seating():
    if session.get('role') != 'admin': 
        return jsonify({"status": "error"}), 403
        
    try:
        data = request.get_json()
        date_val = data['date']
        sessions = data['sessions']
        room_ids = data['rooms']
        layout = data['layout_style']
        teacher_mode = data['teacher_mode']
        teacher_mapping = data.get('teacher_mapping', {})

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        today = date.today().strftime('%Y-%m-%d')
        cursor.execute("DELETE FROM seating_publish WHERE exam_date < %s", (today,))
        
        for sess in sessions:
            cursor.execute("SELECT id FROM exams WHERE exam_date=%s AND exam_time=%s", (date_val, sess))
            current_exams = cursor.fetchall()
            
            if current_exams:
                ex_ids = [str(r['id']) for r in current_exams]
                fmt = ','.join(['%s'] * len(ex_ids))
                cursor.execute(f"DELETE FROM allotment WHERE exam_id IN ({fmt})", tuple(ex_ids))
                cursor.execute(f"DELETE FROM invigilation WHERE exam_id IN ({fmt})", tuple(ex_ids))
            
            cursor.execute("DELETE FROM seating_publish WHERE exam_date=%s AND exam_time=%s", (date_val, sess))

            if not current_exams: 
                continue

            students = []
            for ex in current_exams:
                # 🛑 students ടേബിളും is_approved ഉം ശരിയാക്കി 🛑
                cursor.execute("""
                    SELECT s.id, s.reg_no, s.name, c.course_name, %s as exam_id 
                    FROM students s 
                    JOIN subjects sub ON s.course_id = sub.course_id AND s.semester = sub.semester
                    JOIN courses c ON s.course_id = c.id
                    WHERE sub.id = (SELECT subject_id FROM exams WHERE id=%s) AND s.is_approved = 1
                """, (ex['id'], ex['id']))
                students.extend(cursor.fetchall())

            if not students: 
                continue

            if layout == 'sequential':
                students.sort(key=lambda x: str(x['reg_no']))
                
            elif layout == 'random':
                import random
                random.shuffle(students)
                
            elif layout == 'department':
                students.sort(key=lambda x: (x['course_name'], str(x['reg_no'])))
                
            elif layout == 'alternate':
                from itertools import zip_longest
                students.sort(key=lambda x: str(x['reg_no'])) 
                depts = {}
                for st in students: 
                    depts.setdefault(st['course_name'], []).append(st)
                lists = list(depts.values())
                students = [st for group in zip_longest(*lists) for st in group if st is not None]

            format_strings = ','.join(['%s'] * len(room_ids))
            cursor.execute(f"SELECT id, benches FROM classrooms WHERE id IN ({format_strings}) ORDER BY room_no", tuple(room_ids))
            available_rooms = cursor.fetchall()

            student_idx = 0
            for room in available_rooms:
                seat_no = 1
                for bench in range(1, room['benches'] + 1):
                    for side in ['Left', 'Right']:
                        if student_idx < len(students):
                            st = students[student_idx]
                            cursor.execute("INSERT INTO allotment (student_id, room_id, exam_id, seat_no, bench_no, side) VALUES (%s, %s, %s, %s, %s, %s)", 
                                           (st['id'], room['id'], st['exam_id'], seat_no, bench, side))
                            student_idx += 1
                            seat_no += 1

            if teacher_mode == 'manual':
                for r_id in room_ids:
                    t_id = teacher_mapping.get(str(r_id))
                    if t_id: 
                        cursor.execute("INSERT INTO invigilation (exam_id, room_id, faculty_id) VALUES (%s, %s, %s)", (current_exams[0]['id'], r_id, t_id))
            elif teacher_mode == 'auto':
                import random
                cursor.execute("SELECT id FROM users WHERE role='faculty'")
                faculties = [f['id'] for f in cursor.fetchall()]
                random.shuffle(faculties)
                for i, r_id in enumerate(room_ids):
                    if i < len(faculties): 
                        cursor.execute("INSERT INTO invigilation (exam_id, room_id, faculty_id) VALUES (%s, %s, %s)", (current_exams[0]['id'], r_id, faculties[i]))

            cursor.execute("REPLACE INTO seating_publish (exam_date, exam_time, status) VALUES (%s, %s, 'Draft')", (date_val, sess))

        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
        
    except Exception as e:
        print("Backend Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/admin/draft_preview', methods=['GET', 'POST'])
def draft_preview():
    if session.get('role') != 'admin': return redirect('/login')
    conn = get_db(); cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        if 'publish' in request.form:
            cursor.execute("UPDATE seating_publish SET status='Published' WHERE status='Draft'")
            conn.commit(); conn.close()
            return redirect('/admin/seatplan?msg=published')
        elif 'cancel_draft' in request.form:
            cursor.execute("SELECT exam_date, exam_time FROM seating_publish WHERE status='Draft'")
            drafts = cursor.fetchall()
            for d in drafts:
                cursor.execute("DELETE a FROM allotment a JOIN exams e ON a.exam_id = e.id WHERE e.exam_date = %s AND e.exam_time=%s", (d['exam_date'], d['exam_time']))
                cursor.execute("DELETE i FROM invigilation i JOIN exams e ON i.exam_id = e.id WHERE e.exam_date = %s AND e.exam_time=%s", (d['exam_date'], d['exam_time']))
            cursor.execute("DELETE FROM seating_publish WHERE status='Draft'")
            conn.commit(); conn.close()
            return redirect('/admin/seatplan?msg=cancelled')

    cursor.execute("""
        SELECT a.seat_no, a.bench_no, a.side, r.id as room_id, r.room_no, s.name, s.reg_no, c.course_name as dept
        FROM allotment a JOIN students s ON a.student_id = s.id JOIN classrooms r ON a.room_id = r.id 
        JOIN exams e ON a.exam_id = e.id JOIN subjects sub ON e.subject_id = sub.id JOIN courses c ON sub.course_id = c.id
        JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time
        WHERE sp.status = 'Draft' ORDER BY r.room_no, a.seat_no
    """)
    students_data = cursor.fetchall()

    cursor.execute("""
        SELECT r.id as room_id, u.name as faculty_name 
        FROM invigilation i JOIN classrooms r ON i.room_id = r.id JOIN users u ON i.faculty_id = u.id
        JOIN exams e ON i.exam_id = e.id JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time
        WHERE sp.status = 'Draft'
    """)
    faculty_data = {f['room_id']: f['faculty_name'] for f in cursor.fetchall()}
    conn.close()

    if not students_data: return redirect('/admin/seatplan')

    rooms_dict = {}
    for st in students_data:
        r_id = st['room_id']
        if r_id not in rooms_dict:
            rooms_dict[r_id] = {'room_no': st['room_no'], 'faculty': faculty_data.get(r_id, 'Not Assigned'), 'students': []}
        rooms_dict[r_id]['students'].append(st)

    return render_template('draft_preview.html', grouped_data=rooms_dict)


# --- പബ്ലിഷ് ചെയ്ത സീറ്റിംഗ് കാണാനുള്ള പുതിയ API റൂട്ടുകൾ ---
# --- 1. Published Preview (അഡ്മിനും ഫാക്കൽറ്റിക്കും കാണാൻ) ---
@app.route('/published_preview')
def published_preview():
    role = session.get('role')
    if role not in ['admin', 'faculty', 'student']: return redirect('/login')
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT a.seat_no, a.bench_no, a.side, r.id as room_id, r.room_no, s.name, s.reg_no, c.course_name as dept,
               e.exam_date, e.exam_time
        FROM allotment a 
        JOIN students s ON a.student_id = s.id 
        JOIN classrooms r ON a.room_id = r.id 
        JOIN exams e ON a.exam_id = e.id 
        JOIN subjects sub ON e.subject_id = sub.id 
        JOIN courses c ON sub.course_id = c.id
        JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time
        WHERE sp.status = 'Published' 
        ORDER BY e.exam_date DESC, e.exam_time, r.room_no, a.seat_no
    """)
    students_data = cursor.fetchall()

    cursor.execute("""
        SELECT r.id as room_id, u.name as faculty_name, e.exam_date, e.exam_time
        FROM invigilation i 
        JOIN classrooms r ON i.room_id = r.id 
        JOIN users u ON i.faculty_id = u.id
        JOIN exams e ON i.exam_id = e.id 
        JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time
        WHERE sp.status = 'Published'
    """)
    faculty_list = cursor.fetchall()
    
    # ടീച്ചറെ മാറ്റാൻ ലിസ്റ്റ് എടുക്കുന്നു
    cursor.execute("SELECT id, name FROM users WHERE role='faculty'")
    all_faculty = cursor.fetchall()
    conn.close()

    faculty_data = {}
    for f in faculty_list:
        key = f"{str(f['exam_date'])}_{f['exam_time']}_{f['room_id']}"
        faculty_data[key] = f['faculty_name']

    grouped_data = {}
    for st in students_data:
        date_session = f"Date: {st['exam_date']} | Session: {st['exam_time']}"
        if date_session not in grouped_data:
            grouped_data[date_session] = {}
            
        r_id = st['room_id']
        fac_key = f"{str(st['exam_date'])}_{st['exam_time']}_{r_id}"
        
        if r_id not in grouped_data[date_session]:
            grouped_data[date_session][r_id] = {
                'room_no': st['room_no'], 
                'faculty': faculty_data.get(fac_key, 'Not Assigned'), 
                'raw_date': str(st['exam_date']),
                'raw_time': st['exam_time'],
                'students': []
            }
        grouped_data[date_session][r_id]['students'].append(st)

    return render_template('published_preview.html', grouped_data=grouped_data, role=role, all_faculty=all_faculty)

# --- സീറ്റിംഗ് പൂർണ്ണമായി ഡിലീറ്റ് ചെയ്യാൻ ---
@app.route('/admin/delete_published_seating', methods=['POST'])
def delete_published_seating():
    if session.get('role') != 'admin': return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    date_val, time_val = data.get('date'), data.get('session')
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT id FROM exams WHERE exam_date=%s AND exam_time=%s", (date_val, time_val))
        exams = cursor.fetchall()
        if exams:
            ex_ids = [str(e[0]) for e in exams]
            fmt = ','.join(['%s'] * len(ex_ids))
            cursor.execute(f"DELETE FROM allotment WHERE exam_id IN ({fmt})", tuple(ex_ids))
            cursor.execute(f"DELETE FROM invigilation WHERE exam_id IN ({fmt})", tuple(ex_ids))
        cursor.execute("DELETE FROM seating_publish WHERE exam_date=%s AND exam_time=%s AND status='Published'", (date_val, time_val))
        conn.commit(); conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- റൂമിലെ ടീച്ചറെ മാറ്റാൻ ---
@app.route('/admin/reassign_teacher', methods=['POST'])
def reassign_teacher():
    if session.get('role') != 'admin': return jsonify({"error": "Unauthorized"}), 403
    
    data = request.get_json()
    date_val = data.get('exam_date')
    time_val = data.get('exam_time')
    target_room_id = str(data.get('room_id'))
    new_faculty_id = str(data.get('faculty_id'))
    force_swap = data.get('force_swap', False)

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        
        # ഈ ഡേറ്റിനുള്ള എല്ലാ എക്സാമുകളും എടുക്കുന്നു
        cursor.execute("SELECT id FROM exams WHERE exam_date=%s AND exam_time=%s", (date_val, time_val))
        exams = cursor.fetchall()
        if not exams:
            conn.close()
            return jsonify({"error": "No exams found for this session."})
            
        ex_ids = [str(e['id']) for e in exams]
        fmt = ','.join(['%s'] * len(ex_ids))

        # 1. പുതിയ ടീച്ചർ വേറെ ഏതെങ്കിലും റൂമിൽ ഡ്യൂട്ടിയിൽ ഉണ്ടോ എന്ന് നോക്കുന്നു
        query = f"SELECT room_id FROM invigilation WHERE faculty_id=%s AND exam_id IN ({fmt}) LIMIT 1"
        cursor.execute(query, tuple([new_faculty_id] + ex_ids))
        conflict_row = cursor.fetchone()

        if conflict_row and str(conflict_row['room_id']) != target_room_id:
            conflict_room_id = conflict_row['room_id']
            cursor.execute("SELECT room_no FROM classrooms WHERE id=%s", (conflict_room_id,))
            room_no = cursor.fetchone()['room_no']

            # Warning മെസ്സേജ് കൊടുക്കാൻ
            if not force_swap:
                conn.close()
                return jsonify({
                    "status": "conflict", 
                    "message": f"This teacher is already assigned to Room {room_no}!\n\nDo you want to swap their duties?"
                })
            else:
                # --- SWAP LOGIC (മാറ്റി ഇരുത്തുന്നു) ---
                # നിലവിൽ ഈ റൂമിൽ ഉള്ള ടീച്ചറെ കണ്ടുപിടിക്കുന്നു
                cursor.execute(f"SELECT faculty_id FROM invigilation WHERE room_id=%s AND exam_id IN ({fmt}) LIMIT 1", tuple([target_room_id] + ex_ids))
                old_fac_row = cursor.fetchone()
                old_faculty_id = old_fac_row['faculty_id'] if old_fac_row else None

                # രണ്ട് റൂമിലെയും പഴയ ഡ്യൂട്ടി കളയുന്നു
                cursor.execute(f"DELETE FROM invigilation WHERE room_id IN (%s, %s) AND exam_id IN ({fmt})", tuple([target_room_id, conflict_room_id] + ex_ids))

                # പുതിയ ടീച്ചറെ ഈ റൂമിലേക്ക് മാറ്റുന്നു
                cursor.execute("INSERT INTO invigilation (exam_id, room_id, faculty_id) VALUES (%s, %s, %s)", (exams[0]['id'], target_room_id, new_faculty_id))

                # പഴയ ടീച്ചർ ഉണ്ടെങ്കിൽ അവരെ മറ്റേ റൂമിലേക്ക് മാറ്റുന്നു
                if old_faculty_id:
                    cursor.execute("INSERT INTO invigilation (exam_id, room_id, faculty_id) VALUES (%s, %s, %s)", (exams[0]['id'], conflict_room_id, old_faculty_id))

                conn.commit(); conn.close()
                return jsonify({"status": "success"})

        # --- NORMAL UPDATE (പ്രശ്നങ്ങൾ ഒന്നുമില്ലെങ്കിൽ) ---
        cursor.execute(f"DELETE FROM invigilation WHERE room_id=%s AND exam_id IN ({fmt})", tuple([target_room_id] + ex_ids))
        if new_faculty_id:
            cursor.execute("INSERT INTO invigilation (exam_id, room_id, faculty_id) VALUES (%s, %s, %s)", (exams[0]['id'], target_room_id, new_faculty_id))
        
        conn.commit(); conn.close()
        return jsonify({"status": "success"})

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500


# --- 2. Faculty Dashboard Seating Data ---
@app.route('/faculty/seating')
def faculty_seating():
    if session.get('role') != 'faculty': return redirect('/login')
    teacher_id = session['user_id']
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # ടീച്ചറുടെ പേര് എടുക്കുന്നു
    cursor.execute("SELECT name FROM users WHERE id=%s", (teacher_id,))
    teacher = cursor.fetchone()
    
    # ടീച്ചർക്ക് ഡ്യൂട്ടി ഉള്ള റൂമുകൾ എടുക്കുന്നു
    cursor.execute("""
        SELECT i.id as duty_id, e.exam_date, e.exam_time, c.room_no, c.id as room_id
        FROM invigilation i
        JOIN exams e ON i.exam_id = e.id
        JOIN classrooms c ON i.room_id = c.id
        JOIN seating_publish sp ON e.exam_date = sp.exam_date AND e.exam_time = sp.exam_time
        WHERE i.faculty_id = %s AND sp.status = 'Published'
        ORDER BY e.exam_date DESC
    """, (teacher_id,))
    duties = cursor.fetchall()
    
    # ഓരോ ഡ്യൂട്ടിക്കും ആ റൂമിലുള്ള കുട്ടികളുടെ ലിസ്റ്റ് എടുക്കുന്നു
    for duty in duties:
        cursor.execute("""
            SELECT a.seat_no, a.bench_no, a.side, s.reg_no, s.name, crs.course_name as dept
            FROM allotment a
            JOIN students s ON a.student_id = s.id
            JOIN courses crs ON s.course_id = crs.id
            JOIN exams e ON a.exam_id = e.id
            WHERE e.exam_date=%s AND e.exam_time=%s AND a.room_id = %s
            ORDER BY a.seat_no
        """, (duty['exam_date'], duty['exam_time'], duty['room_id']))
        duty['students'] = cursor.fetchall()
        duty['student_count'] = len(duty['students']) # കുട്ടികളുടെ എണ്ണം

    conn.close()
    return render_template('faculty_seat_plan.html', duties=duties, teacher_name=teacher['name'])

@app.route('/admin/delete_timetable_group', methods=['POST'])
def delete_timetable_group():
    if session.get('role') != 'admin':
        return redirect('/login')

    exam_name = request.form.get('exam_name')
    course_id = request.form.get('course_id')
    semester = request.form.get('semester')

    try:
        conn = get_db()
        cursor = conn.cursor()
        # Aa department-nte, aa semester-ile, aa exam full aayi delete aakum
        cursor.execute("""
            DELETE FROM exams 
            WHERE exam_name = %s AND course_id = %s AND semester = %s
        """, (exam_name, course_id, semester))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Error deleting timetable group:", e)
        
    return redirect('/admin/timetable')

@app.route('/api/get_room/<int:id>', methods=['GET'])
def get_room_api(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM classrooms WHERE id = %s", (id,))
    room = cursor.fetchone()
    conn.close()
    return jsonify(room)

@app.route('/api/quick_add_room', methods=['POST'])
def quick_add_room():
    try:
        data = request.get_json()
        capacity = int(data['benches']) * 2
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO classrooms (room_no, benches, capacity) VALUES (%s, %s, %s)", 
                       (data['room_no'], data['benches'], capacity))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        print("ADD ROOM ERROR:", e)
        # എറർ എന്താണെന്ന് തിരിച്ചു ബ്രൗസറിലേക്ക് അയക്കുന്നു
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/quick_edit_room', methods=['POST'])
def quick_edit_room():
    try:
        data = request.get_json()
        capacity = int(data['benches']) * 2
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE classrooms SET room_no=%s, benches=%s, capacity=%s WHERE id=%s", 
                       (data['room_no'], data['benches'], capacity, data['id']))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        print("EDIT ROOM ERROR:", e)
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
@app.route('/admin/profile')
def admin_profile():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user_data = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('admin_profile.html', user=user_data)

# 1. എഡിറ്റ് പേജ് തുറക്കുമ്പോൾ ഡാറ്റാബേസിൽ നിന്ന് പഴയ വിവരങ്ങൾ എടുക്കാൻ
@app.route('/admin/edit_profile')
def edit_profile():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    user_id = session.get('user_id')
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user_data = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('edit_profile.html', user=user_data)

# 2. ഡാറ്റയും ഫോട്ടോയും സേവ് ചെയ്യാൻ
@app.route('/admin/update_profile', methods=['POST'])
def update_profile():
    if session.get('role') != 'admin':
        return redirect('/login')

    name = request.form.get('admin_name')
    email = request.form.get('admin_email')
    mobile = request.form.get('admin_phone')
    user_id = session.get('user_id')
    
    conn = get_db()
    # 🛑 buffered=True ചേർക്കുന്നത് നല്ലതാണ്
    cursor = conn.cursor(dictionary=True, buffered=True) 

    # 1. പഴയ ഫോട്ടോയുടെ പേര് ഡാറ്റാബേസിൽ നിന്ന് എടുക്കുന്നു
    cursor.execute("SELECT photo FROM users WHERE id=%s", (user_id,))
    current_admin = cursor.fetchone()
    
    # നിലവിലുള്ള ഫോട്ടോ അല്ലെങ്കിൽ ഡീഫോൾട്ട് സെറ്റ് ചെയ്യുന്നു
    photo_filename = current_admin['photo'] if current_admin and current_admin['photo'] else 'default.png'
    cropped_data = request.form.get('cropped_data')

    # 2. പുതിയ ഫോട്ടോ ഉണ്ടെങ്കിൽ പഴയത് കളഞ്ഞ് പുതിയത് സേവ് ചെയ്യുന്നു
    if cropped_data and ',' in cropped_data:
        try:
            # 🛑 പഴയ ഫോട്ടോ default.png അല്ലെങ്കിൽ അത് ഡിലീറ്റ് ചെയ്യുന്നു
            if current_admin and current_admin['photo'] and current_admin['photo'] != 'default.png':
                old_path = os.path.join(app.root_path, 'static', 'uploads', current_admin['photo'])
                if os.path.exists(old_path):
                    os.remove(old_path)

            # പുതിയ ഫോട്ടോ സേവ് ചെയ്യുന്നു
            header, encoded = cropped_data.split(",", 1)
            file_ext = header.split(';')[0].split('/')[1]
            
            # ക്യാഷ് ഒഴിവാക്കാൻ UUID ഉപയോഗിച്ച് പുതിയ പേര്
            photo_filename = f"admin_{user_id}_{uuid.uuid4().hex[:6]}.{file_ext}" 
            
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            
            file_path = os.path.join(upload_folder, photo_filename)
            with open(file_path, "wb") as fh:
                fh.write(base64.b64decode(encoded))
                
        except Exception as e:
            print("Error saving cropped photo:", e)

    # 3. ഡാറ്റാബേസിൽ അപ്ഡേറ്റ് ചെയ്യുന്നു
    cursor.execute("""
        UPDATE users 
        SET name=%s, email=%s, mobile=%s, photo=%s 
        WHERE id=%s
    """, (name, email, mobile, photo_filename, user_id))
    
    # സെഷൻ അപ്ഡേറ്റ് ചെയ്യുന്നു
    session['user_name'] = name 
    session['user_photo'] = photo_filename 

    conn.commit()
    cursor.close()
    conn.close()

    return redirect('/admin/profile')

# 1. പാസ്‌വേഡ് മാറ്റാനുള്ള പേജ് കാണിക്കാൻ
@app.route('/admin/change_password')
def change_password_page():
    if session.get('role') != 'admin':
        return redirect('/login')
    return render_template('change_password.html')

# 2. പാസ്‌വേഡ് ഡാറ്റാബേസിൽ അപ്‌ഡേറ്റ് ചെയ്യാൻ
@app.route('/admin/update_password', methods=['POST'])
def update_password():
    if session.get('role') != 'admin':
        return redirect('/login')

    current_p = request.form.get('current_password')
    new_p = request.form.get('new_password')
    user_id = session.get('user_id')

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # പഴയ പാസ്‌വേഡ് ചെക്ക് ചെയ്യുന്നു
    cursor.execute("SELECT password FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()

    if user and user['password'] == current_p:
        cursor.execute("UPDATE users SET password=%s WHERE id=%s", (new_p, user_id))
        conn.commit()
        # പാസ്‌വേഡ് മാറിയാൽ ലോഗൗട്ട് ചെയ്യിക്കുന്നതാണ് കൂടുതൽ സുരക്ഷിതം
        cursor.close()
        conn.close()
        return redirect('/logout') 
    else:
        cursor.close()
        conn.close()
        return "Current password incorrect! Go back and try again."



@app.route('/student/change_password', methods=['GET', 'POST'])
def student_change_password():
    if session.get('role') != 'student': 
        return redirect('/login')

    msg = ""
    msg_type = ""
    
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # 🛑 പാസ്‌വേഡ് വാലിഡേഷൻ (Regex)
        # കുറഞ്ഞത് 6 char, 1 Uppercase, 1 Number, 1 Symbol
        password_pattern = r"^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{6,}$"

        if not re.match(password_pattern, new_password):
            msg = "Error: Password must have at least 6 characters, 1 Uppercase, 1 Number, and 1 Symbol!"
            msg_type = "error"
        elif new_password != confirm_password:
            msg = "Error: New password and confirm password do not match!"
            msg_type = "error"
        else:
            conn = get_db()
            cursor = conn.cursor(dictionary=True, buffered=True)

            cursor.execute("SELECT password FROM students WHERE id=%s", (session['user_id'],))
            user = cursor.fetchone()

            if user and user['password'] == current_password:
                cursor.execute("UPDATE students SET password=%s WHERE id=%s", (new_password, session['user_id']))
                conn.commit()
                msg = "Password changed successfully!"
                msg_type = "success"
            else:
                msg = "Error: Incorrect current password!"
                msg_type = "error"
            
            cursor.close()
            conn.close()

    return render_template('student_change_password.html', msg=msg, msg_type=msg_type)

@app.route('/faculty/change_password', methods=['GET', 'POST'])
def faculty_change_password():
    if session.get('role') != 'faculty': 
        return redirect('/login')

    msg = ""
    msg_type = ""
    
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # 🛑 പാസ്‌വേഡ് വാലിഡേഷൻ (Regex)
        password_pattern = r"^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{6,}$"

        if not re.match(password_pattern, new_password):
            msg = "Error: Password must have at least 6 characters, 1 Uppercase, 1 Number, and 1 Symbol!"
            msg_type = "error"
        elif new_password != confirm_password:
            msg = "Error: New password and confirm password do not match!"
            msg_type = "error"
        else:
            conn = get_db()
            cursor = conn.cursor(dictionary=True, buffered=True)

            # നിലവിലെ പാസ്‌വേഡ് ചെക്ക് ചെയ്യുന്നു (users ടേബിളിൽ)
            cursor.execute("SELECT password FROM users WHERE id=%s", (session['user_id'],))
            user = cursor.fetchone()

            if user and user['password'] == current_password:
                cursor.execute("UPDATE users SET password=%s WHERE id=%s", (new_password, session['user_id']))
                conn.commit()
                msg = "Password changed successfully!"
                msg_type = "success"
            else:
                msg = "Error: Incorrect current password!"
                msg_type = "error"
            
            cursor.close()
            conn.close()

    return render_template('faculty_change_password.html', msg=msg, msg_type=msg_type)

if __name__ == '__main__':
    app.run(debug=True)