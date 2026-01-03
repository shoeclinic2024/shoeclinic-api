@admin_bp.route("/edit_manual_task/<int:task_id>", methods=["POST"])
@login_required
@super_admin_required
def edit_manual_task(task_id):
    from models import ManualTask
    task = ManualTask.query.get_or_404(task_id)
    try:
        task.title = request.form.get("title")
        task.task_type = request.form.get("task_type")
        task.customer_name = request.form.get("customer_name")
        task.mobile = request.form.get("mobile")
        
        due_date_str = request.form.get("due_date")
        if due_date_str:
            task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            
        task.assigned_to = request.form.get("assigned_to")
        task.description = request.form.get("description")
        
        db.session.commit()
        flash("Manual task updated successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating manual task: {str(e)}", "danger")
        
    return redirect(url_for('admin.work_assign'))
