"""V3.0 present-proof indy presentation-exchange format handler."""

import json
import logging


from typing import Mapping, Tuple
from marshmallow import RAISE


from ......indy.holder import IndyHolder
from ......indy.models.predicate import Predicate
from ......indy.models.proof import IndyProofSchema
from ......indy.models.proof_request import IndyProofRequestSchema
from ......indy.models.xform import indy_proof_req_preview2indy_requested_creds
from ......indy.util import generate_pr_nonce
from ......indy.verifier import IndyVerifier
from ......messaging.decorators.attach_decorator_didcomm_v2_pres import AttachDecorator
from ......messaging.util import canon

from ....indy.pres_exch_handler import IndyPresExchHandler

from ...message_types import (
    ATTACHMENT_FORMAT,
    PRES_30_REQUEST,
    PRES_30,
    PRES_30_PROPOSAL,
)
from ...messages.pres import V30Pres
from ...messages.pres_format import V30PresFormat
from ...models.pres_exchange import V30PresExRecord

from ..handler import V30PresFormatHandler, V30PresFormatHandlerError

LOGGER = logging.getLogger(__name__)


class IndyPresExchangeHandler(V30PresFormatHandler):
    """Indy presentation format handler."""

    format = V30PresFormat.Format.INDY

    @classmethod
    def validate_fields(cls, message_type: str, attachment_data: Mapping):
        """Validate attachment data for a specific message type.

        Uses marshmallow schemas to validate if format specific attachment data
        is valid for the specified message type. Only does structural and type
        checks, does not validate if .e.g. the issuer value is valid.


        Args:
            message_type (str): The message type to validate the attachment data for.
                Should be one of the message types as defined in message_types.py
            attachment_data (Mapping): [description]
                The attachment data to valide

        Raises:
            Exception: When the data is not valid.

        """
        mapping = {
            PRES_30_REQUEST: IndyProofRequestSchema,
            PRES_30_PROPOSAL: IndyProofRequestSchema,
            PRES_30: IndyProofSchema,
        }

        # Get schema class
        Schema = mapping[message_type]

        # Validate, throw if not valid
        Schema(unknown=RAISE).load(attachment_data)

    def get_format_identifier(self, message_type: str) -> str:
        """Get attachment format identifier for format and message combination.

        Args:
            message_type (str): Message type for which to return the format identifier

        Returns:
            str: Issue credential attachment format identifier

        """
        return ATTACHMENT_FORMAT[message_type][IndyPresExchangeHandler.format.api]

    def get_format_data(
        self, message_type: str, data: dict
    ) -> Tuple[V30PresFormat, AttachDecorator]:
        """Get presentation format and attach objects for use in pres_ex messages."""
        format = V30PresFormat(
            format_=self.get_format_identifier(message_type),
        )

        return (
            format,
            AttachDecorator.data_base64(
                data, ident=IndyPresExchangeHandler.format.api, format=format
            ),
        )

    async def create_bound_request(
        self,
        pres_ex_record: V30PresExRecord,
        request_data: dict = None,
    ) -> Tuple[V30PresFormat, AttachDecorator]:
        """
        Create a presentation request bound to a proposal.

        Args:
            pres_ex_record: Presentation exchange record for which
                to create presentation request
            request_data: Dict

        Returns:
            A tuple (updated presentation exchange record, presentation request message)

        """
        indy_proof_request = pres_ex_record.pres_proposal.attachments
        for att in indy_proof_request:
            if (
                V30PresFormat.Format.get(att.format.format).api
                == V30PresFormat.Format.INDY.api
            ):
                indy_proof_request = att.content
        if request_data:
            indy_proof_request["name"] = request_data.get("name", "proof-request")
            indy_proof_request["version"] = request_data.get("version", "1.0")
            indy_proof_request["nonce"] = (
                request_data.get("nonce") or await generate_pr_nonce()
            )
        else:
            indy_proof_request["name"] = "proof-request"
            indy_proof_request["version"] = "1.0"
            indy_proof_request["nonce"] = await generate_pr_nonce()
        return self.get_format_data(PRES_30_REQUEST, indy_proof_request)

    async def create_pres(
        self,
        pres_ex_record: V30PresExRecord,
        request_data: dict = None,
    ) -> Tuple[V30PresFormat, AttachDecorator]:
        """Create a presentation."""
        requested_credentials = {}
        if not request_data:
            try:
                proof_request = pres_ex_record.pres_request
                indy_proof_request = proof_request.attachment(
                    IndyPresExchangeHandler.format
                )

                requested_credentials = (
                    await indy_proof_req_preview2indy_requested_creds(
                        indy_proof_request,
                        preview=None,
                        holder=self._profile.inject(IndyHolder),
                    )
                )
            except ValueError as err:
                LOGGER.warning(f"{err}")
                raise V30PresFormatHandlerError(
                    f"No matching Indy credentials found: {err}"
                )
        else:
            if IndyPresExchangeHandler.format.api in request_data:
                indy_spec = request_data.get(IndyPresExchangeHandler.format.api)
                requested_credentials = {
                    "self_attested_attributes": indy_spec["self_attested_attributes"],
                    "requested_attributes": indy_spec["requested_attributes"],
                    "requested_predicates": indy_spec["requested_predicates"],
                }
        indy_handler = IndyPresExchHandler(self._profile)
        indy_proof = await indy_handler.return_presentation(
            pres_ex_record=pres_ex_record,
            requested_credentials=requested_credentials,
        )
        return self.get_format_data(PRES_30, indy_proof)

    async def receive_pres(self, message: V30Pres, pres_ex_record: V30PresExRecord):
        """Receive a presentation and check for presented values vs. proposal request."""

        def _check_proof_vs_proposal():
            """Check for bait and switch in presented values vs. proposal request."""
            proof_req = pres_ex_record.pres_request.attachments

            for att in proof_req:
                if (
                    V30PresFormat.Format.get(att.format.format).api
                    == V30PresFormat.Format.INDY.api
                ):
                    proof_req = att.content

            # revealed attrs
            for reft, attr_spec in proof["requested_proof"]["revealed_attrs"].items():
                proof_req_attr_spec = proof_req["requested_attributes"].get(reft)
                if not proof_req_attr_spec:
                    raise V30PresFormatHandlerError(
                        f"Presentation referent {reft} not in proposal request"
                    )
                req_restrictions = proof_req_attr_spec.get("restrictions", {})

                name = proof_req_attr_spec["name"]
                proof_value = attr_spec["raw"]
                sub_proof_index = attr_spec["sub_proof_index"]
                schema_id = proof["identifiers"][sub_proof_index]["schema_id"]
                cred_def_id = proof["identifiers"][sub_proof_index]["cred_def_id"]
                criteria = {
                    "schema_id": schema_id,
                    "schema_issuer_did": schema_id.split(":")[-4],
                    "schema_name": schema_id.split(":")[-2],
                    "schema_version": schema_id.split(":")[-1],
                    "cred_def_id": cred_def_id,
                    "issuer_did": cred_def_id.split(":")[-5],
                    f"attr::{name}::value": proof_value,
                }

                if (
                    not any(r.items() <= criteria.items() for r in req_restrictions)
                    and len(req_restrictions) != 0
                ):
                    raise V30PresFormatHandlerError(
                        f"Presented attribute {reft} does not satisfy proof request "
                        f"restrictions {req_restrictions}"
                    )

            # revealed attr groups
            for reft, attr_spec in (
                proof["requested_proof"].get("revealed_attr_groups", {}).items()
            ):
                proof_req_attr_spec = proof_req["requested_attributes"].get(reft)
                if not proof_req_attr_spec:
                    raise V30PresFormatHandlerError(
                        f"Presentation referent {reft} not in proposal request"
                    )
                req_restrictions = proof_req_attr_spec.get("restrictions", {})
                proof_values = {
                    name: values["raw"] for name, values in attr_spec["values"].items()
                }
                sub_proof_index = attr_spec["sub_proof_index"]
                schema_id = proof["identifiers"][sub_proof_index]["schema_id"]
                cred_def_id = proof["identifiers"][sub_proof_index]["cred_def_id"]
                criteria = {
                    "schema_id": schema_id,
                    "schema_issuer_did": schema_id.split(":")[-4],
                    "schema_name": schema_id.split(":")[-2],
                    "schema_version": schema_id.split(":")[-1],
                    "cred_def_id": cred_def_id,
                    "issuer_did": cred_def_id.split(":")[-5],
                    **{
                        f"attr::{name}::value": value
                        for name, value in proof_values.items()
                    },
                }

                if (
                    not any(r.items() <= criteria.items() for r in req_restrictions)
                    and len(req_restrictions) != 0
                ):
                    raise V30PresFormatHandlerError(
                        f"Presented attr group {reft} does not satisfy proof request "
                        f"restrictions {req_restrictions}"
                    )

            # predicate bounds
            for reft, pred_spec in proof["requested_proof"]["predicates"].items():
                proof_req_pred_spec = proof_req["requested_predicates"].get(reft)
                if not proof_req_pred_spec:
                    raise V30PresFormatHandlerError(
                        f"Presentation referent {reft} not in proposal request"
                    )
                req_name = proof_req_pred_spec["name"]
                req_pred = Predicate.get(proof_req_pred_spec["p_type"])
                req_value = proof_req_pred_spec["p_value"]
                req_restrictions = proof_req_pred_spec.get("restrictions", {})
                for req_restriction in req_restrictions:
                    for k in [k for k in req_restriction]:  # cannot modify en passant
                        if k.startswith("attr::"):
                            req_restriction.pop(k)  # let indy-sdk reject mismatch here
                sub_proof_index = pred_spec["sub_proof_index"]
                for ge_proof in proof["proof"]["proofs"][sub_proof_index][
                    "primary_proof"
                ]["ge_proofs"]:
                    proof_pred_spec = ge_proof["predicate"]
                    if proof_pred_spec["attr_name"] != canon(req_name):
                        continue
                    if not (
                        Predicate.get(proof_pred_spec["p_type"]) is req_pred
                        and proof_pred_spec["value"] == req_value
                    ):
                        raise V30PresFormatHandlerError(
                            f"Presentation predicate on {req_name} "
                            "mismatches proposal request"
                        )
                    break
                else:
                    raise V30PresFormatHandlerError(
                        f"Proposed request predicate on {req_name} not in presentation"
                    )

                schema_id = proof["identifiers"][sub_proof_index]["schema_id"]
                cred_def_id = proof["identifiers"][sub_proof_index]["cred_def_id"]
                criteria = {
                    "schema_id": schema_id,
                    "schema_issuer_did": schema_id.split(":")[-4],
                    "schema_name": schema_id.split(":")[-2],
                    "schema_version": schema_id.split(":")[-1],
                    "cred_def_id": cred_def_id,
                    "issuer_did": cred_def_id.split(":")[-5],
                }

                if (
                    not any(r.items() <= criteria.items() for r in req_restrictions)
                    and len(req_restrictions) != 0
                ):
                    raise V30PresFormatHandlerError(
                        f"Presented predicate {reft} does not satisfy proof request "
                        f"restrictions {req_restrictions}"
                    )

        proof = message.attachments
        for att in proof:
            if (
                V30PresFormat.Format.get(att.format.format).api
                == V30PresFormat.Format.INDY.api
            ):
                proof = att.content
        _check_proof_vs_proposal()

    async def verify_pres(self, pres_ex_record: V30PresExRecord) -> V30PresExRecord:
        """
        Verify a presentation.

        Args:
            pres_ex_record: presentation exchange record
                with presentation request and presentation to verify

        Returns:
            presentation exchange record, updated

        """
        pres_request_msg = pres_ex_record.pres_request
        indy_proof_request = pres_request_msg.attachments
        for att in indy_proof_request:
            if (
                V30PresFormat.Format.get(att.format.format).api
                == V30PresFormat.Format.INDY.api
            ):
                indy_proof_request = att.content
        indy_proof = pres_ex_record.pres.attachments
        for att in indy_proof:
            if (
                V30PresFormat.Format.get(att.format.format).api
                == V30PresFormat.Format.INDY.api
            ):
                indy_proof = att.content
        indy_handler = IndyPresExchHandler(self._profile)
        (
            schemas,
            cred_defs,
            rev_reg_defs,
            rev_reg_entries,
        ) = await indy_handler.process_pres_identifiers(indy_proof["identifiers"])

        verifier = self._profile.inject(IndyVerifier)
        pres_ex_record.verified = json.dumps(  # tag: needs string value
            await verifier.verify_presentation(
                indy_proof_request,
                indy_proof,
                schemas,
                cred_defs,
                rev_reg_defs,
                rev_reg_entries,
            )
        )
        return pres_ex_record
