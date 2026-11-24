"""
Models package — imports all ORM models for convenient access.

Usage anywhere in the project:
    from models import User, Shelter, ShelterFacility, Resource
    from models import OccupancyHistory, ShelterRequest, Allocation, Alert

All models use the shared `db` instance from extensions.py.
"""

from models.user       import User
from models.shelter    import Shelter
from models.facility   import ShelterFacility
from models.resource   import Resource
from models.occupancy  import OccupancyHistory
from models.request    import ShelterRequest
from models.allocation import Allocation
from models.alert      import Alert

__all__ = [
    'User',
    'Shelter',
    'ShelterFacility',
    'Resource',
    'OccupancyHistory',
    'ShelterRequest',
    'Allocation',
    'Alert',
]
