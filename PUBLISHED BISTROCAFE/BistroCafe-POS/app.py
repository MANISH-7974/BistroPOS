from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, Response
import os
import smtplib
import json
import threading
import io
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import csv
import requests
from datetime import datetime
from fpdf import FPDF
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, template_folder=os.path.abspath(os.path.dirname(__file__)))
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-only-change-this-secret')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'manishkushwah7974@gmail.com')
ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')
if not ADMIN_PASSWORD_HASH:
    # Keeps the college demo usable; set ADMIN_PASSWORD_HASH in deployment.
    ADMIN_PASSWORD_HASH = generate_password_hash(os.getenv('ADMIN_PASSWORD', 'BistroCafe'))

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INVOICES_DIR = os.path.join(BASE_DIR, 'invoices')
CSV_FILE = os.path.join(BASE_DIR, 'daily_sales.csv')
INVENTORY_FILE = os.path.join(BASE_DIR, 'inventory.json')
INVENTORY_LOCK = threading.Lock()

DEFAULT_INVENTORY = {
    'Paneer Tikka': {'stock': 20, 'threshold': 5},
    'Veg Biryani': {'stock': 20, 'threshold': 5},
    'Dal Makhani': {'stock': 20, 'threshold': 5},
    'Butter Chicken': {'stock': 20, 'threshold': 5},
    'Garlic Naan': {'stock': 30, 'threshold': 8},
    'Chole Bhature': {'stock': 20, 'threshold': 5},
    'Veg Burger': {'stock': 20, 'threshold': 5},
    'Chicken Burger': {'stock': 20, 'threshold': 5},
    'Cheese Burger': {'stock': 20, 'threshold': 5},
    'Spicy Paneer': {'stock': 20, 'threshold': 5},
    'Double Patty': {'stock': 20, 'threshold': 5},
    'Mushroom Swiss': {'stock': 20, 'threshold': 5},
    'French Fries': {'stock': 30, 'threshold': 8},
    'Peri Peri Fries': {'stock': 25, 'threshold': 6},
    'Garlic Bread': {'stock': 25, 'threshold': 6},
    'Onion Rings': {'stock': 25, 'threshold': 6},
    'Chicken Nuggets': {'stock': 25, 'threshold': 6},
    'Loaded Nachos': {'stock': 20, 'threshold': 5},
    'Cold Coffee': {'stock': 30, 'threshold': 8},
    'Oreo Shake': {'stock': 25, 'threshold': 6},
    'Masala Chai': {'stock': 40, 'threshold': 10},
    'Fresh Lime Soda': {'stock': 30, 'threshold': 8},
    'Mango Lassi': {'stock': 25, 'threshold': 6},
    'Virgin Mojito': {'stock': 25, 'threshold': 6}
}

if not os.path.exists(INVOICES_DIR):
    os.makedirs(INVOICES_DIR)

if not os.path.exists(INVENTORY_FILE):
    with open(INVENTORY_FILE, 'w') as file:
        json.dump(DEFAULT_INVENTORY, file, indent=2)

def load_inventory():
    try:
        with open(INVENTORY_FILE, 'r') as file:
            inventory = json.load(file)
        return inventory
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_INVENTORY.copy()

def save_inventory(inventory):
    temporary_file = INVENTORY_FILE + '.tmp'
    with open(temporary_file, 'w') as file:
        json.dump(inventory, file, indent=2)
    os.replace(temporary_file, INVENTORY_FILE)

def inventory_status(item):
    stock = int(item.get('stock', 0))
    threshold = int(item.get('threshold', 0))
    if stock <= 0:
        return 'out'
    if stock <= threshold:
        return 'low'
    return 'healthy'

def normalize_sales_row(row):
    """Keep older CSV rows compatible with the payment-method column."""
    extra = row.pop(None, []) if isinstance(row, dict) else []
    if not isinstance(extra, list):
        extra = [extra]
    row['Payment Method'] = row.get('Payment Method') or (extra[0] if extra and extra[0] else 'Cash')
    return row

