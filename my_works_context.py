
@app.context_processor
def inject_my_work_counts():
    if not current_user.is_authenticated:
        return dict(my_work_total_count=0)
        
    try:
        from models import ManualTask, OrderItem
        from datetime import date
        import json
        
        today = date.today()
        
        # 1. Active Manual Tasks
        manual_count = ManualTask.query.filter_by(assigned_to=current_user.username)\
                                       .filter(ManualTask.status.notin_(['done', 'completed'])).count()
                                       
        # 2. Active Order Items (mimicking my_works logic) and 
        #    ensure we catch items where user has ANY incomplete task
        
        # Determine items relevant to user
        search_term = f'%"{current_user.username}"%'
        assigned_items = OrderItem.query.filter(
            (OrderItem.technician == current_user.username) | 
            (OrderItem.service_assignments.ilike(search_term))
        ).all()
        
        active_item_count = 0
        
        
        for item in assigned_items:
            if not item.order:
                continue
                
            # Skip upcoming
            if item.order.assignment_start_date and item.order.assignment_start_date.date() > today:
                continue
                
            # Check if fully done
            st = (item.status or '').lower()
            if st in ['ready to deliver', 'billed', 'delivered', 'done', 'completed']:
                continue
            
            # STRICT ASSIGNMENT CHECK: Only count if user has explicitly assigned tasks
            try:
                assignments = json.loads(item.service_assignments or '{}')
            except:
                assignments = {}
            
            # Check if user has any explicitly assigned tasks
            has_assigned_tasks = False
            
            # Check core services
            if item.services:
                for s in item.services.split(','):
                    s_name = s.strip()
                    if assignments.get(s_name) == current_user.username:
                        has_assigned_tasks = True
                        break
            
            # Check auxiliary/dynamic tasks
            if not has_assigned_tasks:
                for task_name, assigned_user in assignments.items():
                    if assigned_user == current_user.username:
                        has_assigned_tasks = True
                        break
            
            # Only count if user has explicitly assigned tasks (not just supervision)
            if has_assigned_tasks:
                active_item_count += 1
            
        return dict(my_work_total_count=manual_count + active_item_count)
        
    except Exception as e:
        # Fail gracefully
        return dict(my_work_total_count=0)
