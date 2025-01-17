"""Presentation exchange record."""

import logging

from typing import Any, Mapping, Union

from marshmallow import fields, Schema, validate

from .....core.profile import ProfileSession
from .....messaging.models.base_record import BaseExchangeRecord, BaseExchangeSchema
from .....messaging.valid import UUIDFour
from .....storage.base import StorageError

from ..messages.pres import V30Pres, V30PresSchema
from ..messages.pres_format import V30PresFormat
from ..messages.pres_proposal import V30PresProposal, V30PresProposalSchema
from ..messages.pres_request import V30PresRequest, V30PresRequestSchema

from . import UNENCRYPTED_TAGS

LOGGER = logging.getLogger(__name__)


class V30PresExRecord(BaseExchangeRecord):
    """Represents a V3.0 presentation exchange."""

    class Meta:
        """V30PresExRecord metadata."""

        schema_class = "V30PresExRecordSchema"

    RECORD_TYPE = "pres_ex_v30"
    RECORD_ID_NAME = "pres_ex_id"
    RECORD_TOPIC = "present_proof_v3_0"
    TAG_NAMES = {"~thread_id"} if UNENCRYPTED_TAGS else {"thread_id"}

    INITIATOR_SELF = "self"
    INITIATOR_EXTERNAL = "external"

    ROLE_PROVER = "prover"
    ROLE_VERIFIER = "verifier"

    STATE_PROPOSAL_SENT = "proposal-sent"
    STATE_PROPOSAL_RECEIVED = "proposal-received"
    STATE_REQUEST_SENT = "request-sent"
    STATE_REQUEST_RECEIVED = "request-received"
    STATE_PRESENTATION_SENT = "presentation-sent"
    STATE_PRESENTATION_RECEIVED = "presentation-received"
    STATE_DONE = "done"
    STATE_ABANDONED = "abandoned"

    def __init__(
        self,
        *,
        pres_ex_id: str = None,
        connection_id: str = None,
        thread_id: str = None,
        initiator: str = None,
        role: str = None,
        state: str = None,
        pres_proposal: Union[V30PresProposal, Mapping] = None,  # aries message
        pres_request: Union[V30PresRequest, Mapping] = None,  # aries message
        pres: Union[V30Pres, Mapping] = None,  # aries message
        verified: str = None,
        auto_present: bool = False,
        auto_verify: bool = False,
        error_msg: str = None,
        trace: bool = False,  # backward compat: BaseRecord.FromStorage()
        by_format: Mapping = None,  # backward compat: BaseRecord.FromStorage()
        **kwargs,
    ):
        """Initialize a new PresExRecord."""
        super().__init__(pres_ex_id, state, trace=trace, **kwargs)
        self.connection_id = connection_id
        self.thread_id = thread_id
        self.initiator = initiator
        self.role = role
        self.state = state
        self._pres_proposal = V30PresProposal.serde(pres_proposal)
        self._pres_request = V30PresRequest.serde(pres_request)
        self._pres = V30Pres.serde(pres)
        self.verified = verified
        self.auto_present = auto_present
        self.auto_verify = auto_verify
        self.error_msg = error_msg

    @property
    def pres_ex_id(self) -> str:
        """Accessor for the ID associated with this exchange record."""
        return self._id

    @property
    def by_format(self) -> Mapping:
        """Record proposal, request, and presentation attachments by format."""
        result = {}
        for item, cls in {
            "pres_proposal": V30PresProposal,  # note: proof request attached for indy
            "pres_request": V30PresRequest,
            "pres": V30Pres,
        }.items():
            msg = getattr(self, item)

            if msg:
                try:
                    result.update(
                        {
                            item: {
                                V30PresFormat.Format.get(
                                    atch.format.format
                                ).api: msg.attachment(
                                    V30PresFormat.Format.get(atch.format.format)
                                )
                                for atch in msg.attachments
                            }
                        }
                    )
                except AttributeError:
                    result.update({item: {""}})

        return result

    @property
    def pres_proposal(self) -> V30PresProposal:
        """Accessor; get deserialized view."""
        return None if self._pres_proposal is None else self._pres_proposal.de

    @pres_proposal.setter
    def pres_proposal(self, value):
        """Setter; store de/serialized views."""
        self._pres_proposal = V30PresProposal.serde(value)

    @property
    def pres_request(self) -> V30PresRequest:
        """Accessor; get deserialized view."""
        return None if self._pres_request is None else self._pres_request.de

    @pres_request.setter
    def pres_request(self, value):
        """Setter; store de/serialized views."""
        self._pres_request = V30PresRequest.serde(value)

    @property
    def pres(self) -> V30Pres:
        """Accessor; get deserialized view."""
        return None if self._pres is None else self._pres.de

    @pres.setter
    def pres(self, value):
        """Setter; store de/serialized views."""
        self._pres = V30Pres.serde(value)

    async def save_error_state(
        self,
        session: ProfileSession,
        *,
        state: str = None,
        reason: str = None,
        log_params: Mapping[str, Any] = None,
        log_override: bool = False,
    ):
        """
        Save record error state if need be; log and swallow any storage error.

        Args:
            session: The profile session to use
            reason: A reason to add to the log
            log_params: Additional parameters to log
            override: Override configured logging regimen, print to stderr instead
        """

        if self._last_state == state:  # already done
            return

        self.state = state or V30PresExRecord.STATE_ABANDONED
        if reason:
            self.error_msg = reason

        try:
            await self.save(
                session,
                reason=reason,
                log_params=log_params,
                log_override=log_override,
            )
        except StorageError as err:
            LOGGER.exception(err)

    @property
    def record_value(self) -> Mapping:
        """Accessor for the JSON record value generated for this credential exchange."""
        return {
            **{
                prop: getattr(self, prop)
                for prop in (
                    "connection_id",
                    "initiator",
                    "role",
                    "state",
                    "verified",
                    "auto_present",
                    "auto_verify",
                    "error_msg",
                    "trace",
                )
            },
            **{
                prop: getattr(self, f"_{prop}").ser
                for prop in (
                    "pres_proposal",
                    "pres_request",
                    "pres",
                )
                if getattr(self, prop) is not None
            },
        }

    def __eq__(self, other: Any) -> bool:
        """Comparison between records."""
        return super().__eq__(other)


