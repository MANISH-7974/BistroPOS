from flask import Flask, render_template, request, jsonify, send_file
import csv
import os
from datetime import datetime
from fpdf import FPDF

app = Flask(__name__)

# Ensure invoices folder exists
if not os.path.exists('invoices'):
    os.makedirs('invoices')

# --- NEW: Helper Function to Calculate Daily Token ---
def get_next_token(today_date):
    token = 1
    filename = "daily_sales.csv"
    if os.path.isfile(filename):
        with open(filename, mode='r') as file:
            reader = csv.reader(file)
            for row in reader:
                # Check if the date in the CSV row matches today
                if len(row) > 2 and row[1] == today_date:
                    token += 1
    return token

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/process_order', methods=['POST'])
def process_order():
    order_data = request.get_json()
    
    # 1. Extract frontend data
    order_type = order_data.get('order_type', 'Dine-In')
    table_no = order_data.get('table_no', 'N/A')
    customer = order_data.get('customer_name', 'Guest')
    phone = order_data.get('phone_number', '')
    discount_pct = float(order_data.get('discount') or 0)
    cart_items = order_data.get('cart', [])
    tax_rate = float(order_data.get('tax_rate', 5))
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    invoice_no = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # --- NEW: Get today's Token Number ---
    daily_token = get_next_token(current_date)
    
    # 2. Re-calculate math for security
    subtotal = sum(float(item['price']) * int(item['qty']) for item in cart_items)
    discount_amt = subtotal * (discount_pct / 100)
    discounted_sub = subtotal - discount_amt
    
    half_tax = tax_rate / 2
    total_tax_amt = discounted_sub * (tax_rate / 100)
    cgst = total_tax_amt / 2
    sgst = total_tax_amt / 2
    grand_total = discounted_sub + cgst + sgst
    
    # 3. CSV LOGGING (Added Token Column)
    items_summary = ", ".join([f"{item['qty']}x {item['name']}" for item in cart_items])
    filename = "daily_sales.csv"
    file_exists = os.path.isfile(filename)
    
    try:
        with open(filename, mode='a', newline='') as file:
            writer = csv.writer(file)
            if not file_exists:
                # Added "Token" to the headers
                writer.writerow(["Invoice", "Date", "Time", "Token", "Type", "Table", "Customer", "Items", "Total (Rs)"])
            # Save the daily_token to the row
            writer.writerow([invoice_no, current_date, current_time, daily_token, order_type, table_no, customer, items_summary, round(grand_total, 2)])
    except Exception as e:
        print(f"CSV Error: {e}")

    # 4. FPDF INVOICE GENERATION
    try:
        pdf = FPDF(format='A5')
        pdf.add_page()
        
        # --- Define Brand Colors (RGB Format) ---
        brand_red = (218, 41, 28)
        text_dark = (40, 40, 40)
        text_muted = (100, 100, 100)
        
        # Header / Restaurant Name
        pdf.set_text_color(*brand_red)
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(130, 8, "BISTRO CAFE GWALIOR", ln=True, align='C')
        
        pdf.set_text_color(*text_muted)
        pdf.set_font("Arial", '', 9)
        pdf.cell(130, 4, "GSTIN: 23ABCDE1234F1Z5 | Ph: +91-9876543210", ln=True, align='C')
        pdf.ln(3)
        
        # --- UPGRADE 2: BRAND COLOR TOKEN NUMBER ---
        pdf.set_text_color(*brand_red)
        pdf.set_font("Times", 'B', 20)
        pdf.cell(130, 15, f"#TOKEN: {daily_token}", ln=True, align='C')
        pdf.ln(3)
        
        # Customer & Order Info
        pdf.set_draw_color(200, 200, 200) # Light grey line
        pdf.line(10, pdf.get_y(), 138, pdf.get_y()) # Solid line instead of dashes
        pdf.ln(3)
        
        pdf.set_text_color(*text_dark)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(65, 5, f"Invoice No: {invoice_no}", ln=False)
        pdf.cell(65, 5, f"Date: {current_date}", ln=True, align='R')
        pdf.cell(65, 5, f"Customer: {customer}", ln=False)
        pdf.cell(65, 5, f"Table: {table_no} ({order_type})", ln=True, align='R')
        pdf.ln(3)
        
        # --- UPGRADE 1: TRUE INVOICE TABLE ---
        # Table Header (Filled Grey Box)
        pdf.set_fill_color(245, 245, 245)
        pdf.set_text_color(*text_dark)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(50, 7, " Item", border=0, ln=False, fill=True)
        pdf.cell(20, 7, "Qty", border=0, ln=False, align='C', fill=True)
        pdf.cell(30, 7, "Price", border=0, ln=False, align='R', fill=True)
        pdf.cell(30, 7, "Total ", border=0, ln=True, align='R', fill=True)
        
        # Line Items (With faint borders between rows)
        pdf.set_font("Arial", '', 9)
        for item in cart_items:
            i_price = float(item['price'])
            i_qty = int(item['qty'])
            i_total = i_price * i_qty
            
            pdf.cell(50, 7, f" {item['name'][:20]}", ln=False)
            pdf.cell(20, 7, str(i_qty), ln=False, align='C')
            pdf.cell(30, 7, f"{i_price:.2f}", ln=False, align='R')
            pdf.cell(30, 7, f"{i_total:.2f} ", ln=True, align='R')
            
            # Faint line between items
            pdf.set_draw_color(235, 235, 235)
            pdf.line(10, pdf.get_y(), 138, pdf.get_y())
            
        pdf.ln(4)
        
        # Totals Section
        pdf.set_text_color(*text_dark)
        pdf.set_font("Arial", '', 9)
        pdf.cell(90, 5, "Subtotal:", ln=False, align='R')
        pdf.cell(40, 5, f"Rs {subtotal:.2f}", ln=True, align='R')
        
        if discount_pct > 0:
            pdf.cell(90, 5, f"Discount ({discount_pct}%):", ln=False, align='R')
            pdf.cell(40, 5, f"- Rs {discount_amt:.2f}", ln=True, align='R')
            
        pdf.cell(90, 5, f"CGST ({half_tax}%):", ln=False, align='R')
        pdf.cell(40, 5, f"Rs {cgst:.2f}", ln=True, align='R')
        pdf.cell(90, 5, f"SGST ({half_tax}%):", ln=False, align='R')
        pdf.cell(40, 5, f"Rs {sgst:.2f}", ln=True, align='R')
        pdf.ln(2)
        
        # --- UPGRADE 2 (Part B): BRAND COLOR GRAND TOTAL BOX ---
        pdf.set_fill_color(253, 237, 237) # Extremely light red tint box
        pdf.set_text_color(*brand_red)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(85, 9, "", ln=False) # Invisible spacer to push total to the right
        pdf.cell(45, 9, f" TOTAL: Rs {grand_total:.2f} ", ln=True, align='R', fill=True)
        
        # --- UPGRADE 3: PROFESSIONAL FOOTER ---
        pdf.ln(8) 
        
        pdf.set_draw_color(200, 200, 200)
        pdf.line(30, pdf.get_y(), 118, pdf.get_y()) # Centered elegant line
        pdf.ln(3)
        
        pdf.set_text_color(*text_muted)
        pdf.set_font("Arial", 'I', 8)
        pdf.cell(130, 4, "Thank you for dining with BistroPOS!", ln=True, align='C')
        pdf.cell(130, 4, "Visit us at www.bistrocafe.in", ln=True, align='C')
        
        # Faux UPI tag
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Arial", 'B', 7)
        pdf.cell(130, 5, "[ SCAN QR CODE AT DESK FOR UPI PAYMENT ]", ln=True, align='C')
        
        pdf_filename = f"invoices/Invoice_{invoice_no}.pdf"
        pdf.output(pdf_filename)
        
    except Exception as e:
        print(f"PDF Error: {e}")
        return jsonify({"status": "error", "message": "Failed to generate PDF."}), 500
        
    except Exception as e:
        print(f"PDF Error: {e}")
        return jsonify({"status": "error", "message": "Failed to generate PDF."}), 500

    # 5. Send both Invoice No and Token back to JavaScript
    return jsonify({
        "status": "success",
        "message": "Success! CSV updated and PDF generated.",
        "invoice_no": invoice_no,
        "token": daily_token
    })

@app.route('/download_invoice/<invoice_no>')
def download_invoice(invoice_no):
    base_dir = os.path.abspath(os.path.dirname(__file__))
    file_path = os.path.join(base_dir, 'invoices', f"Invoice_{invoice_no}.pdf")
    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return f"File not found. System Error: {e}", 404

if __name__ == '__main__':
    app.run(debug=True)