# --- LOGIN & AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        
        if user == ADMIN_EMAIL and check_password_hash(ADMIN_PASSWORD_HASH, pwd):
            session.clear()
            session['role'] = 'admin'
            session.permanent = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('login.html', error="Invalid Credentials. Try again.")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('role', None)
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    # 1. Security Check
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    # 2. Setup Data Variables
    total_revenue = 0
    total_orders = 0
    today_revenue = 0
    today_orders = 0
    recent_orders = []
    inventory = load_inventory()
    inventory_items = []
    low_stock_count = 0
    out_of_stock_count = 0
    filter_start = request.args.get('start_date', '')
    filter_end = request.args.get('end_date', '')
    item_counts = {}
    date_revenue = {}
    month_revenue = {} 
    
    # 3. Read the Flat-File Database
    if os.path.isfile(CSV_FILE):
        with open(CSV_FILE, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                row = normalize_sales_row(row)
                row_date = row.get('Date', '')
                if filter_start and row_date < filter_start:
                    continue
                if filter_end and row_date > filter_end:
                    continue

                total_orders += 1
                try:
                    rev = float(row.get('Total (Rs)', 0))
                    total_revenue += rev
                    
                    date = row_date or 'Unknown'
                    date_revenue[date] = date_revenue.get(date, 0) + rev

                    if date == datetime.now().strftime('%Y-%m-%d'):
                        today_revenue += rev
                        today_orders += 1
                    
                    if date != 'Unknown' and len(date) >= 7:
                        month = date[:7] 
                        month_revenue[month] = month_revenue.get(month, 0) + rev
                except ValueError:
                    pass

                recent_orders.append({
                    'invoice': row.get('Invoice', '—'),
                    'date': row.get('Date', '—'),
                    'time': row.get('Time', '—'),
                    'token': row.get('Token', '—'),
                    'table': row.get('Table', '—'),
                    'customer': row.get('Customer', 'Guest'),
                    'items': row.get('Items', '—'),
                    'total': row.get('Total (Rs)', '0.00'),
                    'payment': row.get('Payment Method') or 'Cash'
                })
                
                items_str = row.get('Items', '')
                if items_str:
                    parts = items_str.split(', ') 
                    for part in parts:
                        try:
                            qty_str, name = part.split('x ', 1)
                            item_counts[name] = item_counts.get(name, 0) + int(qty_str)
                        except:
                            pass
                            
    # 4. Sort and format data for Chart.js
    top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)
    for name, details in inventory.items():
        inventory_items.append({
            'name': name,
            'stock': int(details.get('stock', 0)),
            'threshold': int(details.get('threshold', 0)),
            'status': inventory_status(details)
        })
        if inventory_status(details) == 'low':
            low_stock_count += 1
        elif inventory_status(details) == 'out':
            out_of_stock_count += 1
    inventory_items.sort(key=lambda item: (item['status'] == 'healthy', item['stock']))
    
    recent_orders = recent_orders[-12:][::-1]
    average_order_value = total_revenue / total_orders if total_orders else 0

    return render_template('admin.html', 
                           total_revenue=f"{total_revenue:,.2f}", 
                           total_orders=total_orders,
                           today_revenue=f"{today_revenue:,.2f}",
                           today_orders=today_orders,
                           average_order_value=f"{average_order_value:,.2f}",
                           recent_orders=recent_orders,
                           inventory_items=inventory_items,
                           low_stock_count=low_stock_count,
                           out_of_stock_count=out_of_stock_count,
                           filter_start=filter_start,
                           filter_end=filter_end,
                           top_items=top_items[:5], 
                           pie_labels=[item[0] for item in top_items[:5]], 
                           pie_data=[item[1] for item in top_items[:5]],
                           daily_labels=list(date_revenue.keys())[-7:],
                           daily_data=list(date_revenue.values())[-7:],
                           monthly_labels=list(month_revenue.keys())[-12:],
                           monthly_data=list(month_revenue.values())[-12:])

@app.route('/admin/inventory/update', methods=['POST'])
def update_inventory():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    item_name = request.form.get('item_name', '').strip()
    try:
        stock = max(0, int(request.form.get('stock', 0)))
        threshold = max(0, int(request.form.get('threshold', 0)))
    except ValueError:
        return redirect(url_for('admin_dashboard'))

    with INVENTORY_LOCK:
        inventory = load_inventory()
        if item_name in inventory:
            inventory[item_name] = {'stock': stock, 'threshold': threshold}
            save_inventory(inventory)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/export')
