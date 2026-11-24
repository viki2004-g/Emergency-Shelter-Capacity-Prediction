"""
services/allocation.py — Transactional Shelter Allocation Service.

Implements strict ACID transactional allocation confirmation and occupancy updates
with pessimistic row-level locking (SELECT ... FOR UPDATE) to eliminate race conditions
and prevent shelter over-allocation under concurrent responder load.

Workflow (8-Step ACID Sequence):
  1. Start database transaction.
  2. Lock relevant shelter & request rows (SELECT ... FOR UPDATE in sorted ID order).
  3. Re-check current safe capacity under lock.
  4. Verify allocation validity (operational status, request status, total count match).
  5. Create confirmed Allocation records.
  6. Update shelter current_occupancy.
  7. Create immutable OccupancyHistory audit records.
  8. Commit transaction.

Rollback Guarantee:
  If any validation, capacity check, or database operation fails at any step,
  the transaction is immediately and completely rolled back with zero orphaned
  records and zero partial mutations.
"""

from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from extensions import db
from models.allocation import Allocation
from models.occupancy import OccupancyHistory
from models.request import ShelterRequest
from models.shelter import Shelter


# ── Custom Exceptions ─────────────────────────────────────────────────────────

class AllocationError(Exception):
    """Base exception for all allocation service errors."""
    pass


class InsufficientCapacityError(AllocationError):
    """Raised when safe available capacity is insufficient to fulfill the allocation."""
    pass


class InvalidAllocationError(AllocationError):
    """Raised when the allocation is invalid (e.g. non-operational shelter, closed request)."""
    pass


class GroupSizeMismatchError(AllocationError):
    """Raised when total allocated evacuees does not match the requested group size."""
    pass


# ── Core Transactional Service Function ───────────────────────────────────────

