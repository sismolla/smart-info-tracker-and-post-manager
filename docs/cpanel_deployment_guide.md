# cPanel Deployment & Operations Guide
## Deploying Market Intelligence Platform on cPanel Shared Hosting (Mode A)

> [!IMPORTANT]
> **No Root, No Docker, No Permanent Daemons Required**: This application is specifically engineered to run within the CloudLinux LVE memory and process limits of standard cPanel shared hosting accounts.

---

### Step 1: Upload Project Files to cPanel
1. Compress the project folder into a `.zip` archive (excluding `db.sqlite3` and `venv`).
2. Log in to your cPanel control panel and open **File Manager**.
3. Navigate to your target application directory (e.g., `/home/username/market_intel` or `/home/username/public_html`).
4. Upload the zip archive and click **Extract**.

---

### Step 2: Create the Python Application via "Setup Python App"
1. In cPanel, navigate to the **Software** section and click **Setup Python App**.
2. Click **Create Application**.
3. Configure the following fields:
   - **Python version**: Select `3.11` (or `3.10+`).
   - **Application root**: `market_intel` (the folder where your project files live).
   - **Application URL**: Select your domain or subdomain (e.g. `intel.yourdomain.com`).
   - **Application startup file**: `passenger_wsgi.py`
   - **Application Entry point**: `application`
4. Click **Create**.
5. Note the virtual environment activation command displayed at the top of the page:
   ```bash
   source /home/username/virtualenv/market_intel/3.11/bin/activate && cd /home/username/market_intel
   ```

---

### Step 3: Install Dependencies
1. Open the cPanel **Terminal** (or connect via SSH).
2. Activate the virtual environment:
   ```bash
   source /home/username/virtualenv/market_intel/3.11/bin/activate
   cd /home/username/market_intel
   ```
3. Install required packages:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. If you are using MySQL/MariaDB on cPanel, install the MySQL driver:
   ```bash
   pip install mysqlclient
   ```

---

### Step 4: Configure the Environment Variables (.env)
1. In File Manager or Terminal, copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your production values:
   ```ini
   DEBUG=False
   SECRET_KEY=generate-a-strong-secret-key-with-random-characters-here
   ALLOWED_HOSTS=intel.yourdomain.com,yourdomain.com

   # cPanel MySQL Configuration
   DB_ENGINE=mysql
   DB_NAME=username_marketintel
   DB_USER=username_dbuser
   DB_PASSWORD=YourStrongDatabasePassword123!
   DB_HOST=localhost
   DB_PORT=3306

   # Symmetric Token Encryption
   FIELD_ENCRYPTION_KEY=

   # Execution Mode (cPanel Mode A)
   EXECUTION_MODE=cpanel_cron
   BATCH_COLLECTION_LIMIT=25
   CRON_LOCK_TIMEOUT_SECONDS=300

   # AI Configuration
   GEMINI_API_KEY=AIzaSy...your-gemini-api-key
   GEMINI_MODEL=gemini-1.5-flash
   ```

---

### Step 5: Configure the cPanel MySQL Database
1. Go to cPanel > **MySQL Databases**.
2. Create a new database: `username_marketintel`.
3. Create a new MySQL user: `username_dbuser` with a strong password.
4. Add the user to the database with **ALL PRIVILEGES**.

---

### Step 6: Run Database Migrations & Initial Seeding
In the cPanel Terminal inside the activated virtual environment:
```bash
python manage.py migrate
python manage.py seed_demo_data
python manage.py createsuperuser
```

---

### Step 7: Collect Static Files
Serve static files directly through Apache/LiteSpeed for maximum performance:
```bash
python manage.py collectstatic --noinput
```
Ensure your `.htaccess` routes `/static/` and `/media/` directly to their respective directories.

---

### Step 8: Configure Phusion Passenger & .htaccess
Verify that `passenger_wsgi.py` exists in the application root.
Confirm that your `.htaccess` file contains:
```apache
PassengerAppRoot "/home/username/market_intel"
PassengerPython "/home/username/virtualenv/market_intel/3.11/bin/python"
PassengerAppType wsgi
PassengerStartupFile passenger_wsgi.py

Options -Indexes
RewriteEngine On
RewriteCond %{REQUEST_URI} ^/static/ [NC,OR]
RewriteCond %{REQUEST_URI} ^/media/ [NC]
RewriteRule ^ - [L]

RewriteCond %{HTTPS} off
RewriteRule ^(.*)$ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
```

---

### Step 9: Set Up Scheduled cPanel Cron Jobs
Because shared hosting does not allow long-running Celery daemons, background synchronization runs via cPanel Cron Jobs:

1. In cPanel, open **Cron Jobs**.
2. Under **Add New Cron Job**:
   - **Minute**: `*/15` (runs every 15 minutes)
   - **Hour**, **Day**, **Month**, **Weekday**: `*`
   - **Command**:
     ```bash
     cd /home/username/market_intel && /home/username/virtualenv/market_intel/3.11/bin/python manage.py run_collection_batch >> /home/username/market_intel/cron.log 2>&1
     ```
3. Click **Add New Cron Job**.

> [!NOTE]
> **Collision Protection**: If an external network connection is slow, the platform's `DatabaseLock` prevents the next cron run from colliding with the previous one. It will cleanly exit without causing memory exhaustion.

---

### Step 10: Enable HTTPS via AutoSSL
1. Go to cPanel > **SSL/TLS Status**.
2. Check your domain (`intel.yourdomain.com`).
3. Click **Run AutoSSL** to generate a free Let's Encrypt / Sectigo SSL certificate.

---

### Step 11: System Diagnostics Health Verification
Visit the built-in diagnostic endpoint:
```
https://intel.yourdomain.com/health/
```
Or run from terminal:
```bash
python manage.py system_health_check
```
Verify that all services report `status: ok`.

---

### Step 12: Safe Application Updates & Restarts
To deploy updates without dropping active connections:
1. Pull new code or upload modified files.
2. Run database migrations:
   ```bash
   python manage.py migrate
   ```
3. Restart Passenger gracefully by creating or touching `tmp/restart.txt`:
   ```bash
   mkdir -p tmp && touch tmp/restart.txt
   ```
Passenger will cleanly reload workers on the next HTTP request.