def export_sales():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    output = io.StringIO()
    if os.path.isfile(CSV_FILE):
        with open(CSV_FILE, mode='r', newline='') as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames or []
            if 'Payment Method' not in fieldnames:
                fieldnames.append('Payment Method')
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                row = normalize_sales_row(row)
                row_date = row.get('Date', '')
                if start_date and row_date < start_date:
                    continue
                if end_date and row_date > end_date:
                    continue
                writer.writerow({field: row.get(field, '') for field in fieldnames})
    return Response(output.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=BistroCafe_sales_report.csv'
    })

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/manus-routes.json')
def manus_routes():
    return jsonify({
        'routes': [
            {'path': '/', 'title': 'BistroCafe POS'},
            {'path': '/login', 'title': 'Manager login'},
            {'path': '/admin', 'title': 'Manager dashboard'}
        ]
    })

def get_next_token(today_date):
    token = 1
    filename = CSV_FILE
    if os.path.isfile(filename):
        with open(filename, mode='r') as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) > 2 and row[1] == today_date:
                    token += 1
    return token

@app.route('/api/inventory')
def inventory_api():
    inventory = load_inventory()
    return jsonify({
        name: {
            'stock': int(details.get('stock', 0)),
            'threshold': int(details.get('threshold', 0)),
            'status': inventory_status(details)
        }
        for name, details in inventory.items()
    })

