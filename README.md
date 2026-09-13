# Photosite

Photosite is a deployable custom-photo-frame storefront. It contains a responsive public shop, a client-side shopping bag, photo upload previews, a Flask/SQLite order API, Cash on Delivery checkout, optional Razorpay online payments, and a password-protected order dashboard.

## Project layout

```text
photosite/
├── app.py                 # Flask application and order/payment API
├── notifications.py       # New-order email notifications
├── templates/
│   ├── index.html         # Storefront HTML
│   └── admin.html         # Order dashboard
├── static/
│   ├── css/style.css      # All presentation styles
│   └── js/app.js          # Storefront interaction and checkout client
├── uploads/               # Customer photo uploads (persist this in production)
├── data/                  # SQLite order database (persist this in production)
├── Dockerfile             # Portable production container
├── requirements.txt
└── .env.example
```

## Customer accounts

Customers can create an account or sign in from the storefront. Passwords are hashed on the server, sessions are HTTP-only, and each order made while signed in is visible on the private `/account` page. Guest checkout is still available for customers who do not want an account.

Set `SESSION_COOKIE_SECURE=true` in your hosting environment once the website is behind HTTPS on your domain. Keep it `false` only for local development at `http://127.0.0.1`.

## Run locally

1. Install Python 3.12 or later from [python.org](https://www.python.org/downloads/).
2. In this folder, create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies and set environment variables:

   ```powershell
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

4. Update `.env` with a secure `FLASK_SECRET_KEY` and a strong dashboard password, then start the website:

   ```powershell
   flask --app app run --debug
   ```

5. Open `http://127.0.0.1:5000`. The private order dashboard is at `http://127.0.0.1:5000/admin`.

## Payments

Cash on Delivery works immediately and creates an order in `data/photosite.db`.

## Get an email when someone orders

The app automatically sends a **new-order notification** for every confirmed order—immediately for Cash on Delivery and only after payment verification for Razorpay. The email includes the order ID, customer and delivery details, items, total, payment status, and note.

For a first launch, Gmail is the simplest option:

1. Create a dedicated business Gmail address (for example `photosite.orders@gmail.com`) or use your existing business email.
2. In that Google account, turn on 2-Step Verification, then create a 16-character **App Password** for “Mail”. Do not use your normal Gmail password.
3. Set `NOTIFICATION_EMAIL`, `SMTP_FROM_EMAIL`, `SMTP_USERNAME`, and `SMTP_PASSWORD` in the host’s environment settings. Keep `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, and `SMTP_USE_TLS=true`.
4. Place a Cash on Delivery test order and confirm that the email arrives before launch.

When no SMTP values are set, Photosite safely continues to take orders and stores them in the private dashboard; it logs that the alert was skipped rather than exposing an error to customers.

To enable Razorpay, create a Razorpay account and place your live credentials in the server’s environment—never in `static/js/app.js` or a public repository:

```env
RAZORPAY_KEY_ID=rzp_live_your_key_id
RAZORPAY_KEY_SECRET=your_secret
```

The backend creates the Razorpay order and verifies the payment signature before marking an order as paid. Use Razorpay test credentials first, then change to live credentials only when your account and business verification are ready.

## Deploy and connect a domain

The included `Dockerfile` works on any Docker-compatible host, including Render, Railway, Fly.io, DigitalOcean App Platform, or an AWS service.

1. Push this folder to a **private** GitHub repository. Do not commit `.env`.
2. Create a new Docker web service on your hosting provider from that repository.
3. Set the environment values from `.env.example` in the provider dashboard. Set `PORT=5000` only if the host requires it; most hosts inject their own `PORT`.
4. Attach persistent storage to `/app/data` and `/app/uploads`. SQLite and uploaded customer photos must not live only on temporary container storage.
5. After the service is live, use your provider’s **Custom Domain** setting. Add the shown DNS CNAME/A records at the business domain registrar, then enable the provider’s managed HTTPS certificate.
6. Before launch, update the contact email, policies, product images, delivery areas, prices, the default admin password, and Razorpay live keys.

## Production notes

- Customer photos are personal data. Publish a privacy policy, restrict dashboard access, and back up the persistent volumes.
- SQLite is a good single-store launch option. For multiple servers or higher order volume, move `orders` to PostgreSQL and uploads to object storage (such as S3 or Cloudinary).
- The public product total is recalculated on the server; browser prices are never trusted for checkout.
- This starter creates and stores orders. Add email/SMS notifications through a provider such as Resend, SendGrid, or Twilio when you are ready to connect those services.
