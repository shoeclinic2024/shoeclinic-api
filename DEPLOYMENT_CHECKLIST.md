# Deployment Checklist

## Before Every Deployment

Follow this checklist to ensure safe deployment:

### 1. ? Create Backup

**Run the backup script:**
```bash
cd e:\app_v02
backup_before_deploy.bat
```

This will:
- Create timestamped backup of your database
- Store in `backups/` folder
- Keep last 10 backups automatically
- Verify backup was successful

### 2. ? Test Locally

**Test all changes locally:**
```bash
cd e:\app_v02
start_app.bat
```

Verify:
- [ ] Application starts without errors
- [ ] All new features work correctly
- [ ] Existing features still work
- [ ] No error messages in console

### 3. ? Update Database (if models changed)

**If you modified `models.py`:**
```bash
flask db migrate -m "Description of changes"
flask db upgrade
```

### 4. ? Commit Changes

**Commit to git:**
```bash
git add .
git commit -m "Description of update"
git push
```

### 5. ? Deploy to Render

**Option A: Auto-Deploy**
- Push to GitHub
- Render auto-deploys

**Option B: Manual Deploy**
- Go to Render dashboard
- Click "Manual Deploy"
- Select "Deploy latest commit"

### 6. ? Verify Deployment

**After deployment:**
- [ ] Visit your production URL
- [ ] Check `/version` endpoint
- [ ] Test login
- [ ] Verify existing data is intact
- [ ] Test new features

## Rollback Plan (If Something Goes Wrong)

### Quick Rollback

**Option 1: Render Dashboard**
1. Go to Render dashboard
2. Find previous deployment
3. Click "Rollback"

**Option 2: Git Revert**
```bash
git revert HEAD
git push
```

### Restore Database (Emergency Only)

**If database is corrupted (RARE):**

1. **Stop the application** on Render

2. **Restore from backup:**
   - SQLite: Copy backup file back
   - PostgreSQL: Use `psql` to restore

   ```bash
   # PostgreSQL restore
   psql \ < backups/shoeclinic_backup_YYYYMMDD_HHMMSS.sql
   ```

3. **Restart application**

## Backup Locations

**Local Backups:**
- Directory: `e:\app_v02\backups\`
- Format: `shoeclinic_backup_YYYYMMDD_HHMMSS.db` (or `.sql`)
- Retention: Last 10 backups kept automatically

**Render Backups:**
- Use Render dashboard to create PostgreSQL backups
- Recommended: Weekly automatic backups

## Emergency Contacts

**If deployment fails:**
1. Check Render deployment logs
2. Review error messages
3. Rollback to previous version
4. Contact development team

## Post-Deployment

- [ ] Monitor application for 10-15 minutes
- [ ] Check for any error logs
- [ ] Verify performance is normal
- [ ] Notify team of successful deployment

---

**Remember:** Always backup before deploying! ???
