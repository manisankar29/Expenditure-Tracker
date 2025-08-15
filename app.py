from flask import Flask, render_template, request, redirect, session
from supabase_config import supabase, auth
from datetime import datetime, timedelta, timezone
import os, requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = auth.sign_up({"email": email, "password": password})
            uid = user.user.id
            supabase.table("user_roles").insert({"user_id": uid, "role": "user"}).execute()
            return redirect('/')
        except Exception as e:
            return str(e)
    return render_template('signup.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    try:
        user = auth.sign_in_with_password({"email": email, "password": password})
        uid = user.user.id
        session['user_id'] = uid
        session['email'] = email
        role_data = supabase.table("user_roles").select("role").eq("user_id", uid).execute().data
        session['role'] = role_data[0]['role'] if role_data else 'user'

        meta = supabase.table("user_metadata").select("username").eq("id", uid).execute().data
        if not meta or not meta[0].get("username"):
            return redirect('/setup-username')

        return redirect('/dashboard')
    except Exception as e:
        return str(e)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        try:
            redirect_url = "http://localhost:5000/reset-password"
            auth.reset_password_for_email(email, options={"redirect_to": redirect_url})
            return "✅ Password reset email sent. Check your inbox."
        except Exception as e:
            return f"❌ Error sending reset email: {e}"

    return render_template('forgot_password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    token = request.args.get('access_token') or request.form.get('access_token')
    if not token:
        return render_template('extract_token.html')  

    if request.method == 'POST':
        new_password = request.form.get('password')

        url = f"{os.getenv('SUPABASE_URL')}/auth/v1/user"
        headers = {
            "apikey": os.getenv('SUPABASE_KEY'),
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        body = {
            "password": new_password
        }

        response = requests.put(url, headers=headers, json=body)

        if response.status_code == 200:
            return redirect('/')
        else:
            return f"❌ Error resetting password: {response.json()}"

    return render_template('reset_password.html', token=token)

@app.route('/setup-username', methods=['GET', 'POST'])
def setup_username():
    if 'user_id' not in session:
        return redirect('/')

    uid = session['user_id']

    if request.method == 'POST':
        username = request.form['username']
        existing = supabase.table("user_metadata").select("*").eq("id", uid).execute().data
        if not existing:
            supabase.table("user_metadata").insert({
                "id": uid,
                "username": username
            }).execute()
        return redirect('/dashboard')

    return render_template('setup_username.html', email=session.get('email'))

@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user_id' not in session:
        return redirect('/')

    uid = session['user_id']
    role = session.get('role', 'user')

    username = None
    user_meta = supabase.table("user_metadata").select("username").eq("id", uid).execute().data
    if user_meta and user_meta[0].get("username"):
        username = user_meta[0]["username"]
    else:
        return redirect('/setup-username')

    if role == 'admin':
        data = supabase.table("expenses").select("*").execute().data
        return render_template('dashboard_admin.html', data=data)

    page = int(request.args.get("page", 1))
    sort = request.args.get("sort", "desc")
    per_page = 15

    data = supabase.table("expenses").select("*").eq("user_id", uid).execute().data

    def parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        except:
            return datetime.now(timezone.utc)

    sorted_data = sorted(data, key=lambda x: x['created_at'], reverse=(sort == "desc"))

    total_spent = sum(float(e['amount']) for e in sorted_data)
    today = datetime.now(timezone.utc)
    start_week = today - timedelta(days=today.weekday())
    start_week = start_week.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_year = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    weekly_total = sum(float(e['amount']) for e in sorted_data if parse_date(e['created_at']) >= start_week)
    monthly_total = sum(float(e['amount']) for e in sorted_data if parse_date(e['created_at']) >= start_month)
    yearly_total = sum(float(e['amount']) for e in sorted_data if parse_date(e['created_at']) >= start_year)

    start = (page - 1) * per_page
    end = start + per_page
    paginated = sorted_data[start:end]

    return render_template('dashboard_user.html',
                           username=username,
                           data=paginated,
                           weekly_total=weekly_total,
                           monthly_total=monthly_total,
                           yearly_total=yearly_total,
                           total_spent=total_spent,
                           page=page,
                           sort=sort,
                           total=len(sorted_data))

@app.route('/add', methods=['GET', 'POST'])
def add_expense():
    if 'user_id' not in session:
        return redirect('/')

    user_id = session['user_id']

    if request.method == 'POST':
        category = request.form['category']
        amount = float(request.form['amount'])
        supabase.table("expenses").insert({
            "user_id": user_id,
            "category": category,
            "amount": amount
        }).execute()
        return redirect('/add') 

    page = int(request.args.get("page", 1))
    sort = request.args.get("sort", "desc")
    per_page = 50

    all_expenses = supabase.table("expenses").select("*").eq("user_id", user_id).execute().data

    all_expenses.sort(key=lambda x: x['created_at'], reverse=(sort == "desc"))

    start = (page - 1) * per_page
    end = start + per_page
    paginated = all_expenses[start:end]

    categories = supabase.table("categories").select("name").execute().data
    return render_template('add_expense.html',
                           categories=categories,
                           expenses=paginated,
                           sort=sort,
                           page=page,
                           total=len(all_expenses))

@app.route('/delete', methods=['POST'])
def delete_expense():
    if 'user_id' not in session:
        return redirect('/')
    expense_id = request.form['expense_id']
    supabase.table("expenses").delete().eq("id", expense_id).execute()
    return redirect('/add')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
