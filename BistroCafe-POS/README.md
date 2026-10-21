# BistroCafe POS

A college-level restaurant point-of-sale web application built with Flask, HTML, CSS, and JavaScript.

## Included features

- Menu browsing and cart-based ordering
- Cash, UPI, and Card payment selection
- Inventory tracking with low-stock and out-of-stock behavior
- Customer details and table/order reference
- GST, discount, subtotal, and grand-total calculation
- Premium A5 PDF invoice generation
- Invoice preview/download routes
- Optional SMTP email receipt with PDF attachment
- Admin login and analytics dashboard
- Recent orders, inventory controls, and CSV sales export
- Help/About section
- Responsive current-order panel with one-tap open/close control

## Files

- `app.py` — Flask backend, routes, authentication, inventory, checkout, invoice generation, email, and admin APIs
- `index.html` — main POS frontend
- `index-1.html` — synchronized alternate POS frontend copy
- `login.html` — admin login page
- `admin.html` — admin analytics and inventory dashboard
- `inventory.json` — current inventory data
- `daily_sales.csv` — sales records
- `requirements.txt` — Python dependencies
- `Dockerfile` — production container configuration
- `.env.example` — names of optional runtime environment variables

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`.

## Optional email configuration

Set these environment variables in the hosting provider or local environment. Do not put real values into source files or commit them to Git:

```text
SMTP_SENDER_EMAIL=your Gmail address
SMTP_APP_PASSWORD=your Gmail App Password
```

The application reports email success only after the SMTP server accepts the message. Without these variables, PDF generation still works but email delivery is unavailable.

## Notes for demonstration

This project intentionally stays at a college-project scope. It does not include order-status workflows or dashboard theme selection.
