# Migration Guide: v01 ? v02

## Overview

This guide explains the differences between v01 and v02, and how to work with both versions.

## Key Differences

### Version Identification

**v02 includes:**
- Version constants in `app.py` (`APP_VERSION`, `VERSION_DATE`, `VERSION_STATUS`)
- New `/version` endpoint that returns version information
- Separate database configuration

### Database

- **v01**: Uses `shoeclinic.db` (SQLite) or `shoeclinic` (PostgreSQL)
- **v02**: Uses `shoeclinic_v02.db` (SQLite) or `shoeclinic_v02` (PostgreSQL)

This separation ensures:
- v01 production data remains untouched
- Safe testing in v02
- Easy rollback if needed

### Configuration

**v02 .env file includes:**
```env
APP_VERSION=v02
DATABASE_URL=sqlite:///shoeclinic_v02.db
```

## Working with Both Versions

### Directory Structure

```
e:\
+-- app_v01\          # Production version
¦   +-- .git\         # Separate git history
¦   +-- ...
+-- app_v02\          # Development version
    +-- .git\         # Separate git history
    +-- ...
```

### Running Locally

**v01 (Production):**
```bash
cd e:\app_v01
.venv\Scripts\activate
python app.py
```

**v02 (Development):**
```bash
cd e:\app_v02
.venv\Scripts\activate
python app.py
```

> **Note**: You can only run one at a time on the same port. Consider changing the port in one version if you need both running simultaneously.

## Deploying v02

### Option 1: Separate Render Service (Recommended)

1. **Create New Web Service** on Render
   - Name: `shoeclinic-api-v02`
   - Repository: Point to your v02 git repository
   
2. **Environment Variables**
   ```
   DATABASE_URL=<your_postgresql_url_for_v02>
   APP_VERSION=v02
   TWILIO_ACCOUNT_SID=<your_twilio_sid>
   TWILIO_AUTH_TOKEN=<your_twilio_token>
   TWILIO_PHONE_NUMBER=<your_twilio_phone>
   ```

3. **Deploy**
   - v01: `https://your-app-v01.onrender.com`
   - v02: `https://your-app-v02.onrender.com`

### Option 2: Update Existing Deployment

Only do this if you're ready to replace v01 completely:

1. Push v02 code to your existing repository
2. Render will auto-deploy
3. **Warning**: This will replace v01 in production

## Data Migration (Optional)

If you need to copy data from v01 to v02:

### Using SQLite

```bash
# Export from v01
cd e:\app_v01
python scripts/backup_manager.py

# Import to v02
cd e:\app_v02
# Manually import the backup or copy the database file
```

### Using PostgreSQL

```bash
# Dump v01 database
pg_dump <v01_database_url> > v01_backup.sql

# Import to v02 database
psql <v02_database_url> < v01_backup.sql
```

## Development Workflow

### Adding New Features to v02

1. **Make changes in v02**
   ```bash
   cd e:\app_v02
   # Edit files
   git add .
   git commit -m "Add new feature"
   ```

2. **Test locally**
   ```bash
   python app.py
   ```

3. **Deploy to v02 staging**
   - Push to v02 repository
   - Render auto-deploys

4. **After testing, merge to v01**
   - Once v02 features are stable
   - Manually merge changes to v01
   - Deploy v01 to production

## Rollback Procedure

If v02 has issues:

1. **Keep v01 running** - it's unaffected
2. **Fix issues in v02** - debug and redeploy
3. **No downtime** - users continue using v01

## Version Checking

### Check Current Version

**Via API:**
```bash
curl http://localhost:5000/version
```

**Response:**
```json
{
  "version": "v02",
  "release_date": "2025-12-22",
  "status": "development",
  "api_name": "Shoe Clinic API"
}
```

## Best Practices

1. **Always test in v02 first** before updating v01
2. **Keep v01 stable** - only deploy tested features
3. **Use separate databases** to avoid data corruption
4. **Document changes** in commit messages
5. **Regular backups** of both v01 and v02 databases

## Troubleshooting

### Port Already in Use

If you get a port conflict:

**Solution 1:** Stop the other version
```bash
# Press Ctrl+C in the running terminal
```

**Solution 2:** Change port in one version
```python
# In app.py, at the bottom:
if __name__ == "__main__":
    app.run(debug=True, port=5001)  # Changed from 5000
```

### Database Not Found

Make sure:
- `.env` file exists in the project root
- `DATABASE_URL` is set correctly
- For SQLite: the path is correct
- For PostgreSQL: connection string is valid

### Migration Errors

```bash
# Reset migrations
rm -rf migrations/
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
```

## Support

For questions or issues:
- Check the README.md
- Review error logs
- Contact the development team
