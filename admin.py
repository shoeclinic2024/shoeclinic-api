# admin.py
from flask import Blueprint, render_template, flash, request, redirect, url_for, jsonify, send_file
from flask_login import login_required, current_user
from database import db
from models import User, Expense
import io
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import extract, func
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'super_admin']:
            flash("Access denied. Authorized personnel only.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            flash("Access denied. Owner privileges required.", "danger")
            return redirect(request.referrer or url_for('home'))
        return f(*args, **kwargs)
    return decorated_function



# Define Blueprint
admin_bp = Blueprint("admin", __name__, template_folder="templates")

# Admin Panel Home
@admin_bp.route("/panel", endpoint="admin_panel")
@login_required
@admin_required
def panel():
    data = {}
    if current_user.role == 'super_admin':
        # Get counts for the Superior Control badge
        data['pending_users'] = User.query.filter_by(is_active=False).count()
        data['pending_expenses'] = Expense.query.filter_by(status='pending').count()
        data['pending_access'] = User.query.filter_by(customer_view_requested=True).count()
        data['total_pending'] = data['pending_users'] + data['pending_expenses'] + data['pending_access']
    
    # Detect Database Engine
    from flask import current_app
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'postgresql' in db_uri or 'postgres' in db_uri:
        data['db_engine'] = 'PostgreSQL (Production)'
    else:
        data['db_engine'] = 'SQLite (Local)'
    
    return render_template("admin_panel.html", now=datetime.utcnow(), **data)

# Manage Users
@admin_bp.route("/manage_users")
@login_required
@admin_required
def manage_users():
    try:
        users = User.query.order_by(User.username).all()
        print(f"DEBUG: Found {len(users)} users")
        for user in users:
            print(f"  - {user.username} (role: {user.role}, active: {user.is_active})")
        return render_template("admin/manage_users.html", users=users)
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading users: {str(e)}", "danger")
        return render_template("admin/manage_users.html", users=[])

# Analytics Dashboard
@admin_bp.route("/analytics")
@login_required
@admin_required
def analytics():
    try:
        from datetime import datetime, timedelta
        from models import Order
        
        # Get all orders
        all_orders = Order.query.all()
        today = datetime.utcnow().date()
        
        # Generate list of available months and years for dropdowns if needed
        available_months = []
        available_years = []
        for order in all_orders:
            if order.pickup_date:
                m_key, y_key = order.pickup_date.strftime('%Y-%m'), str(order.pickup_date.year)
                if m_key not in available_months: available_months.append(m_key)
                if y_key not in available_years: available_years.append(y_key)
        
        available_months.sort(reverse=True)
        available_years.sort(reverse=True)
        
        # Week range
        this_week_start = today - timedelta(days=today.weekday())
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(days=1)
        
        def get_service_analysis(orders):
            stats = {}
            for order in orders:
                for item in order.items:
                    if item.services:
                        for svc in item.services.split(','):
                            svc = svc.strip()
                            if svc:
                                if svc not in stats: stats[svc] = {'name': svc, 'count': 0, 'revenue': 0}
                                stats[svc]['count'] += 1
                                stats[svc]['revenue'] += float(item.price or 0)
            
            sorted_stats = sorted(stats.values(), key=lambda x: x['revenue'], reverse=True)
            total_svcs = sum(s['count'] for s in sorted_stats)
            top_svc = sorted_stats[0]['name'] if sorted_stats else "N/A"
            return sorted_stats, total_svcs, top_svc

        def get_metrics(orders):
            total_rev = sum([float(o.price or 0) for o in orders])
            total_discount = sum([float(o.discount or 0) if o.discount else 0 for o in orders])
            
            # Billed Revenue: Sum of price for orders with specific payment status
            billed_rev = sum([float(o.price or 0) for o in orders if o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']])
            
            # Status Analysis
            total = len(orders)
            done = len([o for o in orders if o.status and 'done' in o.status.lower()])
            wip = len([o for o in orders if o.status and 'wip' in o.status.lower()])
            yts = len([o for o in orders if o.status and ('yts' in o.status.lower() or 'yet' in o.status.lower())])
            
            # Billing Logic
            billed_count = len([o for o in orders if o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']])
            unbilled_count = total - billed_count
            
            # Service sub-analysis
            _, total_svcs, top_svc = get_service_analysis(orders)
            
            return {
                'revenue': total_rev,
                'billed_revenue': billed_rev,
                'discount': total_discount,
                'net': total_rev - total_discount,
                'orders': total,
                'completed': done,
                'wip': wip,
                'yts': yts,
                'billed': billed_count,
                'unbilled': unbilled_count,
                'pending': total - done,
                'completion_rate': (done / total * 100) if total > 0 else 0,
                'billing_rate': (billed_count / total * 100) if total > 0 else 0,
                'avg_order_value': (total_rev / total) if total > 0 else 0,
                'total_services': total_svcs,
                'top_service': top_svc,
                'svcs_per_order': (total_svcs / total) if total > 0 else 0
            }
        
        this_week_orders = [o for o in all_orders if o.pickup_date and this_week_start <= o.pickup_date.date() <= today]
        last_week_orders = [o for o in all_orders if o.pickup_date and last_week_start <= o.pickup_date.date() <= last_week_end]
        
        this_week = get_metrics(this_week_orders)
        last_week = get_metrics(last_week_orders)
        
        def calc_growth(current, previous):
            if previous == 0:
                return 0 if current == 0 else 100
            return ((current - previous) / previous * 100)
        
        week_growth = calc_growth(this_week['revenue'], last_week['revenue'])
        
        # Simplified Filter Logic
        filter_type = request.args.get('filter_type', 'month')  # daily, month, year
        filter_date = request.args.get('filter_date', today.strftime('%Y-%m-%d'))
        filter_month = request.args.get('filter_month', today.strftime('%Y-%m'))
        filter_year = request.args.get('filter_year', str(today.year))

        # Main Analysis Period
        if filter_type == 'daily':
            try:
                d1_start = datetime.strptime(filter_date, '%Y-%m-%d').date()
                d1_end = d1_start
            except:
                d1_start = d1_end = today
            month1_label = d1_start.strftime('%d %B %Y')
            # Compare to previous day
            d2_start = d2_end = d1_start - timedelta(days=1)
            month2_label = d2_start.strftime('%d %B %Y')
        elif filter_type == 'year':
            try:
                y_val = int(filter_year)
                d1_start = datetime(year=y_val, month=1, day=1).date()
                d1_end = datetime(year=y_val, month=12, day=31).date()
            except:
                d1_start = datetime(year=today.year, month=1, day=1).date()
                d1_end = datetime(year=today.year, month=12, day=31).date()
            month1_label = f"Year {d1_start.year}"
            # Compare to previous year
            d2_start = d1_start.replace(year=d1_start.year - 1)
            d2_end = d1_end.replace(year=d1_end.year - 1)
            month2_label = f"Year {d2_start.year}"
        else: # monthly (default)
            try:
                d1_start = datetime.strptime(filter_month, '%Y-%m').date()
            except:
                d1_start = today.replace(day=1)
            
            if d1_start.month == 12:
                d1_end = d1_start.replace(year=d1_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                d1_end = d1_start.replace(month=d1_start.month + 1, day=1) - timedelta(days=1)
            month1_label = d1_start.strftime('%B %Y')
            
            # Compare to previous month
            d2_start = (d1_start - timedelta(days=1)).replace(day=1)
            if d2_start.month == 12:
                d2_end = d2_start.replace(year=d2_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                d2_end = d2_start.replace(month=d2_start.month + 1, day=1) - timedelta(days=1)
            month2_label = d2_start.strftime('%B %Y')

        # Filter Orders for selected periods
        month1_orders = [o for o in all_orders if o.pickup_date and d1_start <= o.pickup_date.date() <= d1_end]
        month2_orders = [o for o in all_orders if o.pickup_date and d2_start <= o.pickup_date.date() <= d2_end]
        
        month1 = get_metrics(month1_orders)
        month2 = get_metrics(month2_orders)
        month_growth = calc_growth(month1['revenue'], month2['revenue'])
        
        # Service Analysis for filtered period
        service_list, _, _ = get_service_analysis(month1_orders)
        
        # Yearly defaults (for template backwards compatibility if needed)
        year1 = month1 if filter_type == 'year' else get_metrics([o for o in all_orders if o.pickup_date and o.pickup_date.year == today.year])
        year2 = month2 if filter_type == 'year' else get_metrics([o for o in all_orders if o.pickup_date and o.pickup_date.year == today.year - 1])
        year_growth = calc_growth(year1['revenue'], year2['revenue'])
        year1_label = str(today.year)
        year2_label = str(today.year - 1)
        
        # ===== TECHNICIAN PERFORMANCE (Filtered by Selected Period) =====
        technician_stats = {}
        for order in month1_orders:
            if order.technician and order.technician != 'None':
                if order.technician not in technician_stats:
                    technician_stats[order.technician] = {
                        'name': order.technician,
                        'orders': 0,
                        'revenue': 0,
                        'completed': 0,
                        'pending': 0
                    }
                tech = technician_stats[order.technician]
                tech['orders'] += 1
                tech['revenue'] += float(order.price or 0)
                if order.status and 'done' in order.status.lower():
                    tech['completed'] += 1
                else:
                    tech['pending'] += 1
        
        technician_list = sorted(technician_stats.values(), key=lambda x: x['revenue'], reverse=True)
        for tech in technician_list:
            tech['completion_rate'] = (tech['completed'] / tech['orders'] * 100) if tech['orders'] > 0 else 0
            tech['avg_per_order'] = (tech['revenue'] / tech['orders']) if tech['orders'] > 0 else 0
        
        # ===== MONTHLY TREND =====
        monthly_trend = {}
        for i in range(12, -1, -1):
            month_date = today - timedelta(days=30*i)
            month_key = month_date.strftime('%b %Y')
            month_start = month_date.replace(day=1)
            if month_date.month == 12:
                month_end = month_date.replace(year=month_date.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)
            
            month_orders = [o for o in all_orders if o.pickup_date and month_start <= o.pickup_date.date() <= month_end]
            m_metrics = get_metrics(month_orders)

            monthly_trend[month_key] = {
                'revenue': m_metrics['revenue'],
                'billed_revenue': m_metrics['billed_revenue'],
                'orders': m_metrics['orders'],
                'services': m_metrics['total_services']
            }
        
        return render_template("admin/analytics.html",
                             filter_type=filter_type,
                             filter_date=filter_date,
                             filter_month=filter_month,
                             filter_year=filter_year,
                             this_week=this_week,
                             last_week=last_week,
                             week_growth=week_growth,
                             month1=month1,
                             month2=month2,
                             month1_label=month1_label,
                             month2_label=month2_label,
                             month_growth=month_growth,
                             year1=year1,
                             year2=year2,
                             year_growth=year_growth,
                             technician_list=technician_list,
                             service_list=service_list,
                             monthly_trend=monthly_trend)
    
    except Exception as e:
        print(f"ERROR in analytics: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading analytics: {str(e)}", "danger")
        return redirect(url_for('admin.admin_panel'))

@admin_bp.route("/export_analytics_excel")
@login_required
@super_admin_required
def export_analytics_excel():
    from models import Order
    compare_month1 = request.args.get('compare_month1')
    
    all_orders = Order.query.all()
    today = datetime.utcnow().date()
    
    if compare_month1:
        date1 = datetime.strptime(compare_month1, '%Y-%m').date()
    else:
        date1 = today.replace(day=1)
        compare_month1 = date1.strftime('%Y-%m')

    if date1.month == 12:
        month_end = date1.replace(year=date1.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = date1.replace(month=date1.month + 1, day=1) - timedelta(days=1)

    orders = [o for o in all_orders if o.pickup_date and date1 <= o.pickup_date.date() <= month_end]
    
    data = []
    for o in orders:
        services = []
        for item in o.items:
            if item.services:
                services.extend([s.strip() for s in item.services.split(',') if s.strip()])
        
        data.append({
            'Order ID': o.id,
            'Customer': o.customer_name,
            'Pickup Date': o.pickup_date.strftime('%d-%b-%Y') if o.pickup_date else '-',
            'Status': o.status,
            'Technician': o.technician or 'None',
            'Services': ', '.join(services),
            'Total Amount': float(o.price or 0),
            'Discount': float(o.discount or 0)
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Orders')
    output.seek(0)
    
    filename = f"Analytics_Report_{compare_month1}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def add_watermark(canvas, doc):
    """Add watermark to PDF pages"""
    canvas.saveState()
    canvas.setFont('Helvetica-Bold', 55)
    canvas.setFillGray(0.85)
    canvas.translate(300, 400)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "The Shoe Clinic")
    canvas.restoreState()

@admin_bp.route("/export_analytics_pdf")

@login_required
@super_admin_required
def export_analytics_pdf():
    from models import Order
    compare_month1 = request.args.get('compare_month1')
    
    all_orders = Order.query.all()
    today = datetime.utcnow().date()
    
    if compare_month1:
        date1 = datetime.strptime(compare_month1, '%Y-%m').date()
    else:
        date1 = today.replace(day=1)
        compare_month1 = date1.strftime('%Y-%m')

    if date1.month == 12:
        month_end = date1.replace(year=date1.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = date1.replace(month=date1.month + 1, day=1) - timedelta(days=1)

    orders = [o for o in all_orders if o.pickup_date and date1 <= o.pickup_date.date() <= month_end]
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    elements.append(Paragraph(f"Analytics Order Report - {compare_month1}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    data = [['ID', 'Customer', 'Date', 'Technician', 'Amount']]
    total = 0
    for o in orders:
        price = float(o.price or 0)
        data.append([
            o.id,
            o.customer_name[:15],
            o.pickup_date.strftime('%d-%b') if o.pickup_date else '-',
            o.technician or 'None',
            f"INR {price:.2f}"
        ])
        total += price
    
    data.append(['', '', '', 'TOTAL', f"INR {total:.2f}"])
    
    t = Table(data, colWidths=[40, 150, 80, 100, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey)
    ]))
    
    elements.append(t)
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    
    filename = f"Analytics_Report_{compare_month1}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')

# Reports
@admin_bp.route("/reports")
@login_required
@admin_required
def reports():
    try:
        from datetime import datetime, timedelta
        
        # Get parameters from query string
        report_date = request.args.get('date', None)
        week_start = request.args.get('week_start', None)
        year = request.args.get('year', None)
        month = request.args.get('month', None)
        
        # Convert to proper types
        today = datetime.utcnow().date()
        current_year = today.year
        current_month = today.month
        
        if report_date:
            try:
                report_date = datetime.strptime(report_date, '%Y-%m-%d').date()
            except:
                report_date = today
        else:
            report_date = today
        
        if year:
            year = int(year)
        else:
            year = current_year
            
        if month:
            month = int(month)
        else:
            month = current_month
        
        # Calculate week start for weekly report
        if week_start:
            try:
                week_start = datetime.strptime(week_start, '%Y-%m-%d').date()
            except:
                week_start = today - timedelta(days=today.weekday())
        else:
            week_start = today - timedelta(days=today.weekday())
        
        from app import get_daily_report, get_weekly_report, get_monthly_report, get_yearly_report
        
        daily = get_daily_report(report_date)
        weekly = get_weekly_report(week_start)
        monthly = get_monthly_report(year, month)
        yearly = get_yearly_report(year)
        
        # Get list of years and months available
        from models import Order
        all_orders = Order.query.all()
        years = sorted(set([o.pickup_date.year for o in all_orders if o.pickup_date]), reverse=True)
        selected_year = year or current_year
        months_in_year = sorted(set([o.pickup_date.month for o in all_orders if o.pickup_date and o.pickup_date.year == selected_year]))
        
        return render_template("admin/reports.html", 
                             daily=daily, 
                             weekly=weekly, 
                             monthly=monthly, 
                             yearly=yearly,
                             years=years,
                             months_in_year=months_in_year,
                             selected_year=selected_year,
                             selected_month=month or current_month,
                             selected_date=report_date,
                             selected_week_start=week_start)
    except Exception as e:
        print(f"ERROR in reports: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading reports: {str(e)}", "danger")
        
        # Return empty dicts with all required keys
        empty_report = {
            'date': None,
            'month': None,
            'year': None,
            'total_orders': 0,
            'completed': 0,
            'pending': 0,
            'total_revenue': 0,
            'total_discount': 0,
            'orders': [],
            'week_start': None,
            'week_end': None,
            'month_start': None,
            'month_end': None,
            'year_start': None,
            'year_end': None
        }
        
        return render_template("admin/reports.html", 
                             daily=empty_report, 
                             weekly=empty_report, 
                             monthly=empty_report, 
                             yearly=empty_report)




# Work Assign

@admin_bp.route("/work_assign")
@login_required
@super_admin_required
def work_assign():
    from models import Order, User
    # Fetch orders that are not fully completed
    active_orders = Order.query.filter(Order.status != 'done').order_by(Order.created_at.desc()).all()
    # Fetch active staff (admins and employees)
    staff = User.query.filter_by(is_active=True).all()
    return render_template("admin/work_assign.html", orders=active_orders, staff=staff)

@admin_bp.route("/assign_task", methods=["POST"])
@login_required
@super_admin_required
def assign_task():
    from models import Order, OrderItem
    import json
    
    order_id = request.form.get("order_id")
    item_id = request.form.get("item_id")
    service_name = request.form.get("service_name")
    technician_name = request.form.get("technician")
    
    try:
        if item_id:
            item = OrderItem.query.get(item_id)
            if item:
                if service_name:
                    # Assign specific service
                    assignments = json.loads(item.service_assignments) if item.service_assignments else {}
                    statuses = json.loads(item.service_statuses) if item.service_statuses else {}
                    
                    assignments[service_name] = technician_name
                    if service_name not in statuses:
                        statuses[service_name] = 'yts'
                        
                    item.service_assignments = json.dumps(assignments)
                    item.service_statuses = json.dumps(statuses)
                    flash(f"Service '{service_name}' assigned to {technician_name} ✅", "success")
                else:
                    # Assign whole item
                    item.technician = technician_name
                    assignments = {}
                    statuses = json.loads(item.service_statuses) if item.service_statuses else {}
                    if item.services:
                        for s in item.services.split(','):
                            name = s.strip()
                            assignments[name] = technician_name
                            if name not in statuses:
                                statuses[name] = 'yts'
                    item.service_assignments = json.dumps(assignments)
                    item.service_statuses = json.dumps(statuses)
                    flash(f"Item assigned to {technician_name} ✅", "success")
                db.session.commit()
        elif order_id:
            order = Order.query.get(order_id)
            if order:
                order.technician = technician_name
                # Also auto-assign to all items
                for item in order.items:
                    item.technician = technician_name
                    assignments = {}
                    statuses = json.loads(item.service_statuses) if item.service_statuses else {}
                    if item.services:
                        for s in item.services.split(','):
                            name = s.strip()
                            assignments[name] = technician_name
                            if name not in statuses:
                                statuses[name] = 'yts'
                    item.service_assignments = json.dumps(assignments)
                    item.service_statuses = json.dumps(statuses)
                db.session.commit()
                flash(f"Whole Order {order.job_id} assigned to {technician_name} ✅", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error assigning task: {str(e)}", "danger")
            
    return redirect(url_for("admin.work_assign"))



def _get_customer_data():
    from models import Order
    from sqlalchemy import func
    
    # Determine if we should group by mobile or name if mobile is missing
    # Since mobile is primary key for customer uniqueness as per request
    
    # We filter out records with no mobile to avoid grouping them all into one 'None' customer
    # If mobile is missing, we might (optionally) fall back to name, but user insisted on mobile.
    
    results = db.session.query(
        func.trim(Order.mobile).label('mobile'),
        func.max(Order.customer_name).label('name'),
        func.max(Order.place).label('place'),
        func.count(Order.id).label('order_count'),
        func.sum(Order.price).label('total_spent'),
        func.max(Order.pickup_date).label('last_visit')
    ).filter(
        Order.mobile.isnot(None), 
        Order.mobile != '',
        Order.mobile != '-'
    ).group_by(func.trim(Order.mobile)).order_by(func.max(Order.pickup_date).desc()).all()
    
    customers = []
    for r in results:
        customers.append({
            'mobile': r.mobile,
            'name': r.name,
            'place': r.place,
            'order_count': r[3],
            'total_spent': r[4] or 0,
            'last_visit': r[5]
        })
    return customers

# Customer Database
@admin_bp.route("/customers")
@login_required
def customer_database():
    # Helper to revoke and redirect
    def revoke_access(msg):
        current_user.can_view_customers = False
        current_user.can_export_customers = False
        current_user.customer_access_expiry = None
        current_user.customer_view_requested = False
        db.session.commit()
        flash(msg, "warning")
        return redirect(url_for('admin.admin_panel'))

    # Permission Check
    if current_user.role != 'super_admin':
        if not current_user.can_view_customers:
            flash("Access to Customer Database is restricted.", "danger")
            return redirect(url_for('admin.admin_panel'))
        
        # Check Expiry
        if current_user.customer_access_expiry:
            if datetime.utcnow() > current_user.customer_access_expiry:
                return revoke_access("Your temporary access to the Customer Database has expired.")
        
    customers = _get_customer_data()
    return render_template("admin/customer_database.html", customers=customers)

@admin_bp.route("/request_customer_access")
@login_required
def request_customer_access():
    if current_user.role == 'super_admin':
        flash("You are Super Admin, you already have access!", "info")
        return redirect(url_for("admin.admin_panel"))
        
    # Check if access is currently active and not expired
    is_active = current_user.can_view_customers
    is_expired = current_user.customer_access_expiry and datetime.utcnow() > current_user.customer_access_expiry
    
    if is_active and not is_expired:
        flash("You already have access to the database.", "info")
    else:
        # Reset everything and set request flag
        current_user.can_view_customers = False
        current_user.can_export_customers = False
        current_user.customer_access_expiry = None
        current_user.customer_view_requested = True
        db.session.commit()
        flash("Access request sent to Super Admin.", "success")
        
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/export_customers_excel")
@login_required
def export_customers_excel():
    # Permission Check
    if current_user.role != 'super_admin' and not current_user.can_export_customers:
        flash("Export access denied.", "danger")
        return redirect(url_for('admin.customer_database'))

    customers = _get_customer_data()
    
    data = []
    for c in customers:
        data.append({
            'Customer Name': c['name'],
            'Mobile': c['mobile'],
            'Place': c['place'] or '-',
            'Total Orders': c['order_count'],
            'Total Spent': c['total_spent'],
            'Last Visit': c['last_visit'].strftime('%d-%b-%Y') if c['last_visit'] else '-'
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Customers')
    output.seek(0)
    
    filename = f"Customer_Database_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@admin_bp.route("/export_customers_pdf")
@login_required
def export_customers_pdf():
    # Permission Check
    if current_user.role != 'super_admin' and not current_user.can_export_customers:
        flash("Export access denied.", "danger")
        return redirect(url_for('admin.customer_database'))

    customers = _get_customer_data()
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    elements.append(Paragraph("Customer Database Report", styles['Title']))
    elements.append(Paragraph(f"Generated on: {datetime.utcnow().strftime('%d-%b-%Y')}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    data = [['Name', 'Mobile', 'Place', 'Orders', 'Spent', 'Last Visit']]
    
    for c in customers:
        data.append([
            c['name'][:15] if c['name'] else '-',
            c['mobile'],
            c['place'][:10] if c['place'] else '-',
            str(c['order_count']),
            f"{c['total_spent']:.0f}",
            c['last_visit'].strftime('%d-%b') if c['last_visit'] else '-'
        ])
        
    t = Table(data, colWidths=[100, 80, 80, 50, 60, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    
    elements.append(t)
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    
    filename = f"Customer_Database_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')

    


@admin_bp.route("/toggle_customer_view/<int:user_id>")
@login_required
@super_admin_required
def toggle_customer_view(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'super_admin':
        flash("Cannot modify permissions for Super Admin.", "warning")
    else:
        user.can_view_customers = not user.can_view_customers
        # Reset request flag if access is granted
        if user.can_view_customers:
            user.customer_view_requested = False
            
        db.session.commit()
        status = "enabled" if user.can_view_customers else "disabled"
        flash(f"Customer View {status} for {user.username}.", "success")
        
    return redirect(url_for('admin.manage_users'))

# Add Expense Form (Action)

@admin_bp.route("/add_expense", methods=["GET", "POST"])
@login_required
@admin_required
def add_expense():
    from datetime import datetime
    
    if request.method == "POST":
        try:
            title = request.form.get("title")
            amount = float(request.form.get("amount"))
            category = request.form.get("category")
            description = request.form.get("description")
            date_str = request.form.get("expense_date")
            expense_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            # Determine status based on role
            status = 'approved' if current_user.role == 'super_admin' else 'pending'
            
            new_expense = Expense(
                title=title,
                amount=amount,
                category=category,
                description=description,
                expense_date=expense_date,
                status=status,
                added_by=current_user.id
            )
            
            db.session.add(new_expense)
            db.session.commit()
            
            if status == 'approved':
                flash("Expense added and approved! ✅", "success")
            else:
                flash("Expense submitted for Owner approval. ⏳", "info")
            
            return redirect(url_for('home')) 
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding expense: {str(e)}", "danger")
    
    today_date = datetime.utcnow().strftime("%Y-%m-%d")
    return render_template("admin/add_expense.html", today_date=today_date)

# Day to Day Expense (View)
def _get_filtered_expenses(args):
    from sqlalchemy import extract
    
    filter_type = args.get('filter_type', 'month')
    selected_date_str = args.get('date_{}'.format(filter_type)) or args.get('date')
    selected_category = args.get('category', '')

    query = Expense.query.filter_by(status='approved')
    today = datetime.utcnow().date()
    selected_date = today 
    display_date = today.strftime('%Y-%m')

    if filter_type == 'month':
        if selected_date_str:
            try:
                year, month = map(int, selected_date_str.split('-'))
                query = query.filter(extract('year', Expense.expense_date) == year,
                                     extract('month', Expense.expense_date) == month)
                display_date = selected_date_str
                selected_date = datetime(year, month, 1).date()
            except ValueError:
                selected_date_str = None
        
        if not selected_date_str:
            query = query.filter(extract('year', Expense.expense_date) == today.year,
                                 extract('month', Expense.expense_date) == today.month)
            display_date = today.strftime('%Y-%m')

    elif filter_type == 'date':
        if selected_date_str:
            try:
                selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
                display_date = selected_date.strftime('%Y-%m-%d')
            except ValueError:
                selected_date = today
        else:
            display_date = today.strftime('%Y-%m-%d')
        query = query.filter(Expense.expense_date == selected_date)

    elif filter_type == 'year':
        if selected_date_str:
            try:
                year = int(selected_date_str)
                query = query.filter(extract('year', Expense.expense_date) == year)
                display_date = str(year)
                selected_date = datetime(year, 1, 1).date()
            except ValueError:
                selected_date_str = None
        
        if not selected_date_str:
            year = today.year
            query = query.filter(extract('year', Expense.expense_date) == year)
            display_date = str(year)

    elif filter_type == 'range':
        start_date_str = args.get('start_date')
        end_date_str = args.get('end_date')
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                query = query.filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
                display_date = f"{start_date_str} to {end_date_str}"
                selected_date = start_date
            except ValueError:
                pass
        else:
            # Fallback to last 7 days if no range provided
            start_date = today - timedelta(days=7)
            query = query.filter(Expense.expense_date >= start_date, Expense.expense_date <= today)
            display_date = f"{start_date} to {today}"

    if selected_category:
        query = query.filter(Expense.category == selected_category)

    expenses = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
    return expenses, filter_type, display_date, selected_date, selected_category

# Day to Day Expense (View)
@admin_bp.route("/day_to_day_expense")
@login_required
@admin_required
def day_to_day_expense():
    expenses, filter_type, display_date, selected_date, selected_category = _get_filtered_expenses(request.args)
    
    total_amount = sum(e.amount for e in expenses)
    transaction_count = len(expenses)
    
    categories = ["Rent", "Utilities", "Salaries", "Salary Advance", "Supplies", "Marketing", "Petrol", "Maintenance", "Other"]

    return render_template("admin/day_to_day_expense.html", 
                         expenses=expenses, 
                         total_amount=total_amount,
                         transaction_count=transaction_count,
                         timedelta=timedelta,
                         filter_type=filter_type,
                         display_date=display_date,
                         selected_date=selected_date,
                         selected_category=selected_category,
                         categories=categories)

@admin_bp.route("/export_expenses_excel")
@login_required
@super_admin_required
def export_expenses_excel():
    expenses, filter_type, display_date, _, _ = _get_filtered_expenses(request.args)
    
    data = []
    for e in expenses:
        data.append({
            'Date': e.expense_date.strftime('%d-%b-%Y'),
            'Title': e.title,
            'Category': e.category,
            'Description': e.description or '-',
            'Amount': e.amount,
            'Added At': e.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Expenses')
        
    output.seek(0)
    
    filename = f"Expenses_Report_{display_date}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@admin_bp.route("/export_expenses_pdf")
@login_required
@super_admin_required
def export_expenses_pdf():
    expenses, filter_type, display_date, _, _ = _get_filtered_expenses(request.args)
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    # Title
    elements.append(Paragraph(f"Expense Report - {display_date}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Table Header
    data = [['Date', 'Title', 'Category', 'Description', 'Amount']]
    
    total = 0
    for e in expenses:
        data.append([
            e.expense_date.strftime('%d-%b-%Y'),
            e.title,
            e.category,
            e.description or '-',
            f"INR {e.amount:.2f}"
        ])
        total += e.amount
    
    # Add Total Row
    data.append(['', '', '', 'TOTAL', f"INR {total:.2f}"])
    
    # Create Table
    t = Table(data, colWidths=[80, 120, 80, 150, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(t)
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    
    output.seek(0)
    filename = f"Expenses_Report_{display_date}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')

@admin_bp.route("/expense_chart_data")
@login_required
@admin_required
def expense_chart_data():
    from datetime import datetime
    from sqlalchemy import extract
    
    filter_type = request.args.get('filter_type', 'month')
    date_str = request.args.get('date')
    selected_cat = request.args.get('category', '')
    
    try:
        if date_str:
            ref_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            ref_date = datetime.utcnow().date()
    except ValueError:
        ref_date = datetime.utcnow().date()
        
    query = Expense.query.filter_by(status='approved')
    
    # Apply Time Filter
    if filter_type == 'month':
        query = query.filter(extract('year', Expense.expense_date) == ref_date.year,
                             extract('month', Expense.expense_date) == ref_date.month)
    elif filter_type == 'year':
        query = query.filter(extract('year', Expense.expense_date) == ref_date.year)
    elif filter_type == 'range':
        s_date = request.args.get('start_date')
        e_date = request.args.get('end_date')
        if s_date and e_date:
            try:
                start = datetime.strptime(s_date, '%Y-%m-%d').date()
                end = datetime.strptime(e_date, '%Y-%m-%d').date()
                query = query.filter(Expense.expense_date >= start, Expense.expense_date <= end)
            except ValueError:
                pass

    # Apply Category Filter (Optional) - only for trend line
    trend_query = query
    if selected_cat:
        trend_query = trend_query.filter(Expense.category == selected_cat)

    # Fetch all matching expenses for this period
    all_expenses = query.all()
    trend_expenses = trend_query.all()
    
    # 1. Calculate Summary (from ALL categories in this period)
    total_amount = sum(e.amount for e in all_expenses)
    
    cat_summary = {}
    for e in all_expenses:
        cat_summary[e.category] = cat_summary.get(e.category, 0) + e.amount
    
    largest_cat_name = "N/A"
    largest_cat_amount = 0
    if cat_summary:
        largest_cat_name = max(cat_summary, key=cat_summary.get)
        largest_cat_amount = cat_summary[largest_cat_name]

    # 2. Time Trend Data (from TREND query)
    time_groups = {}
    labels = []
    
    if filter_type == 'month':
        for e in trend_expenses:
            day = e.expense_date.day
            time_groups[day] = time_groups.get(day, 0) + e.amount
        labels = sorted(time_groups.keys())
    elif filter_type == 'year':
        for e in trend_expenses:
            month = e.expense_date.month
            time_groups[month] = time_groups.get(month, 0) + e.amount
        labels = sorted(time_groups.keys())
    elif filter_type == 'range':
        s_date = request.args.get('start_date')
        e_date = request.args.get('end_date')
        try:
            start = datetime.strptime(s_date, '%Y-%m-%d').date()
            end = datetime.strptime(e_date, '%Y-%m-%d').date()
            diff = (end - start).days
            
            if diff <= 62: # Up to 2 months, show daily
                for e in trend_expenses:
                    d_key = e.expense_date.strftime('%d %b')
                    time_groups[d_key] = time_groups.get(d_key, 0) + e.amount
                # Sort by date properly
                labels = sorted(time_groups.keys(), key=lambda x: datetime.strptime(x, '%d %b'))
            else: # Larger range, show monthly
                for e in trend_expenses:
                    m_key = e.expense_date.strftime('%b %Y')
                    time_groups[m_key] = time_groups.get(m_key, 0) + e.amount
                labels = sorted(time_groups.keys(), key=lambda x: datetime.strptime(x, '%b %Y'))
        except (ValueError, TypeError):
            # Fallback
            for e in trend_expenses:
                day = e.expense_date.day
                time_groups[day] = time_groups.get(day, 0) + e.amount
            labels = sorted(time_groups.keys())

    time_data = [time_groups[l] for l in labels]

    # 3. Category Distribution (from ALL categories in this period)
    cat_labels = list(cat_summary.keys())
    cat_data = [cat_summary[l] for l in cat_labels]
        
    return jsonify({
        'by_category': {
            'labels': cat_labels,
            'data': [float(d) for d in cat_data]
        },
        'by_time': {
            'labels': labels,
            'data': [float(d) for d in time_data]
        },
        'summary': {
            'total': total_amount,
            'top_cat_name': largest_cat_name,
            'top_cat_amount': largest_cat_amount
        }
    })

# Payouts
@admin_bp.route("/payouts")
@login_required
@admin_required
def payouts():
    try:
        from sqlalchemy import extract
        from datetime import datetime
        
        filter_type = request.args.get('filter_type', 'month')
        selected_date_str = request.args.get('date_{}'.format(filter_type)) or request.args.get('date')
        
        query = Expense.query.filter(Expense.category.in_(['Salaries', 'Salary']))
        today = datetime.utcnow().date()
        selected_date = today 
        display_date = today.strftime('%Y-%m')

        if filter_type == 'month':
            if selected_date_str:
                try:
                    year, month = map(int, selected_date_str.split('-'))
                    query = query.filter(extract('year', Expense.expense_date) == year,
                                         extract('month', Expense.expense_date) == month)
                    display_date = selected_date_str
                    selected_date = datetime(year, month, 1).date()
                except ValueError:
                    selected_date_str = None
            
            if not selected_date_str:
                query = query.filter(extract('year', Expense.expense_date) == today.year,
                                     extract('month', Expense.expense_date) == today.month)
                display_date = today.strftime('%Y-%m')

        elif filter_type == 'year':
            if selected_date_str:
                try:
                    year = int(selected_date_str)
                    query = query.filter(extract('year', Expense.expense_date) == year)
                    display_date = str(year)
                    selected_date = datetime(year, 1, 1).date()
                except ValueError:
                    selected_date_str = None
            
            if not selected_date_str:
                year = today.year
                query = query.filter(extract('year', Expense.expense_date) == year)
                display_date = str(year)

        expenses = query.order_by(Expense.expense_date.desc()).all()
        total_payout = sum(e.amount for e in expenses)
        
        return render_template("admin/payouts.html", 
                             expenses=expenses, 
                             total_payout=total_payout,
                             filter_type=filter_type,
                             display_date=display_date,
                             selected_date=selected_date)
    except Exception as e:
        flash(f"Error loading payouts: {str(e)}", "danger")
        return redirect(url_for('admin.admin_panel'))

# Technician Status
@admin_bp.route("/technician_status")
@login_required
@admin_required
def technician_status():
    return "<h3>Technician Status (to be implemented)</h3>"

# --- SUPER ADMIN (OWNER) ACTIONS ---

@admin_bp.route("/pending_approvals")
@login_required
@super_admin_required
def pending_approvals():
    pending_users = User.query.filter_by(is_active=False).all()
    pending_expenses = Expense.query.filter_by(status='pending').all()
    access_requests = User.query.filter_by(customer_view_requested=True).all()
    
    # Also fetch currently authorized users for manual control
    authorized_users = User.query.filter(User.can_view_customers == True, User.role != 'super_admin').all()
    
    return render_template("admin/pending_approvals.html", 
                         users=pending_users, 
                         expenses=pending_expenses,
                         access_requests=access_requests,
                         authorized_users=authorized_users)

@admin_bp.route("/approve_customer_access/<int:user_id>")
@login_required
@super_admin_required
def approve_customer_access(user_id):
    user = User.query.get_or_404(user_id)
    export_perm = request.args.get('export', 'false') == 'true'
    duration_hours = request.args.get('duration', type=int) # If None, it's permanent
    
    user.can_view_customers = True
    user.customer_view_requested = False
    user.can_export_customers = export_perm
    
    if duration_hours:
        user.customer_access_expiry = datetime.utcnow() + timedelta(hours=duration_hours)
    else:
        user.customer_access_expiry = None # Permanent until revoked manually
        
    db.session.commit()
    
    expiry_msg = f"Expires in {duration_hours}h" if duration_hours else "Permanent"
    msg = f"Access granted to {user.username} (Export: {'Yes' if export_perm else 'No'}, {expiry_msg})."
    flash(msg, "success")
    return redirect(url_for('admin.pending_approvals'))

@admin_bp.route("/toggle_customer_export/<int:user_id>")
@login_required
@super_admin_required
def toggle_customer_export(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'super_admin':
        flash("Cannot modify Super Admin.", "warning")
    else:
        user.can_export_customers = not user.can_export_customers
        db.session.commit()
        status = "enabled" if user.can_export_customers else "disabled"
        flash(f"Customer Export {status} for {user.username}.", "success")
    return redirect(url_for('admin.manage_users'))

@admin_bp.route("/approve_user/<int:user_id>")
@login_required
@super_admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f"User {user.username} approved successfully! ✅", "success")
    return redirect(url_for('admin.pending_approvals'))

@admin_bp.route("/approve_expense/<int:expense_id>")
@login_required
@super_admin_required
def approve_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    expense.status = 'approved'
    db.session.commit()
    flash(f"Expense '{expense.title}' approved and reflected in reports! ✅", "success")
    return redirect(url_for('admin.pending_approvals'))

@admin_bp.route("/reject_expense/<int:expense_id>")
@login_required
@super_admin_required
def reject_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    flash(f"Expense rejected and deleted. ❌", "warning")
    return redirect(url_for('admin.pending_approvals'))
