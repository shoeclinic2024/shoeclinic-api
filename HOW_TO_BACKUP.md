# How to Backup Your Database

## Quick Backup (Before Deployment)

**Just run this:**
```bash
cd e:\app_v02
backup_before_deploy.bat
```

That's it! ?

## What Happens

1. **Creates backup** in `backups/` folder
2. **Names it** with timestamp: `shoeclinic_backup_20251222_125542.db`
3. **Keeps** last 10 backups (auto-deletes older ones)
4. **Shows** confirmation message

## Example Output

```
========================================
  PRE-DEPLOYMENT BACKUP
  Shoe Clinic API
========================================

? Created backup directory: e:\app_v02\backups
? SQLite backup created successfully!
   File: shoeclinic_backup_20251222_125542.db
   Size: 2.45 MB
   Path: e:\app_v02\backups\shoeclinic_backup_20251222_125542.db

???  Removed old backup: shoeclinic_backup_20251201_103022.db
? Kept 10 most recent backups

========================================
  ? BACKUP SUCCESSFUL!
  Safe to deploy now.
========================================
```

## When to Backup

**Always backup before:**
- ? Deploying updates to production
- ? Making database schema changes
- ? Testing major new features
- ? End of each week (for safety)

## Restore from Backup (Emergency)

**If you need to restore:**

1. **Find the backup file:**
   ```bash
   cd e:\app_v02\backups
   dir
   ```

2. **Copy backup to replace current database:**
   ```bash
   # Stop the application first!
   copy shoeclinic_backup_20251222_125542.db ..\instance\shoeclinic.db
   ```

3. **Restart application**

## For Production (PostgreSQL on Render)

**Render provides automatic backups:**
1. Go to Render dashboard
2. Click on your PostgreSQL database
3. Go to "Backups" tab
4. Enable automatic backups

**Manual backup on Render:**
- Click "Create Backup" in dashboard
- Download backup file if needed

## Tips

?? **Best Practice:** Backup before EVERY deployment
?? **Storage:** Backups are stored locally in `backups/` folder
?? **Automatic:** Old backups auto-deleted (keeps 10 recent)
?? **Size:** Backup size shown after creation

---

**Your data is precious. Always backup! ???**