class V30PresExRecordSchema(BaseExchangeSchema):
    """Schema for de/serialization of V3.0 presentation exchange records."""

    class Meta:
        """V30PresExRecordSchema metadata."""

        model_class = V30PresExRecord

    pres_ex_id = fields.Str(
        required=False,
        description="Presentation exchange identifier",
        example=UUIDFour.EXAMPLE,  # typically a UUID4 but not necessarily
    )
    connection_id = fields.Str(
        required=False,
        description="Connection identifier",
        example=UUIDFour.EXAMPLE,  # typically a UUID4 but not necessarily
    )
    thread_id = fields.Str(
        required=False,
        description="Thread identifier",
        example=UUIDFour.EXAMPLE,  # typically a UUID4 but not necessarily
    )
    initiator = fields.Str(
        required=False,
        description="Present-proof exchange initiator: self or external",
        example=V30PresExRecord.INITIATOR_SELF,
        validate=validate.OneOf(
            [
                getattr(V30PresExRecord, m)
                for m in vars(V30PresExRecord)
                if m.startswith("INITIATOR_")
            ]
        ),
    )
    role = fields.Str(
        required=False,
        description="Present-proof exchange role: prover or verifier",
        example=V30PresExRecord.ROLE_PROVER,
        validate=validate.OneOf(
            [
                getattr(V30PresExRecord, m)
                for m in vars(V30PresExRecord)
                if m.startswith("ROLE_")
            ]
        ),
    )
    state = fields.Str(
        required=False,
        description="Present-proof exchange state",
        validate=validate.OneOf(
            [
                getattr(V30PresExRecord, m)
                for m in vars(V30PresExRecord)
                if m.startswith("STATE_")
            ]
        ),
    )
    pres_proposal = fields.Nested(
        V30PresProposalSchema(),
        required=False,
        description="Presentation proposal message",
    )
    pres_request = fields.Nested(
        V30PresRequestSchema(),
        required=False,
        description="Presentation request message",
    )
    pres = fields.Nested(
        V30PresSchema(),
        required=False,
        description="Presentation message",
    )
    by_format = fields.Nested(
        Schema.from_dict(
            {
                "pres_proposal": fields.Dict(required=False),
                "pres_request": fields.Dict(required=False),
                "pres": fields.Dict(required=False),
            },
            name="V30PresExRecordByFormatSchema",
        ),
        required=False,
        description=(
            "Attachment content by format for proposal, request, and presentation"
        ),
        dump_only=True,
    )
    verified = fields.Str(  # tag: must be a string
        required=False,
        description="Whether presentation is verified: 'true' or 'false'",
        example="true",
        validate=validate.OneOf(["true", "false"]),
    )
    auto_present = fields.Bool(
        required=False,
        description="Prover choice to auto-present proof as verifier requests",
        example=False,
    )
    auto_verify = fields.Bool(
        required=False, description="Verifier choice to auto-verify proof presentation"
    )
    error_msg = fields.Str(
        required=False, description="Error message", example="Invalid structure"
    )
