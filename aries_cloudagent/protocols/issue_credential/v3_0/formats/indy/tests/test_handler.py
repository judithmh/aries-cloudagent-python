import asyncio
from copy import deepcopy
from time import time
import json
from asynctest import TestCase as AsyncTestCase
from asynctest import mock as async_mock
from marshmallow import ValidationError
from more_itertools import side_effect

from .. import handler as test_module

from .......core.in_memory import InMemoryProfile
from .......ledger.base import BaseLedger
from .......ledger.multiple_ledger.ledger_requests_executor import (
    IndyLedgerRequestsExecutor,
)
from .......multitenant.base import BaseMultitenantManager
from .......multitenant.manager import MultitenantManager
from .......indy.issuer import IndyIssuer
from .......cache.in_memory import InMemoryCache
from .......cache.base import BaseCache
from .......storage.record import StorageRecord
from .......storage.error import StorageNotFoundError
from .......messaging.credential_definitions.util import CRED_DEF_SENT_RECORD_TYPE
from .......messaging.decorators.attach_decorator_didcomm_v2_cred import AttachDecorator
from .......indy.holder import IndyHolder
from ....models.detail.indy import V30CredExRecordIndy
from ....messages.cred_proposal import V30CredProposal
from ....messages.cred_format import V30CredFormat
from ....messages.cred_issue import V30CredIssue
from ....messages.inner.cred_preview import (
    V30CredPreview,
    V30CredAttrSpec,
    V30CredPreviewBody,
)
from ....messages.cred_offer import V30CredOffer
from ....messages.cred_request import (
    V30CredRequest,
)
from ....messages.cred_body import V30CredBody
from ....models.cred_ex_record import V30CredExRecord
from ....message_types import (
    ATTACHMENT_FORMAT,
    CRED_30_PROPOSAL,
    CRED_30_OFFER,
    CRED_30_REQUEST,
    CRED_30_ISSUE,
)

from ...handler import LOGGER, V30CredFormatError

from ..handler import IndyCredFormatHandler
from ..handler import LOGGER as INDY_LOGGER

