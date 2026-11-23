# Smart Info Tracker & Post Manager

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Django](https://img.shields.io/badge/Django-5.0%2B-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-All-lightgrey)

> An intelligent market intelligence collection, AI-powered analysis, and multi-channel social media publishing platform. Perfect for organizations that need to monitor tenders, job opportunities, healthcare announcements, and business news across multiple sources and automatically publish curated content to Telegram, Facebook, and LinkedIn.

## 🌟 Features

### Information Collection
- **Multi-Source Connectors**: RSS feeds, web scraping, PDF document parsing
- **Smart Deduplication**: Automatic clustering of duplicate content from multiple sources
- **Scheduled Collection**: Cron-based batch collection with configurable limits
- **Content Extraction**: Automatic extraction of images, documents, and structured data

### AI-Powered Intelligence
- **Google Gemini Integration**: LLM-powered content analysis and summarization
- **Entity Extraction**: Automatic extraction of organizations, budgets, deadlines, contacts
- **Multi-Language Support**: English and Amharic content processing
- **Relevance Scoring**: Explainable AI scoring (0-100) with detailed reasoning
- **Cost Controls**: Daily spend limits and API call circuit breakers

### Publishing & Distribution
- **Multi-Channel Publishing**: Telegram, Facebook, LinkedIn integration
- **News-Channel Style**: Clean article formatting with media galleries
- **Editorial Studio**: Review, edit, and approve content before publishing
- **Custom Broadcast Messages**: Add custom notes to published content
- **Encrypted Credentials**: Secure storage of social media credentials

### Dashboard & Management
- **Web Dashboard**: Django-based admin interface for all operations
- **Source Management**: Configure and monitor information sources
- **Category & Tag System**: Organize content with flexible taxonomy
- **Status Tracking**: Full lifecycle from ingestion to publishing
- **PWA Support**: Progressive Web App for mobile access

### Developer Features
- **REST API**: Full API for programmatic access
- **API Key Authentication**: Secure API client management
- **Database Flexibility**: SQLite, MySQL/MariaDB, PostgreSQL support
- **cPanel Ready**: Designed for shared hosting environments
- **VPS Mode**: Optional Celery + Redis for dedicated servers

## 📸 Screenshots

### Dashboard Overview
![Dashboard](docs/screenshots/dashboard.png)

### Intelligence Items
![Items](docs/screenshots/items.png)

### Publishing Studio
![Publishing](docs/screenshots/publishing.png)

## 🚀 Quick Start

### Prerequisites
- Python 3.10 or higher
- pip package manager
- SQLite (default) or MySQL/PostgreSQL

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/sismolla/smart-info-tracker-and-post-manager.git
cd smart-info-tracker-and-post-manager
```

2. **Create a virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your settings
```

5. **Run migrations**
```bash
python manage.py migrate
```

6. **Create a superuser**
```bash
python manage.py createsuperuser
```

7. **Run the development server**
```bash
python manage.py runserver
```

8. **Access the dashboard**
Open http://localhost:8000 in your browser

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | Auto-generated |
| `DEBUG` | Debug mode | `True` |
| `ALLOWED_HOSTS` | Allowed hosts | `*` |
| `DB_ENGINE` | Database engine (sqlite/mysql/postgresql) | `sqlite` |
| `DB_NAME` | Database name | `db.sqlite3` |
| `DB_USER` | Database user | - |
| `DB_PASSWORD` | Database password | - |
| `DB_HOST` | Database host | `localhost` |
| `DB_PORT` | Database port | - |
| `TELEGRAM_ALERT_CHAT_ID` | Telegram chat ID for alerts | - |
| `TELEGRAM_ALERT_MIN_SCORE` | Minimum score for alerts | `75` |
| `AI_DAILY_SPEND_LIMIT_USD` | Daily AI spend limit | `2.00` |
| `AI_DAILY_MAX_CALLS` | Daily AI call limit | `500` |
| `EXECUTION_MODE` | Execution mode (cpanel_cron/celery_worker) | `cpanel_cron` |

### AI Configuration

Add your Google Gemini API key to `.env`:
```env
GEMINI_API_KEY=your_api_key_here
# Multiple keys supported for rotation
GEMINI_API_KEYS=key1,key2,key3
```

### Social Media Setup

Configure your publishing channels in the dashboard:
1. Navigate to Settings → Channels
2. Add Telegram, Facebook, or LinkedIn credentials
3. Credentials are encrypted at rest

## 📖 Usage

### Adding Information Sources

1. Go to **Sources** in the dashboard
2. Click **Add New Source**
3. Select connector type (RSS, Web, etc.)
4. Configure source settings
5. Save and enable

### Running Collection

**Manual Collection:**
```bash
python manage.py run_collection_batch
```

**Cron Setup (cPanel):**
```bash
# Add to cPanel cron
*/30 * * * * cd /path/to/project && python manage.py run_collection_batch
```

**Cron Setup (Linux):**
```bash
# Add to crontab
*/30 * * * * cd /path/to/project && /path/to/venv/bin/python manage.py run_collection_batch
```

### AI Processing

Process collected items with AI analysis:
```bash
python manage.py process_ai_batch
```

### Publishing Content

1. Go to **Items** in the dashboard
2. Review AI-analyzed content
3. Edit if needed
4. Select channels (Telegram, Facebook, LinkedIn)
5. Click **Publish**

### API Usage

**Get all items:**
```bash
curl -H "Authorization: ApiKey your_api_key" http://localhost:8000/api/items/
```

**Filter by category:**
```bash
curl -H "Authorization: ApiKey your_api_key" "http://localhost:8000/api/items/?category=tender"
```

**Publish an item:**
```bash
curl -X POST -H "Authorization: ApiKey your_api_key" http://localhost:8000/api/items/123/publish/
```

## 🏗️ Architecture

```
smart-info-tracker-and-post-manager/
├── core/                 # Core models and utilities
├── connectors/           # Source connectors (RSS, Web, PDF)
├── intelligence/         # AI analysis and entity extraction
├── publishing/           # Multi-channel publishing
├── workflows/            # Pipeline engine
├── api/                  # REST API
├── dashboard/            # Web dashboard UI
└── market_intel/         # Django project settings
```

### Data Flow

1. **Collection**: Connectors fetch raw content from sources
2. **Ingestion**: Content is stored as `CollectedItem`
3. **Deduplication**: Duplicate detection and clustering
4. **AI Processing**: Entity extraction, summarization, scoring
5. **Review**: Editorial review in dashboard
6. **Publishing**: Multi-channel distribution

## 🌍 Multi-Language Support

The system supports:
- **English**: Primary language for content and UI
- **Amharic**: Full support for Ethiopian content
- **Auto-detection**: Automatic language detection
- **Translation**: AI-powered translation between languages

## 🔒 Security

- **Encrypted Credentials**: Social media credentials encrypted with cryptography
- **API Key Authentication**: Secure API access
- **Rate Limiting**: Configurable API rate limits
- **SQL Injection Protection**: Django ORM prevents SQL injection
- **CSRF Protection**: Built-in CSRF middleware
- **Circuit Breakers**: AI spend limits prevent runaway costs

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Django Framework
- Google Gemini AI
- Telethon (Telegram library)
- All contributors

## 📞 Support

For issues and questions:
- Open an issue on GitHub
- Email: support@example.com
- Documentation: [Wiki](https://github.com/sismolla/smart-info-tracker-and-post-manager/wiki)

## 🔗 Related Projects

- [Django REST Framework](https://www.django-rest-framework.org/)
- [Google AI](https://ai.google.dev/)
- [Telethon](https://docs.telethon.dev/)

---

**Keywords**: Django, market intelligence, AI, social media publishing, Telegram, Facebook, LinkedIn, RSS, web scraping, content curation, automation, Ethiopia, Amharic, tender tracking, job alerts, healthcare intelligence