@app.route('/process_order', methods=['POST'])
def process_order():
    order_data = request.get_json()
    
    table_no = order_data.get('table_no', 'N/A')
    customer = order_data.get('customer_name', 'Guest')
    customer_email = order_data.get('email', '') 
    payment_method = order_data.get('payment_method', 'Cash')
    if payment_method not in {'Cash', 'UPI', 'Card'}:
        return jsonify({'status': 'error', 'message': 'Please select a valid payment method.'}), 400
    try:
        discount_pct = float(order_data.get('discount') or 0)
        tax_rate = float(order_data.get('tax_rate', 5))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Discount and GST must be valid numbers.'}), 400
    if discount_pct < 0 or discount_pct > 100:
        return jsonify({'status': 'error', 'message': 'Discount must be between 0% and 100%.'}), 400
    if tax_rate not in {0, 5, 12}:
        return jsonify({'status': 'error', 'message': 'Please select a valid GST slab.'}), 400
    cart_items = order_data.get('cart', [])
    if not isinstance(cart_items, list) or not cart_items:
        return jsonify({'status': 'error', 'message': 'Your cart is empty.'}), 400
    if customer_email and ('@' not in customer_email or '.' not in customer_email.split('@')[-1]):
        return jsonify({'status': 'error', 'message': 'Please enter a valid customer email.'}), 400
    for item in cart_items:
        try:
            if int(item.get('qty', 0)) <= 0 or float(item.get('price', 0)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'Order quantities and prices must be valid.'}), 400

    with INVENTORY_LOCK:
        inventory = load_inventory()
        # Pass 1: Verify all cart items have enough stock before deducting anything
        for item in cart_items:
            item_name = item.get('name', '')
            requested_qty = int(item.get('qty', 0))
            stock_record = inventory.get(item_name)
            available_stock = int(stock_record.get('stock', 0)) if stock_record else 0
            if not stock_record or requested_qty > available_stock:
                return jsonify({
                    'status': 'error',
                    'message': f"{item_name} has only {available_stock} left in stock."
                }), 409
                
        # Pass 2: Deduct purchased quantities and save atomically to inventory.json
        for item in cart_items:
            item_name = item.get('name', '')
            requested_qty = int(item.get('qty', 0))
            inventory[item_name]['stock'] = int(inventory[item_name].get('stock', 0)) - requested_qty
        save_inventory(inventory)
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    # Include microseconds so multiple counter orders in the same second never overwrite a PDF.
    invoice_no = datetime.now().strftime("%Y%m%d%H%M%S%f")
    
    daily_token = get_next_token(current_date)
    
    subtotal = sum(float(item['price']) * int(item['qty']) for item in cart_items)
    discount_amt = subtotal * (discount_pct / 100)
    discounted_sub = subtotal - discount_amt
    
    half_tax = tax_rate / 2
    total_tax_amt = discounted_sub * (tax_rate / 100)
    cgst = total_tax_amt / 2
    sgst = total_tax_amt / 2
    grand_total = discounted_sub + cgst + sgst
    
    items_summary = ", ".join([f"{item['qty']}x {item['name']}" for item in cart_items])
    filename = CSV_FILE
    file_exists = os.path.isfile(filename)
    
    try:
        with open(filename, mode='a', newline='') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["Invoice", "Date", "Time", "Token", "Table", "Customer", "Items", "Total (Rs)", "Payment Method"])
            writer.writerow([invoice_no, current_date, current_time, daily_token, table_no, customer, items_summary, round(grand_total, 2), payment_method, 'New'])
    except Exception as e:
        print(f"CSV Error: {e}")

    # 4. PREMIUM FPDF INVOICE GENERATION
    try:
        pdf = FPDF(format='A5')
        pdf.set_margins(10, 10, 10)
        pdf.set_auto_page_break(True, margin=16)
        pdf.add_page()
        page_width = 128.5

        # --- Premium brand header ---
        pdf.set_fill_color(22, 79, 58)       # Bistro forest green
        pdf.rect(0, 0, 148.5, 43, 'F')
        pdf.set_fill_color(241, 189, 97)     # Bistro gold accent
        pdf.rect(0, 0, 148.5, 3, 'F')
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 23)
        pdf.set_xy(10, 10)
        pdf.cell(page_width, 9, 'BISTROCAFE', ln=True, align='L')
        pdf.set_text_color(207, 229, 216)
        pdf.set_font('Arial', '', 8)
        pdf.cell(page_width, 5, 'CRAFTED FOOD  |  WARM HOSPITALITY  |  HAPPY TABLES', ln=True)
        pdf.set_font('Arial', '', 7)
        pdf.cell(page_width, 5, 'Gwalior  |  +91-9876543210  |  GSTIN: 23ABCDE1234F1Z5', ln=True)

        # --- Invoice title and token ---
        pdf.set_y(51)
        pdf.set_text_color(22, 79, 58)
        pdf.set_font('Arial', 'B', 17)
        pdf.cell(78, 8, 'TAX INVOICE', ln=False)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 7)
        pdf.cell(50.5, 5, 'ORIGINAL FOR RECIPIENT', ln=True, align='R')
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 8)
        pdf.cell(78, 5, 'A dining receipt from BistroCafe', ln=False)
        pdf.set_text_color(22, 79, 58)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(50.5, 5, f'INVOICE #{invoice_no}', ln=True, align='R')

        # Token highlight card
        pdf.ln(7)
        pdf.set_fill_color(247, 244, 235)
        pdf.set_draw_color(241, 189, 97)
        pdf.rect(10, pdf.get_y(), page_width, 19, 'DF')
        token_y = pdf.get_y()
        pdf.set_xy(16, token_y + 4)
        pdf.set_text_color(117, 93, 47)
        pdf.set_font('Arial', 'B', 7)
        pdf.cell(42, 4, 'ORDER TOKEN', ln=True)
        pdf.set_x(16)
        pdf.set_text_color(22, 79, 58)
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(42, 8, f'#{daily_token}', ln=False)
        pdf.set_xy(72, token_y + 4)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 7)
        pdf.cell(28, 4, 'DATE / TIME', ln=False)
        pdf.set_text_color(35, 48, 41)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(28, 4, f'{current_date}  {current_time}', ln=True, align='R')
        pdf.set_xy(72, token_y + 10)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 7)
        pdf.cell(28, 4, 'TABLE', ln=False)
        pdf.set_text_color(35, 48, 41)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(28, 4, str(table_no)[:14], ln=True, align='R')

        # Customer information strip
        pdf.set_y(token_y + 27)
        pdf.set_fill_color(250, 251, 249)
        pdf.set_draw_color(226, 232, 227)
        pdf.rect(10, pdf.get_y(), page_width, 17, 'DF')
        customer_y = pdf.get_y()
        pdf.set_xy(15, customer_y + 4)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 7)
        pdf.cell(25, 4, 'BILLED TO', ln=False)
        pdf.set_text_color(35, 48, 41)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(37, 4, str(customer or 'Guest')[:22], ln=False)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 7)
        pdf.cell(24, 4, 'PAYMENT', ln=False)
        pdf.set_text_color(35, 48, 41)
        pdf.set_font('Arial', 'B', 8)
        pdf.cell(37, 4, payment_method, ln=True, align='R')
        pdf.set_x(15)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 7)
        pdf.cell(25, 4, 'EMAIL RECEIPT', ln=False)
        pdf.set_text_color(35, 48, 41)
        pdf.set_font('Arial', '', 7)
        pdf.set_x(40)
        pdf.cell(98.5, 4, (customer_email if customer_email else 'Not requested')[:42], ln=True, align='L')

        # Item table
        pdf.set_y(customer_y + 25)
        pdf.set_fill_color(22, 79, 58)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Arial', 'B', 7)
        pdf.cell(59, 9, '  ITEM DESCRIPTION', ln=False, fill=True)
        pdf.cell(15, 9, 'QTY', ln=False, align='C', fill=True)
        pdf.cell(27, 9, 'RATE', ln=False, align='R', fill=True)
        pdf.cell(27.5, 9, 'AMOUNT  ', ln=True, align='R', fill=True)

        for index, item in enumerate(cart_items):
            i_price = float(item['price'])
            i_qty = int(item['qty'])
            i_total = i_price * i_qty
            if index % 2 == 0:
                pdf.set_fill_color(247, 250, 247)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(35, 48, 41)
            pdf.set_font('Arial', 'B', 8)
            pdf.cell(59, 9, f"  {str(item['name'])[:25]}", ln=False, fill=True)
            pdf.set_font('Arial', '', 8)
            pdf.cell(15, 9, str(i_qty), ln=False, align='C', fill=True)
            pdf.cell(27, 9, f'Rs {i_price:.2f}', ln=False, align='R', fill=True)
            pdf.set_font('Arial', 'B', 8)
            pdf.cell(27.5, 9, f'Rs {i_total:.2f}  ', ln=True, align='R', fill=True)
            pdf.set_draw_color(229, 236, 231)
            pdf.line(10, pdf.get_y(), 138.5, pdf.get_y())

        # Totals card
        pdf.ln(7)
        totals_y = pdf.get_y()
        pdf.set_fill_color(250, 251, 249)
        pdf.set_draw_color(226, 232, 227)
        pdf.rect(66, totals_y, 72.5, 39 if discount_pct > 0 else 32, 'DF')
        pdf.set_x(72)
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 8)
        pdf.cell(33, 6, 'Subtotal', ln=False, align='R')
        pdf.set_text_color(35, 48, 41)
        pdf.cell(33, 6, f'Rs {subtotal:.2f}', ln=True, align='R')
        if discount_pct > 0:
            pdf.set_x(72)
            pdf.set_text_color(112, 128, 119)
            pdf.cell(33, 6, f'Discount ({discount_pct:g}%)', ln=False, align='R')
            pdf.set_text_color(207, 79, 61)
            pdf.cell(33, 6, f'- Rs {discount_amt:.2f}', ln=True, align='R')
        pdf.set_x(72)
        pdf.set_text_color(112, 128, 119)
        pdf.cell(33, 6, f'CGST ({half_tax:g}%)', ln=False, align='R')
        pdf.set_text_color(35, 48, 41)
        pdf.cell(33, 6, f'Rs {cgst:.2f}', ln=True, align='R')
        pdf.set_x(72)
        pdf.set_text_color(112, 128, 119)
        pdf.cell(33, 6, f'SGST ({half_tax:g}%)', ln=False, align='R')
        pdf.set_text_color(35, 48, 41)
        pdf.cell(33, 6, f'Rs {sgst:.2f}', ln=True, align='R')
        pdf.set_fill_color(22, 79, 58)
        pdf.set_text_color(255, 255, 255)
        pdf.set_x(66)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(72.5, 11, f'  GRAND TOTAL                         Rs {grand_total:.2f}', ln=True, fill=True)

        # Footer: follow the totals block so short invoices never overlap the grand total.
        footer_y = max(177, pdf.get_y() + 4)
        if footer_y + 14 > 208:
            pdf.add_page()
            footer_y = pdf.get_y() + 4
        pdf.set_y(footer_y)
        pdf.set_draw_color(241, 189, 97)
        pdf.line(10, pdf.get_y(), 138.5, pdf.get_y())
        pdf.set_y(pdf.get_y() + 2)
        pdf.set_text_color(22, 79, 58)
        pdf.set_font('Arial', 'B', 7)
        pdf.cell(page_width, 3, 'THANK YOU FOR DINING WITH US', ln=True, align='C')
        pdf.set_text_color(112, 128, 119)
        pdf.set_font('Arial', '', 6)
        pdf.cell(page_width, 3, 'Keep this invoice for your records  |  Visit us again at BistroCafe', ln=True, align='C')
        pdf.set_text_color(166, 178, 169)
        pdf.set_font('Arial', '', 5)
        pdf.cell(page_width, 3, 'This is a computer-generated invoice and does not require a signature.', ln=True, align='C')

        pdf_filename = os.path.join(INVOICES_DIR, f'Invoice_{invoice_no}.pdf')
        pdf.output(pdf_filename)

    except Exception as e:
        print(f'PDF Error: {e}')
        return jsonify({'status': 'error', 'message': 'Failed to generate PDF.'}), 500

    # 5. AUTOMATED CRM EMAIL NOTIFICATION (FOREST GREEN & GOLD LUXURY THEME)
    email_sent = False
    email_error = ''
    if customer_email and '@' in customer_email and os.getenv('SMTP_SENDER_EMAIL') and os.getenv('SMTP_APP_PASSWORD'):
        try:
            sender_email = os.getenv('SMTP_SENDER_EMAIL')
            app_password = os.getenv('SMTP_APP_PASSWORD')
            
            msg = MIMEMultipart()
            msg['From'] = f"BistroCafe Gwalior <{sender_email}>"
            msg['To'] = customer_email
            msg['Subject'] = f"Tax Invoice & Order Token #{daily_token} | BistroCafe"
            
            # Forest Green & Bistro Gold HTML Email Body
            body = f"""
            <div style="font-family: 'DM Sans', 'Segoe UI', Arial, sans-serif; max-width: 520px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e5e9e5; border-radius: 20px; overflow: hidden; box-shadow: 0 18px 45px rgba(22, 79, 58, 0.08);">
                
                <!-- Gold Top Accent Bar -->
                <div style="height: 5px; background-color: #f1bd61;"></div>

                <!-- Forest Green Header -->
                <div style="background: linear-gradient(135deg, #164f3a, #1e6b4d); padding: 36px 24px; text-align: center;">
                    <h1 style="color: #ffffff; font-family: Georgia, serif; margin: 0; font-size: 28px; letter-spacing: 0.5px;">BistroCafe</h1>
                    <p style="color: #cfe5d8; margin: 6px 0 0 0; font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px;">Crafted Food &middot; Warm Hospitality</p>
                </div>
                
                <div style="padding: 34px 30px;">
                    <p style="font-size: 16px; color: #19211d; margin-top: 0;">Hi <b>{customer}</b>,</p>
                    <p style="font-size: 14px; color: #718078; line-height: 1.6;">Thank you for dining at BistroCafe. Your official GST tax invoice is attached to this email as a PDF for your records.</p>
                    
                    <!-- Cream & Gold Token Highlight Box -->
                    <div style="background-color: #f7f4eb; border-radius: 14px; padding: 24px; margin: 26px 0; text-align: center; border: 1.5px solid #f1bd61;">
                        <p style="margin: 0; font-size: 11px; color: #755d2f; font-weight: bold; text-transform: uppercase; letter-spacing: 1.5px;">Order Token</p>
                        <h2 style="margin: 8px 0 0 0; color: #164f3a; font-size: 44px; letter-spacing: -1px;">#{daily_token}</h2>
                    </div>
                    
                    <!-- Order Summary Table -->
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 26px; font-size: 14px;">
                        <tr>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; color: #718078; font-weight: 600;">Invoice Number</td>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; text-align: right; color: #19211d; font-family: monospace; font-weight: bold;">#{invoice_no}</td>
                        </tr>
                        <tr>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; color: #718078; font-weight: 600;">Table / Reference</td>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; text-align: right; color: #19211d; font-weight: bold;">{table_no}</td>
                        </tr>
                        <tr>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; color: #718078; font-weight: 600;">Items Ordered</td>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; text-align: right; color: #19211d; font-weight: 600;">{items_summary}</td>
                        </tr>
                        <tr>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; color: #718078; font-weight: 600;">Payment Method</td>
                            <td style="padding: 11px 0; border-bottom: 1px solid #e5e9e5; text-align: right; color: #19211d; font-weight: 700;">{payment_method}</td>
                        </tr>
                        <tr>
                            <td style="padding: 14px 0 6px 0; color: #19211d; font-weight: 700; text-transform: uppercase; font-size: 12px; letter-spacing: 1px;">Grand Total Paid</td>
                            <td style="padding: 14px 0 6px 0; text-align: right; font-size: 22px; font-weight: 800; color: #1e6b4d;">Rs {grand_total:.2f}</td>
                        </tr>
                    </table>
                    
                    <!-- Forest Green QR Code -->
                    <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px dashed #dce4de;">
                        <p style="font-size: 12px; color: #718078; margin-bottom: 12px; font-weight: 600;">Present this QR code for 10% off your next visit</p>
                        <img src="https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=BistroCafe-VIP-{invoice_no}&color=164f3a&bgcolor=f6f8f4" alt="Discount QR Code" style="width: 105px; height: 105px; border-radius: 10px; padding: 6px; border: 1px solid #e5e9e5;">
                    </div>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #f6f8f4; padding: 18px; text-align: center; border-top: 1px solid #e5e9e5;">
                    <p style="font-size: 12px; color: #718078; margin: 0; font-weight: 600;">BistroCafe Gwalior &copy; 2026 &middot; All Rights Reserved</p>
                    <p style="font-size: 11px; color: #9aa9a0; margin: 4px 0 0 0;">GSTIN: 23ABCDE1234F1Z5</p>
                </div>
            </div>
            """
            msg.attach(MIMEText(body, 'html'))
            
            # Attach the generated PDF Invoice
            try:
                with open(pdf_filename, "rb") as fil:
                    part = MIMEApplication(fil.read(), Name=os.path.basename(pdf_filename))
                part['Content-Disposition'] = f'attachment; filename="BistroCafe_Invoice_{invoice_no}.pdf"'
                msg.attach(part)
            except Exception as pdf_err:
                print(f"--- Could not attach PDF: {pdf_err} ---")

            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)
            server.quit()
            email_sent = True
            
            print(f"--- Email successfully sent to {customer_email} WITH PDF ATTACHMENT ---")
            
        except Exception as e:
            email_error = 'Email delivery failed.'
            print(f"--- Email Delivery Failed: {e} ---")
    elif customer_email:
        email_error = 'Email service is not configured.'

    # 6. Send payload back to JS
    return jsonify({
        "status": "success",
        "message": "Success! CSV updated and PDF generated.",
        "invoice_no": invoice_no,
        "token": daily_token,
        "payment_method": payment_method,
        "status": 'success',
        "email_requested": bool(customer_email),
        "email_sent": email_sent,
        "email_message": 'Email sent successfully.' if email_sent else (email_error or 'No email requested.')
    })

@app.route('/download_invoice/<invoice_no>')
def download_invoice(invoice_no):
    file_path = os.path.join(INVOICES_DIR, f"Invoice_{invoice_no}.pdf")
    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return f"File not found. System Error: {e}", 404

@app.route('/view_invoice/<invoice_no>')
def view_invoice(invoice_no):
    file_path = os.path.join(INVOICES_DIR, f"Invoice_{invoice_no}.pdf")
    try:
        return send_file(file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e:
        return f"File not found. System Error: {e}", 404

if __name__ == '__main__':
    app.run(debug=True)
