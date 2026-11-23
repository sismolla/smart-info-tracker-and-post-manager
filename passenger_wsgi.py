"""
cPanel Phusion Passenger WSGI Entry Point
=========================================
This file is required by cPanel's 'Setup Python App' (CloudLinux / Phusion Passenger).
It ensures the application root is in sys.path, sets the DJANGO_SETTINGS_MODULE,
and exposes the application object.
"""

import sys
import os
from pathlib import Path

# Add project root directory to Python path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# Ensure current working directory is application root on cPanel LiteSpeed/Passenger
os.chdir(str(CURRENT_DIR))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_intel.settings')

# PyMySQL compatibility shim — makes PyMySQL act as MySQLdb on hosts
# where the C mysqlclient extension cannot be compiled (e.g. cPanel shared hosting).
# Install with: pip install PyMySQL
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass  # mysqlclient (C extension) is used instead — that's fine too

# Import Django WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
