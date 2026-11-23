# Social Preview & SEO Metadata

## Open Graph / Twitter Card Tags

Add these meta tags to your base HTML template (`dashboard/templates/dashboard/base.html`) in the `<head>` section to improve social media sharing:

```html
<!-- Primary Meta Tags -->
<title>Smart Info Tracker & Post Manager - AI-Powered Market Intelligence & Social Media Publishing</title>
<meta name="title" content="Smart Info Tracker & Post Manager - AI-Powered Market Intelligence & Social Media Publishing">
<meta name="description" content="An intelligent market intelligence collection, AI-powered analysis, and multi-channel social media publishing platform. Monitor tenders, jobs, healthcare announcements, and business news with automatic publishing to Telegram, Facebook, and LinkedIn.">
<meta name="keywords" content="django, market intelligence, AI, social media publishing, telegram, facebook, linkedin, RSS, web scraping, content curation, automation, ethiopia, amharic, tender tracking, job alerts, healthcare intelligence">
<meta name="author" content="Sismolla">

<!-- Open Graph / Facebook -->
<meta property="og:type" content="website">
<meta property="og:url" content="https://github.com/sismolla/smart-info-tracker-and-post-manager">
<meta property="og:title" content="Smart Info Tracker & Post Manager - AI-Powered Market Intelligence & Social Media Publishing">
<meta property="og:description" content="An intelligent market intelligence collection, AI-powered analysis, and multi-channel social media publishing platform. Monitor tenders, jobs, healthcare announcements, and business news with automatic publishing to Telegram, Facebook, and LinkedIn.">
<meta property="og:image" content="https://github.com/sismolla/smart-info-tracker-and-post-manager/raw/main/docs/images/social-preview.png">

<!-- Twitter -->
<meta property="twitter:card" content="summary_large_image">
<meta property="twitter:url" content="https://github.com/sismolla/smart-info-tracker-and-post-manager">
<meta property="twitter:title" content="Smart Info Tracker & Post Manager - AI-Powered Market Intelligence & Social Media Publishing">
<meta property="twitter:description" content="An intelligent market intelligence collection, AI-powered analysis, and multi-channel social media publishing platform. Monitor tenders, jobs, healthcare announcements, and business news with automatic publishing to Telegram, Facebook, and LinkedIn.">
<meta property="twitter:image" content="https://github.com/sismolla/smart-info-tracker-and-post-manager/raw/main/docs/images/social-preview.png">
```

## Creating Social Preview Image

Create a social preview image at `docs/images/social-preview.png` (1200x630px recommended) with:
- Project title: "Smart Info Tracker & Post Manager"
- Tagline: "AI-Powered Market Intelligence & Social Media Publishing"
- Key features: "Multi-Source Collection • AI Analysis • Multi-Channel Publishing"
- GitHub URL or logo
- Professional color scheme matching your project

## robots.txt

Add a `robots.txt` file for SEO:

```
User-agent: *
Allow: /

# Disallow admin and API
Disallow: /admin/
Disallow: /api/

# Sitemap
Sitemap: https://yourdomain.com/sitemap.xml
```

## sitemap.xml

For a deployed version, consider adding a sitemap.xml to help search engines index your documentation.
