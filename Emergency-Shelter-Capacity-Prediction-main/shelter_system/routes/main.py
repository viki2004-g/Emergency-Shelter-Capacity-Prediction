from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user
from extensions import db
from models.shelter import Shelter

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """
    Home page.
    Authenticated users are redirected directly to the mission-critical Dashboard.
    Public visitors see the emergency incident information and shelter request portal.
    """
    if current_user.is_authenticated and current_user.role != 'citizen':
        return redirect(url_for('dashboard.dashboard'))

    active_shelters = Shelter.query.filter_by(status='active').all()
    active_count = len(active_shelters)
    total_capacity = sum(s.max_capacity for s in active_shelters)
    total_occupancy = sum(s.current_occupancy for s in active_shelters)
    available_headroom = max(0, total_capacity - total_occupancy)

    return render_template(
        'main/index.html',
        active_count=active_count,
        total_capacity=total_capacity,
        total_occupancy=total_occupancy,
        available_headroom=available_headroom
    )

