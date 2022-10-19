"""A presentation proposal content message."""

from marshmallow import EXCLUDE, fields, validates_schema, ValidationError
from typing import Sequence

from .....messaging.agent_message import AgentMessage, AgentMessageSchemaV2
from .....messaging.decorators.attach_decorator2 import (
    AttachDecorator,
    AttachDecoratorSchema,
)

from ..message_types import PRES_30_PROPOSAL, PROTOCOL_PACKAGE

from .pres_format import V30PresFormat
from .pres_body import V30PresBody, V30PresBodySchema


HANDLER_CLASS = (
    f"{PROTOCOL_PACKAGE}.handlers.pres_proposal_handler.V30PresProposalHandler"
)


class V30PresProposal(AgentMessage):
    """Class representing a presentation proposal."""

    class Meta:
        """V30PresProposal metadata."""

        handler_class = HANDLER_CLASS
        schema_class = "V30PresProposalSchema"
        message_type = PRES_30_PROPOSAL

    def __init__(
        self,
        _id: str = None,
        *,
        # comment: str = None,
        body: V30PresBody = V30PresBody(),  # is an REQUIRED filed vor didcomV2
        # formats: Sequence[V30PresFormat] = None,
        attachments: Sequence[AttachDecorator] = None,
        **kwargs,
    ):
        """
        Initialize pres proposal object.

        Args:
            body: Body field
            (comment: optional human-readable comment)
            formats: acceptable attachment formats
            attachments: proposal attachments specifying criteria by format
        """
        super().__init__(_id, **kwargs)
        # self.comment = comment, now in:
        self.body = body
        # self.formats = list(formats) if formats else []
        self.attachments = list(attachments) if attachments else []

    def attachment(self, fmt: V30PresFormat.Format = None) -> dict:
        """Return attachment or None if no attachments exists."""
        if len(self.attachments) != 0:
            for att in self.attachments:
                try:
                    if V30PresFormat.Format.get(att.format.format).api == fmt.api:
                        return att.content
                except AttributeError:
                    return None
        else:
            return None


class V30PresProposalSchema(AgentMessageSchemaV2):
    """Presentation proposal schema."""

    class Meta:
        """Presentation proposal schema metadata."""

        model_class = V30PresProposal
        unknown = EXCLUDE

    # comment = fields.Str(description="Human-readable comment", required=False)
    body = fields.Nested(
        # presentation-proposal-msg has no field will_confirm
        V30PresBodySchema(only=("comment", "goal_code")),
        comment="Human-readable comment",
        description="Body descriptor with GoalCode made for PresProof",
        data_key="body",  # def name of field just to make sure
        example="hier könnt ihr body-example stehen",
        required=True,
        allow_none=False,
    )

    attachments = fields.Nested(
        AttachDecoratorSchema,
        many=True,
        # required=True,
        required=False,
        data_key="attachments",
        description="Attachment per acceptable format on corresponding identifier",
    )

    @validates_schema
    def validate_fields(self, data, **kwargs):
        """Validate presentation attachment per format."""

        print(f"data {data}")
        attachments = data.get("attachments") or []
        print(f"attach{attachments}")
        formats = []
        for atch in attachments:
            formats.append(atch.format)
        print(f"formats {formats}")

        if len(formats) != len(attachments):
            raise ValidationError("Formats/attachments length mismatch")

        for atch in attachments:
            # atch = get_attach_by_id(fmt.attach_id)
            pres_format = V30PresFormat.Format.get(atch.format.format)
            if pres_format:
                pres_format.validate_fields(PRES_30_PROPOSAL, atch.content)