TEST_DID = "LjgpST2rjsoxYegQDRm7EL"
SCHEMA_NAME = "bc-reg"
SCHEMA_TXN = 12
SCHEMA_ID = f"{TEST_DID}:2:{SCHEMA_NAME}:1.0"
SCHEMA = {
    "ver": "1.0",
    "id": SCHEMA_ID,
    "name": SCHEMA_NAME,
    "version": "1.0",
    "attrNames": ["legalName", "jurisdictionId", "incorporationDate"],
    "seqNo": SCHEMA_TXN,
}
CRED_DEF_ID = f"{TEST_DID}:3:CL:12:tag1"
CRED_DEF = {
    "ver": "1.0",
    "id": CRED_DEF_ID,
    "schemaId": SCHEMA_TXN,
    "type": "CL",
    "tag": "tag1",
    "value": {
        "primary": {
            "n": "...",
            "s": "...",
            "r": {
                "master_secret": "...",
                "legalName": "...",
                "jurisdictionId": "...",
                "incorporationDate": "...",
            },
            "rctxt": "...",
            "z": "...",
        },
        "revocation": {
            "g": "1 ...",
            "g_dash": "1 ...",
            "h": "1 ...",
            "h0": "1 ...",
            "h1": "1 ...",
            "h2": "1 ...",
            "htilde": "1 ...",
            "h_cap": "1 ...",
            "u": "1 ...",
            "pk": "1 ...",
            "y": "1 ...",
        },
    },
}
REV_REG_DEF_TYPE = "CL_ACCUM"
REV_REG_ID = f"{TEST_DID}:4:{CRED_DEF_ID}:{REV_REG_DEF_TYPE}:tag1"
TAILS_DIR = "/tmp/indy/revocation/tails_files"
TAILS_HASH = "8UW1Sz5cqoUnK9hqQk7nvtKK65t7Chu3ui866J23sFyJ"
TAILS_LOCAL = f"{TAILS_DIR}/{TAILS_HASH}"
REV_REG_DEF = {
    "ver": "1.0",
    "id": REV_REG_ID,
    "revocDefType": "CL_ACCUM",
    "tag": "tag1",
    "credDefId": CRED_DEF_ID,
    "value": {
        "issuanceType": "ISSUANCE_ON_DEMAND",
        "maxCredNum": 5,
        "publicKeys": {"accumKey": {"z": "1 ..."}},
        "tailsHash": TAILS_HASH,
        "tailsLocation": TAILS_LOCAL,
    },
}
INDY_OFFER = {
    "schema_id": SCHEMA_ID,
    "cred_def_id": CRED_DEF_ID,
    "key_correctness_proof": {
        "c": "123467890",
        "xz_cap": "12345678901234567890",
        "xr_cap": [
            [
                "remainder",
                "1234567890",
            ],
            [
                "number",
                "12345678901234",
            ],
            [
                "master_secret",
                "12345678901234",
            ],
        ],
    },
    "nonce": "1234567890",
}
INDY_CRED_REQ = {
    "prover_did": TEST_DID,
    "cred_def_id": CRED_DEF_ID,
    "blinded_ms": {
        "u": "12345",
        "ur": "1 123467890ABCDEF",
        "hidden_attributes": ["master_secret"],
        "committed_attributes": {},
    },
    "blinded_ms_correctness_proof": {
        "c": "77777",
        "v_dash_cap": "12345678901234567890",
        "m_caps": {"master_secret": "271283714"},
        "r_caps": {},
    },
    "nonce": "9876543210",
}
INDY_CRED = {
    "schema_id": SCHEMA_ID,
    "cred_def_id": CRED_DEF_ID,
    "rev_reg_id": REV_REG_ID,
    "values": {
        "legalName": {
            "raw": "The Original House of Pies",
            "encoded": "108156129846915621348916581250742315326283968964",
        },
        "busId": {"raw": "11155555", "encoded": "11155555"},
        "jurisdictionId": {"raw": "1", "encoded": "1"},
        "incorporationDate": {
            "raw": "2021-01-01",
            "encoded": "121381685682968329568231",
        },
        "pic": {"raw": "cG90YXRv", "encoded": "125362825623562385689562"},
    },
    "signature": {
        "p_credential": {
            "m_2": "13683295623862356",
            "a": "1925723185621385238953",
            "e": "253516862326",
            "v": "26890295622385628356813632",
        },
        "r_credential": {
            "sigma": "1 00F81D",
            "c": "158698926BD09866E",
            "vr_prime_prime": "105682396DDF1A",
            "witness_signature": {"sigma_i": "1 ...", "u_i": "1 ...", "g_i": "1 ..."},
            "g_i": "1 ...",
            "i": 1,
            "m2": "862186285926592362384FA97FF3A4AB",
        },
    },
    "signature_correctness_proof": {
        "se": "10582965928638296868123",
        "c": "2816389562839651",
    },
    "rev_reg": {"accum": "21 ..."},
    "witness": {"omega": "21 ..."},
}


