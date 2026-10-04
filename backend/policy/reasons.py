"""The reason catalogue (SPEC-policy; D4a in docs/agent-design.md).

Every code Luis can be shown, with its group. Codes live in the database and in evals; Luis only
ever sees their templates.
"""

from enum import StrEnum


class ReasonGroup(StrEnum):
    UNCERTAINTY = "uncertainty"
    FAILURE = "failure"
    POLICY = "policy"
    NOTE = "note"
    ROUTING = "routing"


class ReasonCode(StrEnum):
    # Uncertainty
    INTENT_UNCLEAR = "intent_unclear"
    FEE_AMBIGUOUS = "fee_ambiguous"
    FEE_NOT_FOUND = "fee_not_found"
    MANIPULATION = "manipulation"
    MULTIPLE_REQUESTS = "multiple_requests"
    LANGUAGE_UNSUPPORTED = "language_unsupported"
    FEE_QUESTION = "fee_question"
    # Failures
    CLASSIFIER_DOWN = "classifier_down"
    DATA_TIMEOUT = "data_timeout"
    DATA_MISMATCH = "data_mismatch"
    DRAFTER_DOWN = "drafter_down"
    # Policy
    ALREADY_REFUNDED = "already_refunded"
    YEARLY_LIMIT = "yearly_limit"
    NOT_GOOD_STANDING = "not_good_standing"
    DEPOSIT_NOT_SAME_DAY = "deposit_not_same_day"
    OVER_LIMIT = "over_limit"
    # Notes (they never change the status)
    CLASSIFIED_WITH_BACKUP = "classified_with_backup"
    # Routing
    NOT_FEE_REQUEST = "not_fee_request"

    @property
    def group(self) -> ReasonGroup:
        return GROUPS[self]


GROUPS: dict[ReasonCode, ReasonGroup] = {
    **dict.fromkeys(
        [
            ReasonCode.INTENT_UNCLEAR,
            ReasonCode.FEE_AMBIGUOUS,
            ReasonCode.FEE_NOT_FOUND,
            ReasonCode.MANIPULATION,
            ReasonCode.MULTIPLE_REQUESTS,
            ReasonCode.LANGUAGE_UNSUPPORTED,
            ReasonCode.FEE_QUESTION,
        ],
        ReasonGroup.UNCERTAINTY,
    ),
    **dict.fromkeys(
        [
            ReasonCode.CLASSIFIER_DOWN,
            ReasonCode.DATA_TIMEOUT,
            ReasonCode.DATA_MISMATCH,
            ReasonCode.DRAFTER_DOWN,
        ],
        ReasonGroup.FAILURE,
    ),
    **dict.fromkeys(
        [
            ReasonCode.ALREADY_REFUNDED,
            ReasonCode.YEARLY_LIMIT,
            ReasonCode.NOT_GOOD_STANDING,
            ReasonCode.DEPOSIT_NOT_SAME_DAY,
            ReasonCode.OVER_LIMIT,
        ],
        ReasonGroup.POLICY,
    ),
    ReasonCode.CLASSIFIED_WITH_BACKUP: ReasonGroup.NOTE,
    ReasonCode.NOT_FEE_REQUEST: ReasonGroup.ROUTING,
}
