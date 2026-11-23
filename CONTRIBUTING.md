# Contributing to Smart Info Tracker & Post Manager

Thank you for your interest in contributing to this project! This document provides guidelines and instructions for contributing.

## 🤝 How to Contribute

### Reporting Bugs

Before creating bug reports, please check the existing issues to avoid duplicates. When creating a bug report, include:

- **Title**: Clear and descriptive
- **Description**: Detailed explanation of the issue
- **Steps to Reproduce**: Step-by-step instructions
- **Expected Behavior**: What you expected to happen
- **Actual Behavior**: What actually happened
- **Environment**: OS, Python version, Django version
- **Screenshots**: If applicable

### Suggesting Enhancements

Enhancement suggestions are welcome! Please include:

- **Title**: Clear and descriptive
- **Problem Description**: What problem does this solve?
- **Proposed Solution**: How would you like to solve it?
- **Alternatives**: What alternatives have you considered?
- **Additional Context**: Any other context or screenshots

## 🛠️ Development Setup

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork locally:
```bash
git clone https://github.com/YOUR_USERNAME/smart-info-tracker-and-post-manager.git
cd smart-info-tracker-and-post-manager
```

3. Add the upstream remote:
```bash
git remote add upstream https://github.com/sismolla/smart-info-tracker-and-post-manager.git
```

### Set Up Development Environment

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install development dependencies:
```bash
pip install -r requirements-dev.txt  # if available
```

4. Copy environment variables:
```bash
cp .env.example .env
# Edit .env with your development settings
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Create a superuser:
```bash
python manage.py createsuperuser
```

7. Run the development server:
```bash
python manage.py runserver
```

## 📝 Coding Standards

### Python Code Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use 4 spaces for indentation (no tabs)
- Maximum line length: 88 characters (black default)
- Use meaningful variable and function names
- Add docstrings to functions and classes

### Django Conventions

- Use Django's built-in models and fields when possible
- Follow Django's model naming conventions
- Use `related_name` in ForeignKey fields
- Add `__str__` methods to models
- Use Django's URL patterns and views correctly

### Git Commit Messages

Follow conventional commit format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(publishing): add Instagram channel support

Add Instagram publisher with image gallery support.
Includes OAuth authentication and media upload.

Closes #123
```

```
fix(intelligence): correct entity extraction for deadlines

Fix ISO date conversion for Ethiopian calendar dates.
Also updates deadline validation logic.
```

## 🧪 Testing

### Running Tests

```bash
python manage.py test
```

### Running Specific Tests

```bash
python manage.py test intelligence.tests
python manage.py test intelligence.tests.TestEntityExtraction
```

### Writing Tests

- Write tests for new features
- Test edge cases and error conditions
- Use descriptive test names
- Keep tests independent

### Test Coverage

```bash
pip install coverage
coverage run --source='.' manage.py test
coverage report
coverage html  # Generates HTML report
```

## 📂 Project Structure

```
smart-info-tracker-and-post-manager/
├── core/                 # Core models and utilities
│   ├── models.py
│   └── management/commands/
├── connectors/           # Source connectors
│   ├── base.py           # Base connector class
│   ├── rss.py            # RSS connector
│   └── web.py            # Web scraper
├── intelligence/         # AI analysis
│   ├── models.py
│   ├── ai_client.py      # AI integration
│   └── scoring.py        # Relevance scoring
├── publishing/           # Publishing
│   ├── models.py
│   ├── publishers.py     # Channel publishers
│   └── alerts.py         # Alert system
├── workflows/            # Pipeline engine
│   └── engine.py
├── api/                  # REST API
│   ├── views.py
│   └── serializers.py
├── dashboard/            # Web UI
│   ├── views.py
│   ├── templates/
│   └── static/
└── market_intel/         # Django settings
    └── settings.py
```

## 🔄 Pull Request Process

1. **Update Branch**: Ensure your branch is up to date with upstream
```bash
git fetch upstream
git rebase upstream/main
```

2. **Create Feature Branch**: Use descriptive branch names
```bash
git checkout -b feature/your-feature-name
```

3. **Make Changes**: Implement your changes following coding standards

4. **Test**: Run tests and ensure they pass
```bash
python manage.py test
```

5. **Commit**: Write clear commit messages
```bash
git add .
git commit -m "feat(your-scope): your description"
```

6. **Push**: Push to your fork
```bash
git push origin feature/your-feature-name
```

7. **Create Pull Request**: Go to GitHub and create a PR

### Pull Request Checklist

- [ ] Code follows project style guidelines
- [ ] Tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages follow conventional format
- [ ] PR description clearly describes changes
- [ ] No merge conflicts

## 📖 Documentation

### Updating Documentation

- Keep README.md up to date with new features
- Add docstrings to new functions and classes
- Update API documentation if API changes
- Add examples for new features

### API Documentation

API endpoints should be documented with:
- Description
- Request parameters
- Response format
- Authentication requirements
- Example requests/responses

## 🐛 Debugging

### Debug Mode

Set `DEBUG=True` in `.env` for detailed error messages.

### Logging

Check Django logs in:
- Console output
- Log files (if configured)
- Django admin error pages

### Common Issues

**Database Migration Errors:**
```bash
python manage.py migrate --fake-initial
```

**Static Files Not Loading:**
```bash
python manage.py collectstatic
```

**AI API Errors:**
- Check GEMINI_API_KEY in .env
- Verify API key has sufficient quota
- Check AI_DAILY_SPEND_LIMIT_USD

## 🎯 Roadmap

See [PROJECT_ROADMAP.md](PROJECT_ROADMAP.md) for planned features and upcoming changes.

## 💡 Feature Ideas

Looking for something to work on? Check out:
- [Open issues labeled "enhancement"](https://github.com/sismolla/smart-info-tracker-and-post-manager/issues?q=is%3Aissue+is%3Aopen+label%3Aenhancement)
- [Open issues labeled "good first issue"](https://github.com/sismolla/smart-info-tracker-and-post-manager/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

## 📜 Code of Conduct

### Our Pledge

We are committed to making participation in this project a harassment-free experience for everyone.

### Our Standards

- Respect differing viewpoints and experiences
- Accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

### Unacceptable Behavior

- Harassment, trolling, or derogatory comments
- Personal or political attacks
- Public or private harassment
- Publishing others' private information

### Enforcement

Project maintainers reserve the right to remove, edit, or reject comments that do not align with this Code of Conduct.

## 📧 Contact

For questions about contributing:
- Open an issue on GitHub
- Email: support@example.com

## 🙏 Thank You

Thank you for contributing to Smart Info Tracker & Post Manager!