class TestV30IndyCredFormatHandler(AsyncTestCase):
    async def setUp(self):
        self.session = InMemoryProfile.test_session()
        self.profile = self.session.profile
        self.context = self.profile.context
        setattr(
            self.profile, "session", async_mock.MagicMock(return_value=self.session)
        )

        # Ledger
        Ledger = async_mock.MagicMock()
        self.ledger = Ledger()
        self.ledger.get_schema = async_mock.CoroutineMock(return_value=SCHEMA)
        self.ledger.get_credential_definition = async_mock.CoroutineMock(
            return_value=CRED_DEF
        )
        self.ledger.get_revoc_reg_def = async_mock.CoroutineMock(
            return_value=REV_REG_DEF
        )
        self.ledger.__aenter__ = async_mock.CoroutineMock(return_value=self.ledger)
        self.ledger.credential_definition_id2schema_id = async_mock.CoroutineMock(
            return_value=SCHEMA_ID
        )
        self.context.injector.bind_instance(BaseLedger, self.ledger)
        self.context.injector.bind_instance(
            IndyLedgerRequestsExecutor,
            async_mock.MagicMock(
                get_ledger_for_identifier=async_mock.CoroutineMock(
                    return_value=(None, self.ledger)
                )
            ),
        )
        # Context
        self.cache = InMemoryCache()
        self.context.injector.bind_instance(BaseCache, self.cache)

        # Issuer
        self.issuer = async_mock.MagicMock(IndyIssuer, autospec=True)
        self.context.injector.bind_instance(IndyIssuer, self.issuer)

        # Holder
        self.holder = async_mock.MagicMock(IndyHolder, autospec=True)
        self.context.injector.bind_instance(IndyHolder, self.holder)

        self.handler = IndyCredFormatHandler(self.profile)
        assert self.handler.profile

    async def test_validate_fields(self):
        # Test correct data
        self.handler.validate_fields(CRED_30_PROPOSAL, {"cred_def_id": CRED_DEF_ID})
        self.handler.validate_fields(CRED_30_OFFER, INDY_OFFER)
        self.handler.validate_fields(CRED_30_REQUEST, INDY_CRED_REQ)
        self.handler.validate_fields(CRED_30_ISSUE, INDY_CRED)

        # test incorrect proposal
        with self.assertRaises(ValidationError):
            self.handler.validate_fields(
                CRED_30_PROPOSAL, {"some_random_key": "some_random_value"}
            )

        # test incorrect offer
        with self.assertRaises(ValidationError):
            offer = INDY_OFFER.copy()
            offer.pop("nonce")
            self.handler.validate_fields(CRED_30_OFFER, offer)

        # test incorrect request
        with self.assertRaises(ValidationError):
            req = INDY_CRED_REQ.copy()
            req.pop("nonce")
            self.handler.validate_fields(CRED_30_REQUEST, req)

        # test incorrect cred
        with self.assertRaises(ValidationError):
            cred = INDY_CRED.copy()
            cred.pop("schema_id")
            self.handler.validate_fields(CRED_30_ISSUE, cred)

    async def test_get_indy_detail_record(self):
        cred_ex_id = "dummy"
        details_indy = [
            V30CredExRecordIndy(
                cred_ex_id=cred_ex_id,
                rev_reg_id="rr-id",
                cred_rev_id="0",
            ),
            V30CredExRecordIndy(
                cred_ex_id=cred_ex_id,
                rev_reg_id="rr-id",
                cred_rev_id="1",
            ),
        ]
        await details_indy[0].save(self.session)
        await details_indy[1].save(self.session)  # exercise logger warning on get()

        with async_mock.patch.object(
            INDY_LOGGER, "warning", async_mock.MagicMock()
        ) as mock_warning:
            assert await self.handler.get_detail_record(cred_ex_id) in details_indy
            mock_warning.assert_called_once()

    async def test_check_uniqueness(self):
        with async_mock.patch.object(
            self.handler.format.detail,
            "query_by_cred_ex_id",
            async_mock.CoroutineMock(),
        ) as mock_indy_query:
            mock_indy_query.return_value = []
            await self.handler._check_uniqueness("dummy-cx-id")

        with async_mock.patch.object(
            self.handler.format.detail,
            "query_by_cred_ex_id",
            async_mock.CoroutineMock(),
        ) as mock_indy_query:
            mock_indy_query.return_value = [async_mock.MagicMock()]
            with self.assertRaises(V30CredFormatError) as context:
                await self.handler._check_uniqueness("dummy-cx-id")
            assert "detail record already exists" in str(context.exception)

    async def test_create_proposal(self):
        cred_ex_record = async_mock.MagicMock()
        proposal_data = {"schema_id": SCHEMA_ID}

        (cred_format, attachment) = await self.handler.create_proposal(
            cred_ex_record, proposal_data
        )

        # assert content of attachment is proposal data
        assert attachment.content == proposal_data

        # assert data is encoded as base64
        assert attachment.data.base64

    async def test_create_proposal_none(self):
        cred_ex_record = async_mock.MagicMock()
        proposal_data = None

        (cred_format, attachment) = await self.handler.create_proposal(
            cred_ex_record, proposal_data
        )

        # assert content of attachment is proposal data
        assert attachment.content == {}

    async def test_receive_proposal(self):
        cred_ex_record = async_mock.MagicMock()
        cred_proposal_message = async_mock.MagicMock()

        # Not much to assert. Receive proposal doesn't do anything
        await self.handler.receive_proposal(cred_ex_record, cred_proposal_message)

    async def test_create_offer(self):
        schema_id_parts = SCHEMA_ID.split(":")

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=(
                    V30CredAttrSpec(name="legalName", value="value"),
                    V30CredAttrSpec(name="jurisdictionId", value="value"),
                    V30CredAttrSpec(name="incorporationDate", value="value"),
                )
            )
        )

        cred_proposal = V30CredProposal(
            _body=V30CredBody(credential_preview=cred_preview),
            attachments=[
                AttachDecorator.data_base64(
                    {"cred_def_id": CRED_DEF_ID},
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_PROPOSAL][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_def_record = StorageRecord(
            CRED_DEF_SENT_RECORD_TYPE,
            CRED_DEF_ID,
            {
                "schema_id": SCHEMA_ID,
                "schema_issuer_did": schema_id_parts[0],
                "schema_name": schema_id_parts[-2],
                "schema_version": schema_id_parts[-1],
                "issuer_did": TEST_DID,
                "cred_def_id": CRED_DEF_ID,
                "epoch": str(int(time())),
            },
        )
        await self.session.storage.add_record(cred_def_record)

        self.issuer.create_credential_offer = async_mock.CoroutineMock(
            return_value=json.dumps(INDY_OFFER)
        )

        (cred_format, attachment) = await self.handler.create_offer(cred_proposal)

        self.issuer.create_credential_offer.assert_called_once_with(CRED_DEF_ID)

        # assert content of attachment is proposal data
        assert attachment.content == INDY_OFFER

        # assert data is encoded as base64
        assert attachment.data.base64

        self.issuer.create_credential_offer.reset_mock()
        (cred_format, attachment) = await self.handler.create_offer(cred_proposal)
        self.issuer.create_credential_offer.assert_not_called()

    async def test_create_offer_no_cache(self):
        schema_id_parts = SCHEMA_ID.split(":")

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=(
                    V30CredAttrSpec(name="legalName", value="value"),
                    V30CredAttrSpec(name="jurisdictionId", value="value"),
                    V30CredAttrSpec(name="incorporationDate", value="value"),
                )
            )
        )

        cred_proposal = V30CredProposal(
            _body=V30CredBody(credential_preview=cred_preview),
            attachments=[
                AttachDecorator.data_base64(
                    {"cred_def_id": CRED_DEF_ID},
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_PROPOSAL][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_def_record = StorageRecord(
            CRED_DEF_SENT_RECORD_TYPE,
            CRED_DEF_ID,
            {
                "schema_id": SCHEMA_ID,
                "schema_issuer_did": schema_id_parts[0],
                "schema_name": schema_id_parts[-2],
                "schema_version": schema_id_parts[-1],
                "issuer_did": TEST_DID,
                "cred_def_id": CRED_DEF_ID,
                "epoch": str(int(time())),
            },
        )

        # Remove cache from injection context
        self.context.injector.clear_binding(BaseCache)

        await self.session.storage.add_record(cred_def_record)

        self.issuer.create_credential_offer = async_mock.CoroutineMock(
            return_value=json.dumps(INDY_OFFER)
        )

        (cred_format, attachment) = await self.handler.create_offer(cred_proposal)

        self.issuer.create_credential_offer.assert_called_once_with(CRED_DEF_ID)

        # assert content of attachment is proposal data
        assert attachment.content == INDY_OFFER

        # assert data is encoded as base64
        assert attachment.data.base64

    async def test_create_offer_attr_mismatch(self):
        schema_id_parts = SCHEMA_ID.split(":")

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=(  # names have spaces instead of camel case
                    V30CredAttrSpec(name="legal name", value="value"),
                    V30CredAttrSpec(name="jurisdiction id", value="value"),
                    V30CredAttrSpec(name="incorporation date", value="value"),
                )
            )
        )

        cred_proposal = V30CredProposal(
            _body=V30CredBody(credential_preview=cred_preview),
            attachments=[
                AttachDecorator.data_base64(
                    {"cred_def_id": CRED_DEF_ID},
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_PROPOSAL][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        self.context.injector.bind_instance(
            BaseMultitenantManager,
            async_mock.MagicMock(MultitenantManager, autospec=True),
        )

        cred_def_record = StorageRecord(
            CRED_DEF_SENT_RECORD_TYPE,
            CRED_DEF_ID,
            {
                "schema_id": SCHEMA_ID,
                "schema_issuer_did": schema_id_parts[0],
                "schema_name": schema_id_parts[-2],
                "schema_version": schema_id_parts[-1],
                "issuer_did": TEST_DID,
                "cred_def_id": CRED_DEF_ID,
                "epoch": str(int(time())),
            },
        )
        await self.session.storage.add_record(cred_def_record)

        self.issuer.create_credential_offer = async_mock.CoroutineMock(
            return_value=json.dumps(INDY_OFFER)
        )
        with async_mock.patch.object(
            IndyLedgerRequestsExecutor,
            "get_ledger_for_identifier",
            async_mock.CoroutineMock(return_value=(None, self.ledger)),
        ):
            with self.assertRaises(V30CredFormatError):
                await self.handler.create_offer(cred_proposal)

    async def test_create_offer_no_matching_sent_cred_def(self):
        cred_proposal = V30CredProposal(
            attachments=[
                AttachDecorator.data_base64(
                    {},
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_PROPOSAL][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        self.issuer.create_credential_offer = async_mock.CoroutineMock(
            return_value=json.dumps(INDY_OFFER)
        )

        with self.assertRaises(V30CredFormatError) as context:
            await self.handler.create_offer(cred_proposal)
        assert "Issuer has no operable cred def" in str(context.exception)

    async def test_receive_offer(self):
        cred_ex_record = async_mock.MagicMock()
        cred_offer_message = async_mock.MagicMock()

        # Not much to assert. Receive offer doesn't do anything
        await self.handler.receive_offer(cred_ex_record, cred_offer_message)

    async def test_create_request(self):
        holder_did = "did"

        cred_offer = V30CredOffer(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_ex_record = V30CredExRecord(
            cred_ex_id="dummy-id",
            state=V30CredExRecord.STATE_OFFER_RECEIVED,
            cred_offer=cred_offer.serialize(),
        )

        cred_def = {"cred": "def"}
        self.ledger.get_credential_definition = async_mock.CoroutineMock(
            return_value=cred_def
        )

        cred_req_meta = {}
        self.holder.create_credential_request = async_mock.CoroutineMock(
            return_value=(json.dumps(INDY_CRED_REQ), json.dumps(cred_req_meta))
        )

        (cred_format, attachment) = await self.handler.create_request(
            cred_ex_record, {"holder_did": holder_did}
        )

        self.holder.create_credential_request.assert_called_once_with(
            INDY_OFFER, cred_def, holder_did
        )

        # assert content of attachment is proposal data
        assert attachment.content == INDY_CRED_REQ

        # assert data is encoded as base64
        assert attachment.data.base64

        # cover case with cache (change ID to prevent already exists error)
        cred_ex_record._id = "dummy-id2"
        await self.handler.create_request(cred_ex_record, {"holder_did": holder_did})

        # cover case with no cache in injection context
        self.context.injector.clear_binding(BaseCache)
        cred_ex_record._id = "dummy-id3"
        self.context.injector.bind_instance(
            BaseMultitenantManager,
            async_mock.MagicMock(MultitenantManager, autospec=True),
        )
        with async_mock.patch.object(
            IndyLedgerRequestsExecutor,
            "get_ledger_for_identifier",
            async_mock.CoroutineMock(return_value=(None, self.ledger)),
        ):
            await self.handler.create_request(
                cred_ex_record, {"holder_did": holder_did}
            )

    async def test_create_request_bad_state(self):
        cred_ex_record = V30CredExRecord(state=V30CredExRecord.STATE_OFFER_SENT)

        with self.assertRaises(V30CredFormatError) as context:
            await self.handler.create_request(cred_ex_record)
        assert (
            "Indy issue credential format cannot start from credential request"
            in str(context.exception)
        )

        cred_ex_record.state = None

        with self.assertRaises(V30CredFormatError) as context:
            await self.handler.create_request(cred_ex_record)
        assert (
            "Indy issue credential format cannot start from credential request"
            in str(context.exception)
        )

    async def test_create_request_not_unique_x(self):
        cred_ex_record = V30CredExRecord(state=V30CredExRecord.STATE_OFFER_RECEIVED)

        with async_mock.patch.object(
            self.handler, "_check_uniqueness", async_mock.CoroutineMock()
        ) as mock_unique:
            mock_unique.side_effect = (
                V30CredFormatError("indy detail record already exists"),
            )

            with self.assertRaises(V30CredFormatError) as context:
                await self.handler.create_request(cred_ex_record)

            assert "indy detail record already exists" in str(context.exception)

    async def test_receive_request(self):
        cred_ex_record = async_mock.MagicMock()
        cred_request_message = async_mock.MagicMock()

        # Not much to assert. Receive request doesn't do anything
        await self.handler.receive_request(cred_ex_record, cred_request_message)

    async def test_receive_request_no_offer(self):
        cred_ex_record = async_mock.MagicMock(cred_offer=None)
        cred_request_message = async_mock.MagicMock()

        with self.assertRaises(V30CredFormatError) as context:
            await self.handler.receive_request(cred_ex_record, cred_request_message)

        assert (
            "Indy issue credential format cannot start from credential request"
            in str(context.exception)
        )

    async def test_issue_credential_revocable(self):
        attr_values = {
            "legalName": "value",
            "jurisdictionId": "value",
            "incorporationDate": "value",
        }
        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v) for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(credential_preview=cred_preview),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_ex_record = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            initiator=V30CredExRecord.INITIATOR_SELF,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_REQUEST_RECEIVED,
        )

        cred_rev_id = "1000"
        self.issuer.create_credential = async_mock.CoroutineMock(
            return_value=(json.dumps(INDY_CRED), cred_rev_id)
        )

        with async_mock.patch.object(
            test_module, "IndyRevocation", autospec=True
        ) as revoc:
            revoc.return_value.get_or_create_active_registry = async_mock.CoroutineMock(
                return_value=(
                    async_mock.MagicMock(  # active_rev_reg_rec
                        revoc_reg_id=REV_REG_ID,
                    ),
                    async_mock.MagicMock(  # rev_reg
                        tails_local_path="dummy-path",
                        get_or_fetch_local_tails_path=(async_mock.CoroutineMock()),
                        max_creds=10,
                    ),
                )
            )

            (cred_format, attachment) = await self.handler.issue_credential(
                cred_ex_record, retries=1
            )

            self.issuer.create_credential.assert_called_once_with(
                SCHEMA,
                INDY_OFFER,
                INDY_CRED_REQ,
                attr_values,
                REV_REG_ID,
                "dummy-path",
            )

            # assert content of attachment is proposal data
            assert attachment.content == INDY_CRED

            # assert data is encoded as base64
            assert attachment.data.base64

    async def test_issue_credential_non_revocable(self):
        CRED_DEF_NR = deepcopy(CRED_DEF)
        CRED_DEF_NR["value"]["revocation"] = None
        attr_values = {
            "legalName": "value",
            "jurisdictionId": "value",
            "incorporationDate": "value",
        }
        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v) for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(credential_preview=cred_preview),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_ex_record = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            initiator=V30CredExRecord.INITIATOR_SELF,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_REQUEST_RECEIVED,
        )

        self.issuer.create_credential = async_mock.CoroutineMock(
            return_value=(json.dumps(INDY_CRED), None)
        )
        self.ledger.get_credential_definition = async_mock.CoroutineMock(
            return_value=CRED_DEF_NR
        )
        self.context.injector.bind_instance(
            BaseMultitenantManager,
            async_mock.MagicMock(MultitenantManager, autospec=True),
        )
        with async_mock.patch.object(
            IndyLedgerRequestsExecutor,
            "get_ledger_for_identifier",
            async_mock.CoroutineMock(return_value=("test_ledger_id", self.ledger)),
        ):
            (cred_format, attachment) = await self.handler.issue_credential(
                cred_ex_record, retries=0
            )

            self.issuer.create_credential.assert_called_once_with(
                SCHEMA,
                INDY_OFFER,
                INDY_CRED_REQ,
                attr_values,
                None,
                None,
            )

        # assert content of attachment is proposal data
        assert attachment.content == INDY_CRED

        # assert data is encoded as base64
        assert attachment.data.base64

    async def test_issue_credential_not_unique_x(self):
        cred_ex_record = V30CredExRecord(state=V30CredExRecord.STATE_REQUEST_RECEIVED)

        with async_mock.patch.object(
            self.handler, "_check_uniqueness", async_mock.CoroutineMock()
        ) as mock_unique:
            mock_unique.side_effect = (
                V30CredFormatError("indy detail record already exists"),
            )

            with self.assertRaises(V30CredFormatError) as context:
                await self.handler.issue_credential(cred_ex_record)

            assert "indy detail record already exists" in str(context.exception)

    async def test_issue_credential_no_active_rr_no_retries(self):
        attr_values = {
            "legalName": "value",
            "jurisdictionId": "value",
            "incorporationDate": "value",
        }
        cred_rev_id = "1"

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v) for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(credential_preview=cred_preview),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_ex_record = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            initiator=V30CredExRecord.INITIATOR_SELF,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_REQUEST_RECEIVED,
        )

        self.issuer.create_credential = async_mock.CoroutineMock(
            return_value=(json.dumps(INDY_CRED), cred_rev_id)
        )

        with async_mock.patch.object(
            test_module, "IndyRevocation", autospec=True
        ) as revoc:
            revoc.return_value.get_or_create_active_registry = async_mock.CoroutineMock(
                return_value=()
            )
            with self.assertRaises(V30CredFormatError) as context:
                await self.handler.issue_credential(cred_ex_record, retries=0)
            assert "has no active revocation registry" in str(context.exception)

    async def test_issue_credential_no_active_rr_retry(self):
        attr_values = {
            "legalName": "value",
            "jurisdictionId": "value",
            "incorporationDate": "value",
        }
        cred_rev_id = "1"

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v) for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(
                credential_preview=cred_preview,
            ),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_ex_record = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            initiator=V30CredExRecord.INITIATOR_SELF,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_REQUEST_RECEIVED,
        )

        self.issuer.create_credential = async_mock.CoroutineMock(
            return_value=(json.dumps(INDY_CRED), cred_rev_id)
        )

        with async_mock.patch.object(
            test_module, "IndyRevocation", autospec=True
        ) as revoc:
            revoc.return_value.get_or_create_active_registry = async_mock.CoroutineMock(
                side_effect=[
                    None,
                    (
                        async_mock.MagicMock(  # active_rev_reg_rec
                            revoc_reg_id=REV_REG_ID,
                            set_state=async_mock.CoroutineMock(),
                        ),
                        async_mock.MagicMock(  # rev_reg
                            tails_local_path="dummy-path",
                            get_or_fetch_local_tails_path=(async_mock.CoroutineMock()),
                        ),
                    ),
                ]
            )

            with self.assertRaises(V30CredFormatError) as context:
                await self.handler.issue_credential(cred_ex_record, retries=1)
            assert "has no active revocation registry" in str(context.exception)

    async def test_issue_credential_rr_full(self):
        attr_values = {
            "legalName": "value",
            "jurisdictionId": "value",
            "incorporationDate": "value",
        }
        cred_rev_id = "1"

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v) for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(
                credential_preview=cred_preview,
            ),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        cred_ex_record = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            initiator=V30CredExRecord.INITIATOR_SELF,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_REQUEST_RECEIVED,
        )

        self.issuer.create_credential = async_mock.CoroutineMock(
            side_effect=test_module.IndyIssuerRevocationRegistryFullError("Nope")
        )
        with async_mock.patch.object(
            test_module, "IndyRevocation", autospec=True
        ) as revoc:
            revoc.return_value.get_or_create_active_registry = async_mock.CoroutineMock(
                return_value=(
                    async_mock.MagicMock(  # active_rev_reg_rec
                        revoc_reg_id=REV_REG_ID,
                        set_state=async_mock.CoroutineMock(),
                    ),
                    async_mock.MagicMock(  # rev_reg
                        tails_local_path="dummy-path",
                        get_or_fetch_local_tails_path=(async_mock.CoroutineMock()),
                    ),
                )
            )

            with self.assertRaises(V30CredFormatError) as context:
                await self.handler.issue_credential(cred_ex_record, retries=1)
            assert "has no active revocation registry" in str(context.exception)

    async def test_receive_credential(self):
        cred_ex_record = async_mock.MagicMock()
        cred_issue_message = async_mock.MagicMock()

        # Not much to assert. Receive credential doesn't do anything
        await self.handler.receive_credential(cred_ex_record, cred_issue_message)

    async def test_store_credential(self):
        connection_id = "test_conn_id"
        attr_values = {
            "legalName": ["value", None],
            "jurisdictionId": ["value", None],
            "incorporationDate": ["value", None],
            "pic": ["cG90YXRv", "image/jpeg"],
        }
        cred_req_meta = {"req": "meta"}
        thread_id = "thread-id"

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v[0], mime_type=v[1])
                    for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(
                credential_preview=cred_preview,
            ),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_offer.assign_thread_id(thread_id)
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_issue = V30CredIssue(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_ISSUE][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        stored_cx_rec = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            connection_id=connection_id,
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            cred_issue=cred_issue.serialize(),
            initiator=V30CredExRecord.INITIATOR_EXTERNAL,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_CREDENTIAL_RECEIVED,
            thread_id=thread_id,
            auto_remove=True,
        )

        cred_id = "cred-id"

        self.holder.store_credential = async_mock.CoroutineMock(return_value=cred_id)
        stored_cred = {"stored": "cred"}
        self.holder.get_credential = async_mock.CoroutineMock(
            return_value=json.dumps(stored_cred)
        )

        with async_mock.patch.object(
            test_module, "RevocationRegistry", autospec=True
        ) as mock_rev_reg:
            mock_rev_reg.from_definition = async_mock.MagicMock(
                return_value=async_mock.MagicMock(
                    get_or_fetch_local_tails_path=async_mock.CoroutineMock()
                )
            )
            with self.assertRaises(V30CredFormatError) as context:
                await self.handler.store_credential(stored_cx_rec, cred_id=cred_id)
            assert "No credential exchange " in str(context.exception)
        self.context.injector.bind_instance(
            BaseMultitenantManager,
            async_mock.MagicMock(MultitenantManager, autospec=True),
        )
        with async_mock.patch.object(
            IndyLedgerRequestsExecutor,
            "get_ledger_for_identifier",
            async_mock.CoroutineMock(return_value=("test_ledger_id", self.ledger)),
        ), async_mock.patch.object(
            test_module, "RevocationRegistry", autospec=True
        ) as mock_rev_reg, async_mock.patch.object(
            test_module.IndyCredFormatHandler, "get_detail_record", autospec=True
        ) as mock_get_detail_record:
            mock_rev_reg.from_definition = async_mock.MagicMock(
                return_value=async_mock.MagicMock(
                    get_or_fetch_local_tails_path=async_mock.CoroutineMock()
                )
            )
            mock_get_detail_record.return_value = async_mock.MagicMock(
                cred_request_metadata=cred_req_meta,
                save=async_mock.CoroutineMock(),
            )

            self.ledger.get_credential_definition.reset_mock()
            await self.handler.store_credential(stored_cx_rec, cred_id=cred_id)

            self.ledger.get_credential_definition.assert_called_once_with(CRED_DEF_ID)

            self.holder.store_credential.assert_called_once_with(
                CRED_DEF,
                INDY_CRED,
                cred_req_meta,
                {"pic": "image/jpeg"},
                credential_id=cred_id,
                rev_reg_def=REV_REG_DEF,
            )

    async def test_store_credential_holder_store_indy_error(self):
        connection_id = "test_conn_id"
        attr_values = {
            "legalName": ["value", None],
            "jurisdictionId": ["value", None],
            "incorporationDate": ["value", None],
            "pic": ["cG90YXRv", "image/jpeg"],
        }
        cred_req_meta = {"req": "meta"}
        thread_id = "thread-id"

        cred_preview = V30CredPreview(
            _body=V30CredPreviewBody(
                attributes=[
                    V30CredAttrSpec(name=k, value=v[0], mime_type=v[1])
                    for (k, v) in attr_values.items()
                ]
            )
        )
        cred_offer = V30CredOffer(
            _body=V30CredBody(
                credential_preview=cred_preview,
            ),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_OFFER,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_OFFER][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_offer.assign_thread_id(thread_id)
        cred_request = V30CredRequest(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED_REQ,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_REQUEST][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )
        cred_issue = V30CredIssue(
            _body=V30CredBody(),
            attachments=[
                AttachDecorator.data_base64(
                    INDY_CRED,
                    ident="0",
                    format=V30CredFormat(
                        format_=ATTACHMENT_FORMAT[CRED_30_ISSUE][
                            V30CredFormat.Format.INDY.api
                        ],
                    ),
                )
            ],
        )

        stored_cx_rec = V30CredExRecord(
            cred_ex_id="dummy-cxid",
            connection_id=connection_id,
            cred_offer=cred_offer.serialize(),
            cred_request=cred_request.serialize(),
            cred_issue=cred_issue.serialize(),
            initiator=V30CredExRecord.INITIATOR_EXTERNAL,
            role=V30CredExRecord.ROLE_ISSUER,
            state=V30CredExRecord.STATE_CREDENTIAL_RECEIVED,
            thread_id=thread_id,
            auto_remove=True,
        )

        cred_id = "cred-id"
        self.holder.store_credential = async_mock.CoroutineMock(
            side_effect=test_module.IndyHolderError("Problem", {"message": "Nope"})
        )

        with async_mock.patch.object(
            test_module.IndyCredFormatHandler, "get_detail_record", autospec=True
        ) as mock_get_detail_record, async_mock.patch.object(
            test_module.RevocationRegistry, "from_definition", async_mock.MagicMock()
        ) as mock_rev_reg:
            mock_get_detail_record.return_value = async_mock.MagicMock(
                cred_request_metadata=cred_req_meta,
                save=async_mock.CoroutineMock(),
            )
            mock_rev_reg.return_value = async_mock.MagicMock(
                get_or_fetch_local_tails_path=async_mock.CoroutineMock()
            )
            with self.assertRaises(test_module.IndyHolderError) as context:
                await self.handler.store_credential(stored_cx_rec, cred_id)
            assert "Nope" in str(context.exception)
