# Shoe Clinic API - Version 02

**Version:** v02  
**Release Date:** 2025-12-22  
**Status:** Development

## Overview

This is version 02 of the Shoe Clinic Management API. This version is based on v01 and serves as the development/staging environment for new features and updates.

## What's New in v02

- Version tracking and identification
- Separate database for safe testing
- Independent deployment from v01
- Ready for new feature development

## Setup Instructions

### Prerequisites
- Python 3.9+
- PostgreSQL (for production) or SQLite (for local development)

### Local Development

1. **Create Virtual Environment**
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. **Install Dependencies**
   ```
   pip install -r requirements.txt
   ```

3. **Configure Environment**
   - Copy `.env.example` to `.env`
   - Update database connection string
   - Set `APP_VERSION=v02`

4. **Initialize Database**
   ```
   flask db upgrade
   ```

5. **Run Application**
   ```
   python app.py
   ```
   Or use the provided batch file:
   ```
   start_app.bat
   ```

## Deployment

### Render Deployment

1. Create new Web Service on Render
2. Connect to your repository
3. Set environment variables:
   - `DATABASE_URL`: PostgreSQL connection string
   - `APP_VERSION`: v02
4. Deploy!

## API Endpoints

### Version Information
- `GET /version` - Returns version info and status

### Authentication
- `POST /login` - User login
- `POST /register` - User registration
- `POST /logout` - User logout

### Orders
- `GET /tsc_dashboard` - View all orders
- `POST /add` - Create new order
- `POST /edit_order/<id>` - Update order

## Database

v02 uses a separate database from v01 to ensure:
- Safe testing without affecting production
- Independent schema migrations
- Easy rollback if needed

## Migration from v01

If you need to migrate data from v01:
1. Export data from v01 database
2. Import into v02 database
3. Run any necessary data transformations

## Support

For issues or questions, contact the development team.