def confirm_allocation(
    request_id: int,
    allocations: Union[List[Dict[str, Any]], Dict[str, Any]],
    confirmed_by_user_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes an atomic, lock-protected allocation confirmation.

    Acquires exclusive pessimistic row locks on both the ShelterRequest and all target
    Shelters. Shelters are locked in strictly sorted primary key order to prevent deadlocks.
    Re-checks safe available capacity under lock before committing.

    Args:
        request_id:           ID of the ShelterRequest being allocated.
        allocations:          A list of allocation dicts, a single allocation dict,
                              or a redistribution plan dict containing 'allocations'.
                              Each allocation dict must have 'shelter_id' and 'allocated_count'.
        confirmed_by_user_id: ID of the responder/user performing the confirmation.
        notes:                Optional audit/operational notes.

    Returns:
        Dict with keys:
          - 'success': bool (True)
          - 'request_id': int
          - 'total_allocated': int
          - 'allocations': List[Allocation]
          - 'shelters_updated': List[int] (shelter IDs)

    Raises:
        InsufficientCapacityError: If any shelter has insufficient safe capacity under lock.
        InvalidAllocationError:    If input data, request, or shelters are invalid/unsuitable.
        GroupSizeMismatchError:    If total allocated != request.group_size.
    """
    # ── Step 0: Normalize and validate input payload structure ────────────────
    raw_items: List[Dict[str, Any]] = []

    if isinstance(allocations, dict):
        if 'allocations' in allocations and isinstance(allocations['allocations'], list):
            raw_items = allocations['allocations']
        elif 'shelter_id' in allocations and 'allocated_count' in allocations:
            raw_items = [allocations]
        else:
            raise InvalidAllocationError(
                "Invalid allocation payload: expected 'shelter_id' and 'allocated_count' "
                "or a plan dictionary containing an 'allocations' list."
            )
    elif isinstance(allocations, (list, tuple)):
        raw_items = list(allocations)
    else:
        raise InvalidAllocationError(
            f"Unsupported allocation payload type '{type(allocations).__name__}'."
        )

    if not raw_items:
        raise InvalidAllocationError("Cannot confirm an empty allocation plan.")

    # Validate each item structure
    normalized_items: List[Dict[str, int]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise InvalidAllocationError(
                f"Allocation item at index {idx} must be a dictionary, got {type(item).__name__}."
            )
        if 'shelter_id' not in item or 'allocated_count' not in item:
            raise InvalidAllocationError(
                f"Allocation item at index {idx} is missing 'shelter_id' or 'allocated_count'."
            )
        try:
            s_id = int(item['shelter_id'])
            a_count = int(item['allocated_count'])
        except (ValueError, TypeError) as conv_err:
            raise InvalidAllocationError(
                f"Invalid numerical values in allocation item {idx}: {conv_err}"
            ) from conv_err

        if a_count <= 0:
            raise InvalidAllocationError(
                f"Allocated count must be a positive integer, got {a_count} for shelter #{s_id}."
            )

        normalized_items.append({'shelter_id': s_id, 'allocated_count': a_count})

    # Aggregate counts per shelter ID (in case multiple line items target the same shelter)
    aggregated_by_shelter: Dict[int, int] = OrderedDict()
    for item in normalized_items:
        s_id = item['shelter_id']
        aggregated_by_shelter[s_id] = aggregated_by_shelter.get(s_id, 0) + item['allocated_count']

    total_allocated = sum(aggregated_by_shelter.values())

    # ── Step 1: Start a database transaction ──────────────────────────────────
    # Any exception within this block triggers Step rollback.
    try:
        # ── Step 2: Lock the relevant shelter rows appropriately ──────────────
        # Lock ShelterRequest first using SELECT ... FOR UPDATE
        req: Optional[ShelterRequest] = (
            ShelterRequest.query
            .with_for_update()
            .filter_by(id=request_id)
            .first()
        )
        if req is None:
            raise InvalidAllocationError(f"ShelterRequest #{request_id} does not exist.")

        # Deadlock avoidance: Always lock shelters in ascending primary key order!
        # If Transaction A locks (1 then 3) and Transaction B locks (1 then 3),
        # neither can form a circular dependency wait graph.
        sorted_shelter_ids = sorted(aggregated_by_shelter.keys())
        locked_shelters: Dict[int, Shelter] = {}

        for s_id in sorted_shelter_ids:
            shelter: Optional[Shelter] = (
                Shelter.query
                .with_for_update()
                .filter_by(id=s_id)
                .first()
            )
            if shelter is None:
                raise InvalidAllocationError(f"Shelter #{s_id} does not exist in database.")
            locked_shelters[s_id] = shelter

        # ── Step 4a: Verify request state validity ────────────────────────────
        if req.status == 'allocated':
            raise InvalidAllocationError(
                f"ShelterRequest #{request_id} has already been confirmed as 'allocated'."
            )
        if req.status == 'cancelled':
            raise InvalidAllocationError(
                f"ShelterRequest #{request_id} is cancelled and cannot be allocated."
            )

        # ── Step 4b: Verify total allocated == requested group size ───────────
        if total_allocated != req.group_size:
            raise GroupSizeMismatchError(
                f"Total allocated evacuees ({total_allocated}) does not match "
                f"the requested group size ({req.group_size})."
            )

        # ── Step 4c: Verify shelter operational status ────────────────────────
        for s_id in sorted_shelter_ids:
            sh = locked_shelters[s_id]
            if not sh.is_operational:
                raise InvalidAllocationError(
                    f"Shelter '{sh.name}' (#{s_id}) is not operational (status: '{sh.status}')."
                )

        # ── Step 3: Re-check current safe capacity under lock ─────────────────
        # Crucial concurrency guard: now that we hold the exclusive row lock,
        # no other transaction can concurrently mutate this shelter's occupancy.
        for s_id in sorted_shelter_ids:
            sh = locked_shelters[s_id]
            needed = aggregated_by_shelter[s_id]
            safe_avail = sh.safe_available_capacity

            if safe_avail < needed:
                raise InsufficientCapacityError(
                    f"Insufficient safe capacity in shelter '{sh.name}' (#{s_id}): "
                    f"allocation requires {needed} spot(s), but real-time safe available "
                    f"capacity is {safe_avail} (current occupancy: {sh.current_occupancy}/"
                    f"{sh.max_capacity}, safe limit: {sh.safe_limit}%)."
                )

        now = datetime.utcnow()
        created_allocations: List[Allocation] = []

        # ── Step 5: Create Allocation records ─────────────────────────────────
        for item in normalized_items:
            s_id = item['shelter_id']
            count = item['allocated_count']
            sh = locked_shelters[s_id]

            alloc_note = notes or (
                f"Confirmed allocation: {count} of {req.group_size} evacuee(s) placed in '{sh.name}'"
            )
            alloc = Allocation(
                request_id=req.id,
                shelter_id=sh.id,
                allocated_count=count,
                confirmed=True,
                confirmed_by=confirmed_by_user_id,
                confirmed_at=now,
                notes=alloc_note,
                created_at=now,
            )
            db.session.add(alloc)
            created_allocations.append(alloc)

        # ── Step 6: Update shelter occupancy ──────────────────────────────────
        for s_id in sorted_shelter_ids:
            sh = locked_shelters[s_id]
            added_count = aggregated_by_shelter[s_id]
            sh.current_occupancy = sh.current_occupancy + added_count
            sh.updated_at = now

        # ── Step 7: Create occupancy history records ──────────────────────────
        for s_id in sorted_shelter_ids:
            sh = locked_shelters[s_id]
            hist = OccupancyHistory(
                shelter_id=sh.id,
                occupancy=sh.current_occupancy,
                recorded_by=confirmed_by_user_id,
                recorded_at=now,
            )
            db.session.add(hist)

        # Update ShelterRequest status to 'allocated'
        req.status = 'allocated'
        req.updated_at = now

        # ── Step 8: Commit the transaction ────────────────────────────────────
        db.session.commit()

        return {
            'success': True,
            'request_id': req.id,
            'total_allocated': total_allocated,
            'allocations': created_allocations,
            'shelters_updated': sorted_shelter_ids,
        }

    except Exception as err:
        # If ANY step fails: ROLLBACK the transaction immediately!
        db.session.rollback()
        raise err
