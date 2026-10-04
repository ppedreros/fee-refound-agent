"""Auto-approve (SPEC-api, "Auto-approve"; D5). Off in the shipped config and exercised only in
tests. With `AUTO_APPROVE_ENABLED`, a run whose case is clear is approved in-process by the
`SYSTEM` staff member, with the run id as the Idempotency-Key, through the same decision service
Luis uses: money still moves only there. The agent module never acts on the flag.
"""

from uuid import UUID

import structlog

from backend.api.decision_service import Actor, make_decision
from backend.api.errors import ApiError
from backend.api.resources import AppResources
from backend.api.schemas import DecisionRequest
from backend.api.view_model import load_case_view

SYSTEM = "SYSTEM"

log = structlog.get_logger()


async def auto_approve(resources: AppResources, case_id: int, run_id: UUID) -> None:
    async with resources.writer() as session, session.begin():
        view = await load_case_view(session, case_id, resources.policy_params)
        if view.draft is None or "approve" not in view.actions:
            log.info("auto_approve_skipped", case_id=case_id, run_id=str(run_id))
            return
        try:
            await make_decision(
                session,
                case_id,
                run_id,
                DecisionRequest(run_id=run_id, action="approve", reply_text=view.draft.text),
                actor=Actor(staff_id=SYSTEM, now=resources.clock.now(), request_id=None),
                params=resources.policy_params,
            )
        except ApiError as error:  # decided meanwhile, or checked again: Luis's page shows it
            log.info("auto_approve_refused", case_id=case_id, code=error.code)
            return
    log.info("auto_approved", case_id=case_id, run_id=str(run_id))
